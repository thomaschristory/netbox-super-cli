from __future__ import annotations

import pytest

from nsc.branching.errors import BranchUnusableError
from nsc.branching.unusable import branch_unusable_error
from nsc.http.errors import NetBoxAPIError


def _err(status_code: int, body: str) -> NetBoxAPIError:
    return NetBoxAPIError(
        status_code=status_code,
        url="https://nb/api/dcim/devices/",
        body_snippet=body,
        headers={"Content-Type": "text/html; charset=utf-8"},
    )


def test_status_from_not_ready_for_use_message() -> None:
    exc = _err(400, "Branch my-change is not ready for use (status: merged)")
    err = branch_unusable_error(exc, "my-change")
    assert isinstance(err, BranchUnusableError)
    assert err.branch == "my-change"
    assert err.status == "merged"
    assert "branch 'my-change' is no longer usable (status: merged)" in str(err)


def test_generic_not_ready_message_has_no_status() -> None:
    err = branch_unusable_error(_err(400, "Selected branch is not ready."), "my-change")
    assert err is not None
    assert err.status is None
    assert "branch 'my-change' is no longer usable (status: not ready)" in str(err)


def test_invalid_identifier_means_branch_is_gone() -> None:
    err = branch_unusable_error(_err(400, "Invalid branch identifier\n"), "my-change")
    assert err is not None
    assert err.status is None
    assert "no longer usable (deleted or not found)" in str(err)


def test_message_points_back_to_main() -> None:
    err = branch_unusable_error(_err(400, "Selected branch is not ready."), "b")
    assert err is not None
    assert "--branch main" in str(err)


@pytest.mark.parametrize(
    "body",
    [
        '{"name": ["This field is required."]}',
        '{"detail": "Invalid branch identifier"}',
        "Invalid branch identifier for site",
        "",
    ],
)
def test_other_400s_are_not_branch_state_errors(body: str) -> None:
    assert branch_unusable_error(_err(400, body), "my-change") is None


def test_non_400_is_not_a_branch_state_error() -> None:
    assert branch_unusable_error(_err(404, "Invalid branch identifier"), "b") is None


def test_no_active_branch_never_classifies() -> None:
    assert branch_unusable_error(_err(400, "Selected branch is not ready."), None) is None
