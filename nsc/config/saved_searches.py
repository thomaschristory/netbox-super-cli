"""Framework-free lookups over the `saved_searches` config mapping.

Keeps saved-search resolution out of `cli/` and `tui/` so both surfaces share
one implementation and the logic stays unit-testable without any I/O.
"""

from __future__ import annotations

from nsc.config.models import Config

_MIN_PRINTABLE = 0x20


class InvalidSavedSearchName(ValueError):
    """Raised when a saved-search name is unsafe to persist."""


def validate_saved_search_name(name: str) -> None:
    """Reject names that would corrupt config.yaml or surprise the user.

    Saved searches are persisted at the dotted config path
    ``saved_searches.<tag>.<resource>.<name>`` and the writer splits on ``.``,
    so a name containing ``.`` would be written as a *nested map* rather than a
    leaf — making the whole file fail ``Config.model_validate`` on the next run.
    Control characters and surrounding whitespace are rejected for the same
    "don't persist a name that won't round-trip cleanly" reason.
    """
    if not name or name != name.strip():
        raise InvalidSavedSearchName(
            "saved-search name must be non-empty and not start or end with whitespace"
        )
    if "." in name:
        raise InvalidSavedSearchName(
            f"saved-search name {name!r} may not contain '.' "
            "(it is used as a config-path separator)"
        )
    if any((ch.isspace() and ch != " ") or ord(ch) < _MIN_PRINTABLE for ch in name):
        raise InvalidSavedSearchName(
            f"saved-search name {name!r} may not contain tabs, newlines, "
            "or other control characters"
        )


def get_saved_search(config: Config, tag: str, resource: str, name: str) -> dict[str, str] | None:
    """The stored filter params for `<tag>.<resource>.<name>`, or None if absent."""
    params = config.saved_searches.get(tag, {}).get(resource, {}).get(name)
    if params is None:
        return None
    return dict(params)


def list_saved_searches(config: Config, tag: str, resource: str) -> list[str]:
    """Sorted names of saved searches for `<tag>.<resource>` (empty if none)."""
    return sorted(config.saved_searches.get(tag, {}).get(resource, {}))
