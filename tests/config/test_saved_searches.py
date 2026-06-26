from __future__ import annotations

import pytest

from nsc.config.models import Config
from nsc.config.saved_searches import (
    InvalidSavedSearchName,
    get_saved_search,
    list_saved_searches,
    validate_saved_search_name,
)


def _config() -> Config:
    return Config.model_validate(
        {
            "saved_searches": {
                "dcim": {
                    "devices": {
                        "active-sw": {"status": "active", "role": "switch"},
                        "offline": {"status": "offline"},
                    }
                }
            }
        }
    )


def test_get_saved_search_hit() -> None:
    assert get_saved_search(_config(), "dcim", "devices", "active-sw") == {
        "status": "active",
        "role": "switch",
    }


def test_get_saved_search_unknown_name_returns_none() -> None:
    assert get_saved_search(_config(), "dcim", "devices", "nope") is None


def test_get_saved_search_unknown_resource_returns_none() -> None:
    assert get_saved_search(_config(), "dcim", "racks", "active-sw") is None


def test_get_saved_search_unknown_tag_returns_none() -> None:
    assert get_saved_search(_config(), "ipam", "devices", "active-sw") is None


def test_get_saved_search_empty_config_returns_none() -> None:
    assert get_saved_search(Config(), "dcim", "devices", "active-sw") is None


def test_list_saved_searches_returns_names_sorted() -> None:
    assert list_saved_searches(_config(), "dcim", "devices") == ["active-sw", "offline"]


def test_list_saved_searches_unknown_resource_returns_empty() -> None:
    assert list_saved_searches(_config(), "dcim", "racks") == []


def test_list_saved_searches_empty_config_returns_empty() -> None:
    assert list_saved_searches(Config(), "dcim", "devices") == []


@pytest.mark.parametrize(
    "name",
    [
        "prod.v2",  # dotted: would split into a nested map under the writer.
        ".",
        "a.b.c",
        "",
        "   ",  # whitespace-only.
        " leading",
        "trailing ",
        "with\ttab",
        "with\nnewline",
        "ctrl\x00null",
    ],
)
def test_validate_saved_search_name_rejects_dangerous(name: str) -> None:
    with pytest.raises(InvalidSavedSearchName):
        validate_saved_search_name(name)


@pytest.mark.parametrize("name", ["active-sw", "prod_v2", "My Switches", "offline 2"])
def test_validate_saved_search_name_accepts_safe(name: str) -> None:
    validate_saved_search_name(name)
