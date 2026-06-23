"""Flat, listable resource catalog backing the resource picker."""

from __future__ import annotations

from dataclasses import dataclass

from nsc.model.command_model import CommandModel, Operation


@dataclass(frozen=True)
class ResourceRef:
    tag: str
    resource_name: str
    list_op: Operation

    @property
    def label(self) -> str:
        return f"{self.tag} / {self.resource_name}"


def list_resources(model: CommandModel) -> list[ResourceRef]:
    refs: list[ResourceRef] = []
    for tag_name, tag in sorted(model.tags.items()):
        for resource_name, resource in sorted(tag.resources.items()):
            if resource.list_op is not None:
                refs.append(ResourceRef(tag_name, resource_name, resource.list_op))
    return sorted(refs, key=lambda r: r.resource_name)


def filter_resources(refs: list[ResourceRef], query: str) -> list[ResourceRef]:
    needle = query.strip().lower()
    if not needle:
        return list(refs)
    return [r for r in refs if needle in r.resource_name.lower() or needle in r.tag.lower()]
