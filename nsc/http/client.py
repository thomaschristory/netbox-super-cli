"""Sync httpx-based NetBox client (Phase 2: reads only)."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from types import TracebackType
from typing import Any, Protocol, cast
from urllib.parse import parse_qs, urlsplit

import httpx

from nsc.http.errors import NetBoxAPIError, NetBoxClientError

_BODY_SNIPPET_BYTES = 2048


class _ProfileLike(Protocol):
    url: Any
    token: str | None
    verify_ssl: bool
    timeout: float


class NetBoxClient:
    def __init__(self, profile: _ProfileLike, *, debug: bool = False) -> None:
        if profile.token is None:
            raise ValueError("NetBoxClient requires a non-None token on the profile")
        self._url = str(profile.url).rstrip("/")
        self._client = httpx.Client(
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
        try:
            response = self._client.get(path, params=params)
        except httpx.RequestError as exc:
            raise NetBoxClientError(url=self._absolute(path, params), cause=exc) from exc
        self._raise_for_status(response)
        return _parse_json(response)

    def paginate(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        url: str | None = path
        first = True
        emitted = 0
        while url is not None:
            if first:
                req_path, req_params = url, params
            else:
                # next URLs are absolute; split them so respx (and httpx) can
                # match on path + params independently rather than a raw string.
                parsed = urlsplit(url)
                req_path = parsed.path
                qs = parse_qs(parsed.query, keep_blank_values=True)
                req_params = {k: v[0] for k, v in qs.items()} if qs else None
            try:
                response = self._client.get(req_path, params=req_params)
            except httpx.RequestError as exc:
                raise NetBoxClientError(url=str(url), cause=exc) from exc
            self._raise_for_status(response)
            payload = _parse_json(response)
            for record in payload.get("results", []):
                yield record
                emitted += 1
                if limit is not None and emitted >= limit:
                    return
            url = payload.get("next")
            first = False

    def _absolute(self, path: str, params: dict[str, Any] | None) -> str:
        request = self._client.build_request("GET", path, params=params)
        return str(request.url)

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            body = response.text[:_BODY_SNIPPET_BYTES]
        except Exception:  # pragma: no cover  (httpx already decoded; defensive)
            body = ""
        raise NetBoxAPIError(
            status_code=response.status_code,
            url=str(response.request.url),
            body_snippet=body,
            headers=dict(response.headers),
        )

    def _event_hooks(self) -> dict[str, list[Any]]:
        def on_request(request: httpx.Request) -> None:
            print(f">>> {request.method} {request.url}", file=sys.stderr)
            for k, v in request.headers.items():
                masked = "<redacted>" if k.lower() == "authorization" else v
                print(f">>> {k}: {masked}", file=sys.stderr)

        def on_response(response: httpx.Response) -> None:
            response.read()
            print(f"<<< {response.status_code} {response.reason_phrase}", file=sys.stderr)
            for k, v in response.headers.items():
                print(f"<<< {k}: {v}", file=sys.stderr)
            body = response.text[:_BODY_SNIPPET_BYTES]
            if body:
                print(f"<<< {body}", file=sys.stderr)

        return {"request": [on_request], "response": [on_response]}


def _parse_json(response: httpx.Response) -> dict[str, Any]:
    if not response.content:
        return {}
    return cast(dict[str, Any], response.json())
