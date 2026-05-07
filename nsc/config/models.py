"""Pydantic models for ~/.nsc/config.yaml.

Phase 2 is read-only; these models describe the on-disk shape. The runtime view
(`ResolvedProfile`) lives in `nsc/cli/runtime.py` and is built by overlaying
flags + env vars on top of a selected `Profile`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OutputFormat(StrEnum):
    TABLE = "table"
    JSON = "json"
    JSONL = "jsonl"
    YAML = "yaml"
    CSV = "csv"


class SchemaRefresh(StrEnum):
    MANUAL = "manual"
    ON_HASH_CHANGE = "on-hash-change"
    DAILY = "daily"
    WEEKLY = "weekly"


class Defaults(_Frozen):
    output: OutputFormat = OutputFormat.TABLE
    page_size: int = 50
    timeout: float = 30.0
    schema_refresh: SchemaRefresh = SchemaRefresh.DAILY


class Profile(_Frozen):
    name: str
    url: HttpUrl
    token: str | None = None
    verify_ssl: bool = True
    schema_url: HttpUrl | None = None
    timeout: float | None = None


class Config(_Frozen):
    default_profile: str | None = None
    profiles: dict[str, Profile] = Field(default_factory=dict)
    defaults: Defaults = Field(default_factory=Defaults)
    columns: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
