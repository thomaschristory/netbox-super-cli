from __future__ import annotations

from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.tui.errors import api_error_message, api_error_text


def test_api_error_formats_netbox_field_validation_body() -> None:
    exc = NetBoxAPIError(
        status_code=400,
        url="https://nb/api/dcim/devices/?manufacturer=Cisco",
        body_snippet='{"manufacturer": ["Cisco is not a valid choice."]}',
        headers={},
    )
    assert api_error_message(exc) == "API 400 — manufacturer: Cisco is not a valid choice."


def test_api_error_falls_back_to_raw_snippet_when_not_json() -> None:
    exc = NetBoxAPIError(status_code=500, url="https://nb/api/x/", body_snippet="boom", headers={})
    assert api_error_message(exc) == "API 500 — boom"


def test_api_error_with_empty_body_shows_only_status() -> None:
    exc = NetBoxAPIError(status_code=404, url="https://nb/api/x/", body_snippet="", headers={})
    assert api_error_message(exc) == "API 404"


def test_client_error_reports_unreachable() -> None:
    exc = NetBoxClientError(url="https://nb/api/x/", cause=OSError("name resolution failed"))
    assert api_error_message(exc) == "Could not reach NetBox: name resolution failed"


def _branch_400(body: str) -> NetBoxAPIError:
    return NetBoxAPIError(status_code=400, url="https://nb/api/x/", body_snippet=body, headers={})


def test_branch_state_error_is_explained_when_a_branch_is_active() -> None:
    exc = _branch_400("Branch b1 is not ready for use (status: archived)")
    message = api_error_message(exc, branch="b1")
    assert "branch 'b1' is no longer usable (status: archived)" in message
    assert not message.startswith("API 400")


def test_branch_state_body_without_active_branch_renders_unchanged() -> None:
    exc = _branch_400("Invalid branch identifier")
    assert api_error_message(exc) == "API 400 — Invalid branch identifier"


def test_validation_400_with_active_branch_renders_unchanged() -> None:
    exc = _branch_400('{"name": ["This field is required."]}')
    assert api_error_message(exc, branch="b1") == "API 400 — name: This field is required."


def test_branch_state_message_sanitizes_branch_name() -> None:
    message = api_error_message(_branch_400("Invalid branch identifier"), branch="[bold]x\x1b]0;t")
    assert "\x1b" not in message
    assert "\\[bold]" in message


def test_api_error_text_is_plain_not_markup() -> None:
    exc = _branch_400("Invalid branch identifier")
    assert api_error_text(exc, branch="[b]").startswith("branch '[b]' is no longer usable")
    other = NetBoxAPIError(
        status_code=500, url="https://nb/api/x/", body_snippet="boom", headers={}
    )
    assert api_error_text(other, branch="b") == "NetBox API 500 on https://nb/api/x/: boom"
