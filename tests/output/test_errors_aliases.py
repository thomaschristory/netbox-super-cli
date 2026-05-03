"""Regression tests for Phase 4c ErrorType / EXIT_CODES additions."""

from __future__ import annotations

import json

import pytest

from nsc.output.errors import (
    EXIT_CODES,
    ErrorEnvelope,
    ErrorType,
    ambiguous_alias_envelope,
    render_to_json,
    unknown_alias_envelope,
)


def test_ambiguous_alias_error_type_exists() -> None:
    assert ErrorType.AMBIGUOUS_ALIAS.value == "ambiguous_alias"


def test_unknown_alias_error_type_exists() -> None:
    assert ErrorType.UNKNOWN_ALIAS.value == "unknown_alias"


def test_ambiguous_alias_exit_code_is_13() -> None:
    assert EXIT_CODES[ErrorType.AMBIGUOUS_ALIAS] == 13


def test_unknown_alias_exit_code_is_14() -> None:
    assert EXIT_CODES[ErrorType.UNKNOWN_ALIAS] == 14


def test_existing_exit_codes_unchanged() -> None:
    """Phase 3 contract: EXIT_CODES[INTERNAL..CONFIG] must never move."""
    assert EXIT_CODES[ErrorType.INTERNAL] == 1
    assert EXIT_CODES[ErrorType.SCHEMA] == 3
    assert EXIT_CODES[ErrorType.VALIDATION] == 4
    assert EXIT_CODES[ErrorType.SERVER] == 5
    assert EXIT_CODES[ErrorType.CLIENT] == 6
    assert EXIT_CODES[ErrorType.TRANSPORT] == 7
    assert EXIT_CODES[ErrorType.AUTH] == 8
    assert EXIT_CODES[ErrorType.NOT_FOUND] == 9
    assert EXIT_CODES[ErrorType.CONFLICT] == 10
    assert EXIT_CODES[ErrorType.RATE_LIMITED] == 11
    assert EXIT_CODES[ErrorType.CONFIG] == 12


def test_ambiguous_alias_envelope_lists_candidates() -> None:
    env = ambiguous_alias_envelope(
        verb="ls",
        term="widgets",
        candidates=[("plugin_a", "widgets"), ("plugin_b", "widgets")],
    )
    assert env.type is ErrorType.AMBIGUOUS_ALIAS
    payload = json.loads(render_to_json(env))
    assert payload["type"] == "ambiguous_alias"
    assert payload["details"]["verb"] == "ls"
    assert payload["details"]["term"] == "widgets"
    assert payload["details"]["candidates"] == [
        {"tag": "plugin_a", "resource": "widgets"},
        {"tag": "plugin_b", "resource": "widgets"},
    ]


def test_unknown_alias_envelope_for_missing_resource() -> None:
    env = unknown_alias_envelope(verb="ls", term="nonexistent")
    assert env.type is ErrorType.UNKNOWN_ALIAS
    payload = json.loads(render_to_json(env))
    assert payload["details"]["verb"] == "ls"
    assert payload["details"]["term"] == "nonexistent"
    assert payload["details"]["reason"] == "no_such_resource"
    assert "nsc commands" in payload["error"]


def test_unknown_alias_envelope_for_missing_search_endpoint() -> None:
    env = unknown_alias_envelope(
        verb="search",
        term="anything",
        reason="search_endpoint_unavailable",
    )
    assert env.type is ErrorType.UNKNOWN_ALIAS
    payload = json.loads(render_to_json(env))
    assert payload["details"]["reason"] == "search_endpoint_unavailable"
    # The hint should NOT point to `nsc commands` for this case (it would not help).
    assert "nsc commands" not in payload["error"]


def test_envelope_renders_through_existing_render_to_json() -> None:
    env = ErrorEnvelope(error="x", type=ErrorType.UNKNOWN_ALIAS)
    payload = json.loads(render_to_json(env))
    assert payload["type"] == "unknown_alias"


def test_ambiguous_alias_envelope_rejects_search_verb() -> None:
    """search is never ambiguous (resolver returns UnknownAlias instead).

    Calling ambiguous_alias_envelope with verb="search" is a programming
    error, not a runtime path — assert it raises loudly.
    """
    with pytest.raises(ValueError, match="search"):
        ambiguous_alias_envelope(verb="search", term="anything", candidates=[("a", "b")])
