"""Pure resolver for `nsc ls / get / rm / search`.

Exposes `resolve(verb, term, command_model)` returning one of
`ResolvedAlias / AmbiguousAlias / UnknownAlias`. No I/O, no Typer, no
HTTP — caller wires the result into the dynamic-tree handlers.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from nsc.model.command_model import CommandModel, HttpMethod, Operation, Resource


class AliasVerb(StrEnum):
    LS = "ls"
    GET = "get"
    RM = "rm"
    SEARCH = "search"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ResolvedAlias(_Frozen):
    """Exactly one (tag, resource, operation) triple matched the term."""

    tag: str
    resource_name: str
    operation: Operation


class AmbiguousAlias(_Frozen):
    """>=2 (tag, resource) pairs matched. Sorted lexicographically by tag, then resource."""

    verb: AliasVerb
    term: str
    candidates: list[tuple[str, str]]


class UnknownAlias(_Frozen):
    """0 matches for ls/get/rm; or `/api/search/` missing for search."""

    verb: AliasVerb
    term: str
    reason: str = "no_such_resource"


def resolve(
    verb: AliasVerb, term: str, model: CommandModel
) -> ResolvedAlias | AmbiguousAlias | UnknownAlias:
    if verb is AliasVerb.SEARCH:
        return _resolve_search(term, model)
    return _resolve_term(verb, term, model)


def _resolve_term(
    verb: AliasVerb, term: str, model: CommandModel
) -> ResolvedAlias | AmbiguousAlias | UnknownAlias:
    needle = term.lower()
    candidates: list[tuple[str, str, Operation]] = []
    for tag_name in sorted(model.tags):
        tag = model.tags[tag_name]
        for resource_name in sorted(tag.resources):
            if resource_name.lower() != needle:
                continue
            resource = tag.resources[resource_name]
            op = _required_op_for(verb, resource)
            if op is None:
                continue
            candidates.append((tag_name, resource_name, op))
    if len(candidates) == 1:
        resolved_tag, resolved_resource, resolved_op = candidates[0]
        return ResolvedAlias(
            tag=resolved_tag, resource_name=resolved_resource, operation=resolved_op
        )
    if len(candidates) > 1:
        return AmbiguousAlias(
            verb=verb,
            term=term,
            candidates=[(t, r) for t, r, _ in candidates],
        )
    return UnknownAlias(verb=verb, term=term)


def _required_op_for(verb: AliasVerb, resource: Resource) -> Operation | None:
    """Return the `Operation` the verb requires on `resource`, or None."""
    if verb is AliasVerb.LS:
        return resource.list_op
    if verb is AliasVerb.GET:
        return resource.get_op
    if verb is AliasVerb.RM:
        return resource.delete_op
    return None  # SEARCH does not flow through this branch


def _resolve_search(term: str, model: CommandModel) -> ResolvedAlias | UnknownAlias:
    for tag_name, resource_name, op in model.iter_operations():
        if op.path == "/api/search/" and op.http_method is HttpMethod.GET:
            return ResolvedAlias(
                tag=tag_name,
                resource_name=resource_name,
                operation=op,
            )
    return UnknownAlias(
        verb=AliasVerb.SEARCH,
        term=term,
        reason="search_endpoint_unavailable",
    )
