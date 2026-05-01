from __future__ import annotations

from nsc.http.errors import NetBoxAPIError, NetBoxClientError


def test_api_error_carries_status_url_body_headers() -> None:
    err = NetBoxAPIError(
        status_code=404,
        url="https://nb.example/api/dcim/devices/9999/",
        body_snippet='{"detail": "Not found."}',
        headers={"content-type": "application/json"},
    )
    assert err.status_code == 404
    assert "404" in err.render_for_cli()
    assert "Not found" in err.render_for_cli()


def test_api_error_truncates_long_bodies() -> None:
    huge = "x" * 5000
    err = NetBoxAPIError(
        status_code=500, url="https://nb.example/api/", body_snippet=huge[:2048], headers={}
    )
    rendered = err.render_for_cli()
    assert len(rendered) < 4000


def test_client_error_wraps_transport_failure() -> None:
    cause = ConnectionError("dns failure")
    err = NetBoxClientError(url="https://nb.example/api/", cause=cause)
    assert "dns failure" in err.render_for_cli()
    assert err.cause is cause
