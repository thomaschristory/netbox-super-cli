from __future__ import annotations

from nsc.savedfilters.params import (
    from_netbox_parameters,
    slugify,
    to_netbox_parameters,
)


def test_to_netbox_parameters_wraps_each_value_in_a_list() -> None:
    # NetBox's web UI stores filter form data as a QueryDict-shaped mapping where
    # every value is a list; matching that shape keeps filters interchangeable.
    assert to_netbox_parameters({"status": "active", "site_id": "3"}) == {
        "status": ["active"],
        "site_id": ["3"],
    }


def test_to_netbox_parameters_empty() -> None:
    assert to_netbox_parameters({}) == {}


def test_from_netbox_parameters_flattens_single_element_lists() -> None:
    assert from_netbox_parameters({"status": ["active"], "site_id": ["3"]}) == {
        "status": "active",
        "site_id": "3",
    }


def test_from_netbox_parameters_takes_first_of_multi_value_lists() -> None:
    # nsc's filter state is single-value per key; a web-UI multi-select degrades
    # to its first value rather than being dropped.
    assert from_netbox_parameters({"status": ["active", "offline"]}) == {"status": "active"}


def test_from_netbox_parameters_accepts_scalar_values() -> None:
    assert from_netbox_parameters({"q": "sw1", "limit": 50}) == {"q": "sw1", "limit": "50"}


def test_from_netbox_parameters_skips_empty_and_null() -> None:
    assert from_netbox_parameters({"a": [], "b": None, "c": ["x"], "d": ""}) == {"c": "x"}


def test_round_trip_is_stable_for_single_values() -> None:
    params = {"status": "active", "role": "leaf"}
    assert from_netbox_parameters(to_netbox_parameters(params)) == params


def test_slugify_basic() -> None:
    assert slugify("My Saved Search") == "my-saved-search"


def test_slugify_collapses_and_strips_separators() -> None:
    assert slugify("  Edge // routers!!  ") == "edge-routers"


def test_slugify_keeps_underscores_and_digits() -> None:
    assert slugify("vlan_100 group") == "vlan_100-group"


def test_slugify_non_empty_fallback() -> None:
    # A name with no slug-safe characters still yields a usable, valid slug.
    assert slugify("✦✦✦") != ""
    assert all(c.isalnum() or c in "-_" for c in slugify("✦✦✦"))
