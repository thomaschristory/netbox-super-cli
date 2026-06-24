"""Derive related-resource navigation from the schema, not hard-coded knowledge.

A resource ``R`` (e.g. ``devices``) is related to any resource whose list
operation accepts a query parameter named ``{singular(R)}`` or
``{singular(R)}_id`` (e.g. ``interfaces`` accepts ``device_id``). The naming
convention is hard-coded; the specific relationships come from the live schema.
"""

from __future__ import annotations

from dataclasses import dataclass

from nsc.model.command_model import CommandModel, Operation, ParameterLocation


@dataclass(frozen=True)
class RelatedView:
    tag: str
    resource_name: str
    list_op: Operation
    filter_param: str


def singularize(name: str) -> str:
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith(("sses", "ses", "xes", "zes", "ches", "shes")):
        return name[:-2]
    if name.endswith("s"):
        return name[:-1]
    return name


def related_views(model: CommandModel, resource_name: str) -> list[RelatedView]:
    singular = singularize(resource_name)
    id_param = f"{singular}_id"
    found: list[RelatedView] = []
    for tag_name, tag in sorted(model.tags.items()):
        for other_name, resource in sorted(tag.resources.items()):
            if other_name == resource_name or resource.list_op is None:
                continue
            names = {
                param.name
                for param in resource.list_op.parameters
                if param.location == ParameterLocation.QUERY
            }
            # Drill passes a numeric PK, so prefer the id-keyed filter (`{singular}_id`)
            # over the name-keyed one (`{singular}`). NetBox declares the name filter
            # first, so a naive first-match would pass a PK to a name filter and get
            # an empty list.
            if id_param in names:
                filter_param = id_param
            elif singular in names:
                filter_param = singular
            else:
                continue
            found.append(
                RelatedView(
                    tag=tag_name,
                    resource_name=other_name,
                    list_op=resource.list_op,
                    filter_param=filter_param,
                )
            )
    return found
