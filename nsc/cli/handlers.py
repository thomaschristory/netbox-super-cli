"""Read and write handlers consumed by the dynamic Typer commands."""

from __future__ import annotations

import json as _json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

import typer

from nsc.cli.runtime import RuntimeContext, apply_limit, emit_envelope, map_error
from nsc.cli.writes.apply import ResolvedRequest
from nsc.cli.writes.apply import resolve as resolve_request
from nsc.cli.writes.bulk import (
    BulkCapability,
    RoutingDecision,
    RoutingMode,
    UnsupportedBulkError,
    detect_bulk_capability,
    route_to_bulk_or_loop,
    run_loop,
)
from nsc.cli.writes.confirmation import (
    refuse_all_on_writes,
    refuse_bulk_and_no_bulk_together,
    refuse_delete_without_id,
    refuse_unknown_on_error,
    refuse_unsupported_bulk,
)
from nsc.cli.writes.input import InputError, NDJSONParseError, RawWriteInput
from nsc.cli.writes.input import collect as collect_input
from nsc.cli.writes.preflight import PreflightResult
from nsc.cli.writes.preflight import check as preflight_check
from nsc.config.models import OutputFormat
from nsc.config.settings import default_paths
from nsc.http.audit import AuditEntry, append_audit_jsonl
from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.model.command_model import HttpMethod, Operation, ParameterLocation
from nsc.output.errors import (
    ClientError,
    ErrorEnvelope,
    ErrorType,
    client_envelope,
    input_error_envelope,
    summary_envelope,
)
from nsc.output.explain import (
    ExplainTrace,
)
from nsc.output.explain import (
    render_to_json as render_explain_json,
)
from nsc.output.explain import (
    render_to_rich_stdout as render_explain_rich,
)
from nsc.output.render import render

_STATUS_NOT_FOUND_DELETE = 404


