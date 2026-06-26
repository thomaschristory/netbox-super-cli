"""Framework-free lookups over the `saved_searches` config mapping.

Keeps saved-search resolution out of `cli/` and `tui/` so both surfaces share
one implementation and the logic stays unit-testable without any I/O.
"""

from __future__ import annotations

from nsc.config.models import Config


def get_saved_search(config: Config, tag: str, resource: str, name: str) -> dict[str, str] | None:
    """The stored filter params for `<tag>.<resource>.<name>`, or None if absent."""
    params = config.saved_searches.get(tag, {}).get(resource, {}).get(name)
    if params is None:
        return None
    return dict(params)


def list_saved_searches(config: Config, tag: str, resource: str) -> list[str]:
    """Sorted names of saved searches for `<tag>.<resource>` (empty if none)."""
    return sorted(config.saved_searches.get(tag, {}).get(resource, {}))
