from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

BRANCHING_PATH = "/api/plugins/branching"
BRANCHES_PATH = f"{BRANCHING_PATH}/branches/"
CHANGES_PATH = f"{BRANCHING_PATH}/changes/"
JOBS_PATH = "/api/core/jobs/"
READY = "ready"


def choice_value(raw: Any) -> Any:
    # NetBox serializes choice fields as {"value": ..., "label": ...}.
    if isinstance(raw, dict):
        return raw.get("value")
    return raw


class Branch(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: int
    name: str
    schema_id: str
    status: str
    description: str = ""
    last_sync: str | None = None
    owner: str | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _flatten_status(cls, raw: Any) -> Any:
        return choice_value(raw)

    @field_validator("owner", mode="before")
    @classmethod
    def _flatten_owner(cls, raw: Any) -> Any:
        if isinstance(raw, dict):
            return raw.get("username")
        return raw
