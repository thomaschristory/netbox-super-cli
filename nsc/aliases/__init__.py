"""Public alias resolver surface.

Imports nothing from `nsc.cli`, `nsc.http`, or any framework — same hard
rule as `nsc.model`. Consumers (`nsc/cli/aliases_commands.py`) call
`resolve(verb, term, command_model)` and pattern-match on the result.
"""

from __future__ import annotations

from nsc.aliases.resolver import (
    AliasVerb,
    AmbiguousAlias,
    ResolvedAlias,
    UnknownAlias,
    resolve,
)

__all__ = [
    "AliasVerb",
    "AmbiguousAlias",
    "ResolvedAlias",
    "UnknownAlias",
    "resolve",
]
