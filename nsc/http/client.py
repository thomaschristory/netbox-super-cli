"""Sync httpx2-based NetBox client."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType
from typing import TYPE_CHECKING, Any, Protocol, cast
from urllib.parse import urlsplit

from nsc.config.models import AuditRedaction
from nsc.config.settings import default_paths
from nsc.http.audit import (
    AuditEntry,
    append_audit_jsonl,
    write_last_request,
)
from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.http.pagination import Pager
from nsc.http.retry import (
    ErrorClass,
    backoff_delay,
    classify_error,
    policy_for_method,
    should_retry,
)
from nsc.model.command_model import HttpMethod

if TYPE_CHECKING:
    import httpx2

_BODY_SNIPPET_BYTES = 2048
BRANCH_HEADER = "X-NetBox-Branch"
_HTTP_5XX_MIN = 500
_HTTP_4XX_MIN = 400


class _ProfileLike(Protocol):
    url: object
    token: str | None
    verify_ssl: bool
    timeout: float


class NetBoxClient:
    def __init__(
        self,
        profile: _ProfileLike,
        *,
        debug: bool = False,
        redaction: AuditRedaction = AuditRedaction.SAFE,
        profile_name: str | None = None,
        branch_resolver: Callable[[NetBoxClient], str] | None = None,
    ) -> None:
        import httpx2  # noqa: PLC0415  # deferred: keeps httpx2 off the CLI-startup path.

        if profile.token is None:
            raise ValueError("NetBoxClient requires a non-None token on the profile")
        self._url = str(profile.url).rstrip("/")
        self._debug = debug
        self._redaction = redaction
        self._profile_name = profile_name
        self._branch_resolver = branch_resolver
        self._branch_pending = branch_resolver is not None
        self._branch_error: BaseException | None = None
        self._branch_lock = threading.Lock()
        self._branch_resolving_thread: int | None = None
        self._client = httpx2.Client(
            base_url=self._url,
            headers={
                "Authorization": f"Token {profile.token}",
                "Accept": "application/json",
            },
            verify=profile.verify_ssl,
            timeout=profile.timeout,
            event_hooks=self._event_hooks() if debug else {},
        )

    def __enter__(self) -> NetBoxClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._send_with_retry(HttpMethod.GET, path, params=params)
        return _parse_json(response)

    def post(
        self,
        path: str,
        *,
        json: Any | None = None,
        operation_id: str | None = None,
        record_indices: list[int] | None = None,
        sensitive_paths: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        response = self._send_with_retry(
            HttpMethod.POST,
            path,
            json_body=json,
            operation_id=operation_id,
            record_indices=record_indices,
            sensitive_paths=sensitive_paths,
        )
        return _parse_json(response)

    def patch(
        self,
        path: str,
        *,
        json: Any | None = None,
        operation_id: str | None = None,
        record_indices: list[int] | None = None,
        sensitive_paths: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        response = self._send_with_retry(
            HttpMethod.PATCH,
            path,
            json_body=json,
            operation_id=operation_id,
            record_indices=record_indices,
            sensitive_paths=sensitive_paths,
        )
        return _parse_json(response)

    def put(
        self,
        path: str,
        *,
        json: Any | None = None,
        operation_id: str | None = None,
        record_indices: list[int] | None = None,
        sensitive_paths: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        response = self._send_with_retry(
            HttpMethod.PUT,
            path,
            json_body=json,
            operation_id=operation_id,
            record_indices=record_indices,
            sensitive_paths=sensitive_paths,
        )
        return _parse_json(response)

    def delete(
        self,
        path: str,
        *,
        operation_id: str | None = None,
        record_indices: list[int] | None = None,
        sensitive_paths: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        response = self._send_with_retry(
            HttpMethod.DELETE,
            path,
            operation_id=operation_id,
            record_indices=record_indices,
            sensitive_paths=sensitive_paths,
        )
        return _parse_json(response)

    def paginate(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        limit: int | None = None,
    ) -> Pager:
        return Pager(self._get_page, path, params, limit=limit, base_path=urlsplit(self._url).path)

    def _get_page(self, path: str, params: dict[str, Any] | None) -> dict[str, Any]:
        return _parse_json(self._send_with_retry(HttpMethod.GET, path, params=params))

    def _send_with_retry(
        self,
        method: HttpMethod,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        operation_id: str | None = None,
        record_indices: list[int] | None = None,
        sensitive_paths: tuple[str, ...] = (),
    ) -> httpx2.Response:
        import httpx2  # noqa: PLC0415  # deferred: keeps httpx2 off the CLI-startup path.

        self.ensure_branch()
        policy = policy_for_method(method)
        attempt = 0
        is_write = method not in {HttpMethod.GET, HttpMethod.HEAD, HttpMethod.OPTIONS}
        indices: list[int] = list(record_indices) if record_indices is not None else []
        while True:
            attempt += 1
            started = time.monotonic()
            try:
                response = self._client.request(method.value, path, params=params, json=json_body)
            except httpx2.RequestError as exc:
                error_class: ErrorClass = classify_error(exc)
                duration_ms = int((time.monotonic() - started) * 1000)
                retry = should_retry(
                    policy, attempt=attempt, status_code=None, error_class=error_class
                )
                self._record_attempt(
                    method=method,
                    path=path,
                    params=params,
                    request_body=json_body,
                    response=None,
                    duration_ms=duration_ms,
                    attempt=attempt,
                    final=not retry,
                    operation_id=operation_id,
                    is_write=is_write,
                    record_indices=indices,
                    sensitive_paths=sensitive_paths,
                )
                if not retry:
                    raise NetBoxClientError(url=self._absolute(path, params), cause=exc) from exc
                time.sleep(backoff_delay(policy, attempt=attempt))
                continue
            duration_ms = int((time.monotonic() - started) * 1000)
            retry = should_retry(
                policy,
                attempt=attempt,
                status_code=response.status_code,
                error_class=None,
            )
            self._record_attempt(
                method=method,
                path=path,
                params=params,
                request_body=json_body,
                response=response,
                duration_ms=duration_ms,
                attempt=attempt,
                final=not retry,
                operation_id=operation_id,
                is_write=is_write,
                record_indices=indices,
                sensitive_paths=sensitive_paths,
            )
            if not retry:
                if response.is_success:
                    return response
                self._raise_for_status(response)
            time.sleep(backoff_delay(policy, attempt=attempt))

    def ensure_branch(self) -> None:
        # Resolved lazily so commands that never hit NetBox pay nothing. Bulk
        # writes run on worker threads, so resolution is serialized: no request
        # may leave before the header is set, and a failed resolution is replayed
        # on every later call — once a branch was asked for, nothing falls
        # through to main.
        if not self._branch_pending:
            return
        if self._branch_resolving_thread == threading.get_ident():
            return  # the resolver's own lookups go out unbranched
        with self._branch_lock:
            if self._branch_error is not None:
                raise self._branch_error
            resolver = self._branch_resolver
            if not self._branch_pending or resolver is None:
                return
            self._branch_resolving_thread = threading.get_ident()
            try:
                schema_id = resolver(self)
            except BaseException as exc:
                self._branch_error = exc
                raise
            finally:
                self._branch_resolving_thread = None
            self._client.headers[BRANCH_HEADER] = schema_id
            self._branch_pending = False

    def _absolute(self, path: str, params: dict[str, Any] | None) -> str:
        request = self._client.build_request("GET", path, params=params)
        return str(request.url)

    def _raise_for_status(self, response: httpx2.Response) -> None:
        try:
            full = response.text
        except Exception:  # pragma: no cover
            full = ""
        raise NetBoxAPIError(
            status_code=response.status_code,
            url=str(response.request.url),
            body_snippet=full[:_BODY_SNIPPET_BYTES],
            headers=dict(response.headers),
            body=full,
        )

    def _record_attempt(
        self,
        *,
        method: HttpMethod,
        path: str,
        params: dict[str, Any] | None,
        request_body: Any | None,
        response: httpx2.Response | None,
        duration_ms: int,
        attempt: int,
        final: bool,
        operation_id: str | None,
        is_write: bool,
        record_indices: list[int],
        sensitive_paths: tuple[str, ...] = (),
    ) -> None:
        url = self._absolute(path, params)
        # httpx2 lowercases all header names; title-case them so the audit log
        # uses the conventional HTTP capitalisation (e.g. "Authorization").
        request_headers = {k.title(): v for k, v in self._client.headers.items()}
        if response is not None:
            status_code: int = response.status_code
            response_headers = dict(response.headers)
            try:
                response_body: Any = response.json() if response.content else None
            except ValueError:
                response_body = response.text[:_BODY_SNIPPET_BYTES]
            if status_code >= _HTTP_5XX_MIN:
                error_kind: str | None = "5xx"
            elif status_code >= _HTTP_4XX_MIN:
                error_kind = "4xx"
            else:
                error_kind = None
            audit_status: int | None = status_code
        else:
            audit_status = None
            response_headers = {}
            response_body = None
            error_kind = "transport"

        entry = AuditEntry(
            timestamp=_now_iso(),
            operation_id=operation_id,
            method=method,
            url=url,
            request_headers=request_headers,
            request_query=dict(params or {}),
            request_body=request_body,
            sensitive_paths=sensitive_paths,
            response_status_code=audit_status,
            response_headers=response_headers,
            response_body=response_body,
            duration_ms=duration_ms,
            attempt_n=attempt,
            final_attempt=final,
            error_kind=error_kind,
            dry_run=False,
            preflight_blocked=False,
            record_indices=list(record_indices),
            applied=is_write,
            explain=False,
            profile=self._profile_name,
            redaction=self._redaction,
        )
        log_dir = default_paths().logs_dir
        write_last_request(entry, path=log_dir / "last-request.json")
        if is_write or self._debug:
            append_audit_jsonl(entry, path=log_dir / "audit.jsonl")

    def _event_hooks(self) -> dict[str, list[Any]]:
        def on_request(request: httpx2.Request) -> None:
            print(f">>> {request.method} {request.url}", file=sys.stderr)
            for k, v in request.headers.items():
                masked = "<redacted>" if k.lower() == "authorization" else v
                print(f">>> {k}: {masked}", file=sys.stderr)

        def on_response(response: httpx2.Response) -> None:
            response.read()
            print(f"<<< {response.status_code} {response.reason_phrase}", file=sys.stderr)
            for k, v in response.headers.items():
                print(f"<<< {k}: {v}", file=sys.stderr)
            body = response.text[:_BODY_SNIPPET_BYTES]
            if body:
                print(f"<<< {body}", file=sys.stderr)

        return {"request": [on_request], "response": [on_response]}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_json(response: httpx2.Response) -> dict[str, Any]:
    if not response.content:
        return {}
    return cast(dict[str, Any], response.json())
