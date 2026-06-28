"""Translation between nsc's flat filter params and NetBox SavedFilter shapes.

NetBox's web UI persists a saved filter's form data as a QueryDict-shaped
mapping where every value is a *list* of strings (e.g. ``{"status": ["active"]}``)
and the object is keyed by a unique ``slug``. nsc models active filters as a flat
``dict[str, str]``. These helpers convert between the two so a filter saved in
either surface is usable in the other.
"""

from __future__ import annotations

import re

_SLUG_STRIP = re.compile(r"[^a-z0-9_]+")


def to_netbox_parameters(params: dict[str, str]) -> dict[str, list[str]]:
    """nsc flat params -> NetBox ``parameters`` (each value wrapped in a list)."""
    return {key: [value] for key, value in params.items()}


def from_netbox_parameters(params: dict[str, object]) -> dict[str, str]:
    """NetBox ``parameters`` -> nsc flat params.

    List values flatten to their first element (nsc holds one value per key, so
    a web-UI multi-select degrades to its first value rather than being lost).
    Empty lists, ``None``, and empty strings are skipped.
    """
    out: dict[str, str] = {}
    for key, value in params.items():
        if isinstance(value, list):
            if not value:
                continue
            first = value[0]
            if first is None or first == "":
                continue
            out[key] = str(first)
        elif value is None or value == "":
            continue
        else:
            out[key] = str(value)
    return out


def slugify(name: str) -> str:
    """A NetBox-safe slug for ``name`` (``^[-a-zA-Z0-9_]+$``).

    Lowercases, turns runs of unsafe characters into single hyphens, and strips
    leading/trailing hyphens. Names with no slug-safe characters fall back to a
    short hex digest so the result is always a non-empty, valid slug.
    """
    slug = _SLUG_STRIP.sub("-", name.strip().lower()).strip("-")
    if slug:
        return slug
    return "f-" + name.encode("utf-8").hex()[:12]