def parse_filters(raw: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise ValueError(f"--filter expects key=value, got: {item!r}")
        key, _, value = item.partition("=")
        out[key.strip()] = value.strip()
    return out


def handle_list(
    operation: Operation,
    op_tag: str,
    op_resource: str,
    ctx: RuntimeContext,
    *,
    stream: TextIO | None = None,
    **kwargs: Any,
) -> None:
    try:
        params, _ = _split_params(operation, kwargs)
        params.update(parse_filters([f"{k}={v}" for k, v in ctx.filters]))
        iterator = ctx.client.paginate(operation.path, params)
        rows = list(
            apply_limit(
                iterator,
                limit=ctx.limit,
                fetch_all=ctx.fetch_all,
                page_size=ctx.page_size,
            )
        )
        render(
            rows,
            format=ctx.output_format,
            columns=ctx.resolve_columns(op_tag, op_resource, operation),
            stream=stream if stream is not None else sys.stdout,
            compact=ctx.compact,
        )
    except (NetBoxAPIError, NetBoxClientError) as exc:
        env = map_error(exc, operation_id=operation.operation_id)
        code = emit_envelope(env, output_format=ctx.output_format)
        raise typer.Exit(code) from exc


def handle_get(
    operation: Operation,
    op_tag: str,
    op_resource: str,
    ctx: RuntimeContext,
    *,
    stream: TextIO | None = None,
    **kwargs: Any,
) -> None:
    try:
        params, path_vars = _split_params(operation, kwargs)
        obj = ctx.client.get(operation.path.format(**path_vars), params)
        render(
            obj,
            format=ctx.output_format,
            columns=ctx.resolve_columns(op_tag, op_resource, operation),
            stream=stream if stream is not None else sys.stdout,
            compact=ctx.compact,
        )
    except (NetBoxAPIError, NetBoxClientError) as exc:
        env = map_error(exc, operation_id=operation.operation_id)
        code = emit_envelope(env, output_format=ctx.output_format)
        raise typer.Exit(code) from exc


def handle_custom_action(
    operation: Operation,
    op_tag: str,
    op_resource: str,
    ctx: RuntimeContext,
    *,
    stream: TextIO | None = None,
    **kwargs: Any,
) -> None:
    handle_get(operation, op_tag, op_resource, ctx, stream=stream, **kwargs)


def handle_create(
    operation: Operation,
    op_tag: str,
    op_resource: str,
    ctx: RuntimeContext,
    *,
    stream: TextIO | None = None,
    **kwargs: Any,
) -> None:
    _handle_write(
        operation,
        op_tag=op_tag,
        op_resource=op_resource,
        ctx=ctx,
        path_vars=_extract_path_vars(operation, kwargs),
        stream=stream,
        require_id=False,
    )


def handle_update(
    operation: Operation,
    op_tag: str,
    op_resource: str,
    ctx: RuntimeContext,
    *,
    stream: TextIO | None = None,
    **kwargs: Any,
) -> None:
    _handle_write(
        operation,
        op_tag=op_tag,
        op_resource=op_resource,
        ctx=ctx,
        path_vars=_extract_path_vars(operation, kwargs),
        stream=stream,
        require_id=True,
    )


def handle_delete(
    operation: Operation,
    op_tag: str,
    op_resource: str,
    ctx: RuntimeContext,
    *,
    stream: TextIO | None = None,
    **kwargs: Any,
) -> None:
    _handle_write(
        operation,
        op_tag=op_tag,
        op_resource=op_resource,
        ctx=ctx,
        path_vars=_extract_path_vars(operation, kwargs),
        stream=stream,
        require_id=True,
    )


def handle_custom_action_write(
    operation: Operation,
    op_tag: str,
    op_resource: str,
    ctx: RuntimeContext,
    *,
    stream: TextIO | None = None,
    **kwargs: Any,
) -> None:
    _handle_write(
        operation,
        op_tag=op_tag,
        op_resource=op_resource,
        ctx=ctx,
        path_vars=_extract_path_vars(operation, kwargs),
        stream=stream,
        require_id=False,
    )


def _handle_write(
    operation: Operation,
    *,
    op_tag: str,
    op_resource: str,
    ctx: RuntimeContext,
    path_vars: dict[str, str],
    stream: TextIO | None,
    require_id: bool,
) -> None:
    out = stream if stream is not None else sys.stdout
    try:
        if ctx.fetch_all:
            refuse_all_on_writes(operation_id=operation.operation_id)
        path_param_names = {
            p.name for p in operation.parameters if p.location is ParameterLocation.PATH
        }
        if require_id and "id" in path_param_names and not path_vars.get("id"):
            refuse_delete_without_id(operation_id=operation.operation_id)

        refuse_bulk_and_no_bulk_together(
            bulk=ctx.bulk is True,
            no_bulk=ctx.no_bulk is True,
            operation_id=operation.operation_id,
        )
        refuse_unknown_on_error(ctx.on_error)

        is_delete = operation.http_method is HttpMethod.DELETE
        if is_delete:
            raw = RawWriteInput(records=[{}], source="fields_only")
        else:
            raw = collect_input(
                file=Path(ctx.file) if ctx.file else None,
                fields=list(ctx.fields),
                stdin=sys.stdin if ctx.file == "-" else None,
            )

        decision = _decide_routing(operation, ctx, raw)

        preflight = preflight_check(raw, operation)
        resolved = resolve_request(
            raw,
            operation,
            path_vars=path_vars,
            base_url=str(ctx.resolved_profile.url),
            headers={
                "Authorization": f"Token {ctx.resolved_profile.token}",
                "Accept": "application/json",
            },
            mode=decision.mode,
        )
        field_overrides = {f.split("=", 1)[0].split(".")[0] for f in ctx.fields if "=" in f}
        trace = ExplainTrace.build_for(
            operation,
            raw,
            preflight,
            resolved,
            field_overrides=field_overrides,
            routing_decision=decision,
        )

        if _handle_dry_run_or_preflight(operation, ctx, resolved, preflight, trace, out=out):
            return

        if ctx.explain:
            _render_explain_or_dry_run(trace, ctx, stream=out)

        if decision.mode is RoutingMode.LOOP:
            _execute_loop(
                operation,
                resolved,
                ctx,
                op_tag=op_tag,
                op_resource=op_resource,
                stream=out,
                total_records=len(raw.records),
                is_delete=is_delete,
            )
            return

        response = _send_one(operation, resolved[0], ctx)
        _render_response(
            operation,
            response,
            ctx,
            op_tag=op_tag,
            op_resource=op_resource,
            stream=out,
            is_delete=is_delete,
        )
    except ClientError as exc:
        code = emit_envelope(exc.envelope, output_format=ctx.output_format)
        raise typer.Exit(code) from exc
    except NDJSONParseError as exc:
        env = input_error_envelope(
            message=str(exc),
            bad_lines=exc.bad_lines,
            operation_id=operation.operation_id,
        )
        code = emit_envelope(env, output_format=ctx.output_format)
        raise typer.Exit(code) from exc
    except InputError as exc:
        env = client_envelope(str(exc), operation_id=operation.operation_id)
        code = emit_envelope(env, output_format=ctx.output_format)
        raise typer.Exit(code) from exc
    except (NetBoxAPIError, NetBoxClientError) as exc:
        if (
            isinstance(exc, NetBoxAPIError)
            and exc.status_code == _STATUS_NOT_FOUND_DELETE
            and operation.http_method is HttpMethod.DELETE
            and not ctx.strict
        ):
            _render_delete_already_absent(ctx, stream=out)
            return
        env = map_error(exc, operation_id=operation.operation_id)
        code = emit_envelope(env, output_format=ctx.output_format)
        raise typer.Exit(code) from exc


def _handle_dry_run_or_preflight(
    operation: Operation,
    ctx: RuntimeContext,
    resolved: list[ResolvedRequest],
    preflight: PreflightResult,
    trace: ExplainTrace,
    *,
    out: TextIO,
) -> bool:
    """Handle dry-run rendering and preflight-blocked envelope emission.

    Returns True if the caller should return immediately (dry-run path);
    False to continue to the apply path. Raises `typer.Exit` if preflight
    failed (in either dry-run or apply mode).
    """
    if not ctx.apply:
        _emit_dry_run_audit(operation, resolved, preflight, ctx)
        _render_explain_or_dry_run(trace, ctx, stream=out)
        if not preflight.ok:
            env = _preflight_envelope(operation, preflight, applied=False)
            code = emit_envelope(env, output_format=ctx.output_format)
            raise typer.Exit(code)
        return True
    if not preflight.ok:
        _emit_dry_run_audit(operation, resolved, preflight, ctx, preflight_blocked=True)
        env = _preflight_envelope(operation, preflight, applied=False)
        code = emit_envelope(env, output_format=ctx.output_format)
        raise typer.Exit(code)
    return False


def _decide_routing(
    operation: Operation,
    ctx: RuntimeContext,
    raw: RawWriteInput,
) -> RoutingDecision:
    """Compute the routing decision and emit the AMBIGUOUS warning.

    Wraps `UnsupportedBulkError` into a ClientError via `refuse_unsupported_bulk`.
    """
    capability = detect_bulk_capability(operation)
    if ctx.bulk is True:
        bulk_flag: bool | None = True
    elif ctx.no_bulk is True:
        bulk_flag = False
    else:
        bulk_flag = None
    try:
        decision = route_to_bulk_or_loop(
            record_count=len(raw.records),
            capability=capability,
            bulk_flag=bulk_flag,
        )
    except UnsupportedBulkError as exc:
        refuse_unsupported_bulk(exc, operation_id=operation.operation_id)
        raise  # unreachable; refuse_unsupported_bulk always raises
    if capability is BulkCapability.AMBIGUOUS:
        print(
            f"warning: bulk capability for {operation.operation_id} is ambiguous; "
            f"treating as {decision.mode.value} (use --bulk or --no-bulk to be explicit)",
            file=sys.stderr,
        )
    return decision


def _execute_loop(
    operation: Operation,
    requests: list[ResolvedRequest],
    ctx: RuntimeContext,
    *,
    op_tag: str,
    op_resource: str,
    stream: TextIO,
    total_records: int,
    is_delete: bool,
) -> None:
    """Run the sequential loop and emit summary envelope on any failure."""

    def _send_one_loop(op: Operation, request: ResolvedRequest) -> dict[str, Any]:
        return _send_one(op, request, ctx)

    def _audit_one(
        _request: ResolvedRequest,
        _response: dict[str, Any] | None,
        _err: Exception | None,
    ) -> None:
        # NetBoxClient.{post,patch,put,delete} already writes one audit entry
        # per HTTP request. Writing here would double-count. The callback
        # exists so unit tests can verify per-attempt ordering; production
        # wiring leaves it as a no-op.
        return

    def _to_envelope(exc: Exception) -> ErrorEnvelope:
        if isinstance(exc, NetBoxAPIError | NetBoxClientError):
            return map_error(exc, operation_id=operation.operation_id)
        return ErrorEnvelope(
            error=str(exc),
            type=ErrorType.INTERNAL,
            operation_id=operation.operation_id,
        )

    result = run_loop(
        requests,
        operation=operation,
        on_error=ctx.on_error,
        send_one=_send_one_loop,
        audit_attempt=_audit_one,
        to_envelope=_to_envelope,
    )

    failures: list[ErrorEnvelope] = []
    for attempt in result.attempts:
        if attempt.failure is None:
            continue
        idx = attempt.request.record_indices[0]
        failures.append(attempt.failure.model_copy(update={"record_index": idx}))

    if not failures:
        last_response = result.attempts[-1].response or {}
        _render_response(
            operation,
            last_response,
            ctx,
            op_tag=op_tag,
            op_resource=op_resource,
            stream=stream,
            is_delete=is_delete,
        )
        return

    env = summary_envelope(
        attempted=result.attempted,
        failures=failures,
        on_error=ctx.on_error,
        operation_id=operation.operation_id,
        total_records=total_records,
    )
    code = emit_envelope(env, output_format=ctx.output_format)
    raise typer.Exit(code)


def _extract_path_vars(operation: Operation, kwargs: dict[str, Any]) -> dict[str, str]:
    path_names = {p.name for p in operation.parameters if p.location is ParameterLocation.PATH}
    return {k: str(v) for k, v in kwargs.items() if k in path_names and v is not None}


def _emit_dry_run_audit(
    operation: Operation,
    resolved: list[ResolvedRequest],
    preflight: PreflightResult,
    ctx: RuntimeContext,
    *,
    preflight_blocked: bool = False,
) -> None:
    log_dir = default_paths().logs_dir
    sensitive_paths = (
        operation.request_body.sensitive_paths if operation.request_body is not None else ()
    )
    for r in resolved:
        entry = AuditEntry(
            timestamp=_now_iso(),
            operation_id=operation.operation_id,
            method=operation.http_method,
            url=r.url,
            request_headers={
                "Authorization": f"Token {ctx.resolved_profile.token}",
                "Accept": "application/json",
            },
            request_query=dict(r.query or {}),
            request_body=r.body,
            sensitive_paths=sensitive_paths,
            response_status_code=None,
            response_headers={},
            response_body=None,
            duration_ms=None,
            attempt_n=1,
            final_attempt=True,
            error_kind="preflight" if preflight_blocked else None,
            dry_run=True,
            preflight_blocked=preflight_blocked,
            record_indices=list(r.record_indices),
            applied=False,
            explain=ctx.explain,
        )
        append_audit_jsonl(entry, path=log_dir / "audit.jsonl")
    _ = preflight  # currently consumed only via preflight_blocked


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _render_explain_or_dry_run(trace: ExplainTrace, ctx: RuntimeContext, *, stream: TextIO) -> None:
    if ctx.output_format is OutputFormat.JSON:
        print(render_explain_json(trace), file=stream)
    elif ctx.output_format is OutputFormat.TABLE:
        render_explain_rich(trace, stream=stream)
    else:
        # CSV/YAML/JSONL on dry-run → JSON to stdout (the formatters expect rows,
        # not a structured trace). Consistent with spec §4.2.3 fallback rules.
        print(render_explain_json(trace), file=stream)


def _send_one(
    operation: Operation, request: ResolvedRequest, ctx: RuntimeContext
) -> dict[str, Any]:
    relative = operation.path.format(**request.path_vars)
    indices = list(request.record_indices)
    sensitive_paths = (
        operation.request_body.sensitive_paths if operation.request_body is not None else ()
    )
    if operation.http_method is HttpMethod.POST:
        return ctx.client.post(
            relative,
            json=request.body,
            operation_id=operation.operation_id,
            record_indices=indices,
            sensitive_paths=sensitive_paths,
        )
    if operation.http_method is HttpMethod.PATCH:
        return ctx.client.patch(
            relative,
            json=request.body,
            operation_id=operation.operation_id,
            record_indices=indices,
            sensitive_paths=sensitive_paths,
        )
    if operation.http_method is HttpMethod.PUT:
        return ctx.client.put(
            relative,
            json=request.body,
            operation_id=operation.operation_id,
            record_indices=indices,
            sensitive_paths=sensitive_paths,
        )
    if operation.http_method is HttpMethod.DELETE:
        return ctx.client.delete(
            relative,
            operation_id=operation.operation_id,
            record_indices=indices,
            sensitive_paths=sensitive_paths,
        )
    raise RuntimeError(f"unsupported write method: {operation.http_method}")


def _render_response(
    operation: Operation,
    response: dict[str, Any],
    ctx: RuntimeContext,
    *,
    op_tag: str,
    op_resource: str,
    stream: TextIO,
    is_delete: bool,
) -> None:
    if is_delete:
        _render_delete_ok(ctx, stream=stream)
        return
    render(
        response,
        format=ctx.output_format,
        columns=ctx.resolve_columns(op_tag, op_resource, operation),
        stream=stream,
        compact=ctx.compact,
    )


def _render_delete_ok(ctx: RuntimeContext, *, stream: TextIO) -> None:
    payload = {"deleted": True}
    if ctx.output_format is OutputFormat.JSON:
        print(_json.dumps(payload), file=stream)
    else:
        print("deleted", file=stream)


def _render_delete_already_absent(ctx: RuntimeContext, *, stream: TextIO) -> None:
    payload = {"deleted": False, "reason": "already_absent"}
    if ctx.output_format is OutputFormat.JSON:
        print(_json.dumps(payload), file=stream)
    else:
        print("already absent (no change)", file=stream)


def _preflight_envelope(
    operation: Operation, preflight: PreflightResult, *, applied: bool
) -> ErrorEnvelope:
    issues = [
        {
            "record_index": i.record_index,
            "field_path": i.field_path,
            "kind": i.kind,
            "message": i.message,
            "expected": i.expected,
        }
        for i in preflight.issues
    ]
    return ErrorEnvelope(
        error="preflight validation failed",
        type=ErrorType.VALIDATION,
        operation_id=operation.operation_id,
        details={"source": "preflight", "issues": issues, "applied": applied},
    )


def _split_params(
    operation: Operation, kwargs: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    path_names = {p.name for p in operation.parameters if p.location is ParameterLocation.PATH}
    query: dict[str, Any] = {}
    path: dict[str, Any] = {}
    for k, v in kwargs.items():
        if v is None:
            continue
        if k in path_names:
            path[k] = v
        else:
            query[k] = v
    return query, path
