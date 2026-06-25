"""Pydantic models for ~/.nsc/config.yaml.

These models describe the on-disk shape. The runtime view (`ResolvedProfile`)
lives in `nsc/cli/runtime.py` and is built by overlaying flags + env vars on
top of a selected `Profile`.
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


class ColorMode(StrEnum):
    AUTO = "auto"
    ON = "on"
    OFF = "off"


class AuditRedaction(StrEnum):
    # SAFE redacts only known secrets (passwords/tokens) in bodies; FULL omits
    # every body, leaving routing metadata only — stricter compliance, harder
    # debugging. SAFE is the default for backward compatibility.
    SAFE = "safe"
    FULL = "full"


class Defaults(_Frozen):
    output: OutputFormat = OutputFormat.TABLE
    page_size: int = 50
    timeout: float = 30.0
    schema_refresh: SchemaRefresh = SchemaRefresh.DAILY
    color_mode: ColorMode = ColorMode.AUTO
    audit_redaction: AuditRedaction = AuditRedaction.SAFE


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
