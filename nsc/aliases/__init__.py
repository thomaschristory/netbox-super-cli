"""Public alias resolver surface.

Imports nothing from `nsc.cli`, `nsc.http`, or any framework — same hard
rule as `nsc.model`. Consumers (`nsc/cli/aliases_commands.py`) call
`resolve(verb, term, command_model)` and pattern-match on the result.
"""

from __future__ import annotations

from nsc.aliases.resolver import (
    CURATED_SINGULARS,
    AliasVerb,
    AmbiguousAlias,
    ResolvedAlias,
    UnknownAlias,
    resolve,
    suggest_plural,
)

__all__ = [
    "CURATED_SINGULARS",
    "AliasVerb",
    "AmbiguousAlias",
    "ResolvedAlias",
    "UnknownAlias",
    "resolve",
    "suggest_plural",
]
