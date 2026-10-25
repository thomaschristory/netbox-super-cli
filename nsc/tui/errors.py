"""User-facing messages for NetBox client failures surfaced inside the TUI.

Screens catch ``NetBoxAPIError`` / ``NetBoxClientError`` at every client-call
boundary and render the result of ``api_error_message`` via ``notify`` instead
of letting the exception escape and crash the Textual event loop.
"""

from __future__ import annotations

import json

from nsc.branching.errors import BranchUnusableError
from nsc.branching.unusable import branch_unusable_error
from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.output.sanitize import safe_markup


def active_branch(app: object) -> str | None:
    """The branch the TUI session runs on (`NscTuiApp.active_branch`), if any."""
    branch = getattr(app, "active_branch", None)
    return branch if isinstance(branch, str) else None


def api_error_message(exc: Exception, *, branch: str | None = None) -> str:
    """The message as Textual markup: `notify` parses markup, and the text is
    server data, so it is passed through `safe_markup` (#206)."""
    return safe_markup(_message(exc, branch))


def api_error_text(exc: Exception, *, branch: str | None = None) -> str:
    """Plain (unescaped) one-line text, for callers that sanitize it themselves."""
    unusable = branch_state_error(exc, branch)
    if unusable is not None:
        return str(unusable)
    if isinstance(exc, NetBoxAPIError | NetBoxClientError):
        return exc.render_for_cli()
    return str(exc)


def branch_state_error(exc: Exception, branch: str | None) -> BranchUnusableError | None:
    if isinstance(exc, NetBoxAPIError):
        return branch_unusable_error(exc, branch)
    return None


def _message(exc: Exception, branch: str | None) -> str:
    unusable = branch_state_error(exc, branch)
    if unusable is not None:
        return str(unusable)
    if isinstance(exc, NetBoxAPIError):
        detail = _format_body(exc.body_snippet)
        return f"API {exc.status_code} — {detail}" if detail else f"API {exc.status_code}"
    if isinstance(exc, NetBoxClientError):
        return f"Could not reach NetBox: {exc.cause}"
    return str(exc)


def _format_body(snippet: str) -> str:
    """Turn a NetBox error body into a one-line message.

    NetBox returns field validation errors as ``{"field": ["message", ...]}``;
    surface those as ``field: message``. The snippet may be truncated and thus
    invalid JSON, in which case the raw text is returned as-is.
    """
    text = (snippet or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except ValueError:
        return text
    if isinstance(parsed, dict):
        parts = []
        for field, value in parsed.items():
            message = value[0] if isinstance(value, list) and value else value
            parts.append(f"{field}: {message}")
        return "; ".join(parts)
    return text
