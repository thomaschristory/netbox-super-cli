from __future__ import annotations

from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.tui.errors import api_error_message


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
