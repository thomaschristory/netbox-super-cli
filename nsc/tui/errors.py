"""User-facing messages for NetBox client failures surfaced inside the TUI.

Screens catch ``NetBoxAPIError`` / ``NetBoxClientError`` at every client-call
boundary and render the result of ``api_error_message`` via ``notify`` instead
of letting the exception escape and crash the Textual event loop.
"""

from __future__ import annotations

import json

from nsc.http.errors import NetBoxAPIError, NetBoxClientError


def api_error_message(exc: Exception) -> str:
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
