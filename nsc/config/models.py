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


class ObjectColorMode(StrEnum):
    # Render NetBox-native hex colors (role/tag/…) independently of status
    # coloring. Still gated by the global color resolution, so OFF never yields
    # ANSI but ON/AUTO only color when color is otherwise enabled.
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
    page_size: int = Field(default=50, ge=1)
    timeout: float = 30.0
    schema_refresh: SchemaRefresh = SchemaRefresh.DAILY
    color_mode: ColorMode = ColorMode.AUTO
    object_colors: ObjectColorMode = ObjectColorMode.AUTO
    audit_redaction: AuditRedaction = AuditRedaction.SAFE


class KeyringRef:
    """A `!keyring NAME` token reference, resolved against the OS keyring on use.

    Kept unresolved at load time so that commands which never send a request
    (completion, `nsc config`, `nsc profiles`) never touch the keyring.

    Deliberately a plain class rather than a dataclass/model: Pydantic then
    validates it by `isinstance` only, so a YAML mapping under `token:` can
    never coerce into one — only the loader's `!keyring` constructor can.
    """

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other: object) -> bool:
        return isinstance(other, KeyringRef) and other.name == self.name

    def __hash__(self) -> int:
        return hash((KeyringRef, self.name))

    def __repr__(self) -> str:
        return f"KeyringRef(name={self.name!r})"


class Profile(_Frozen):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    name: str
    url: HttpUrl
    token: str | KeyringRef | None = None
    verify_ssl: bool = True
    schema_url: HttpUrl | None = None
    timeout: float | None = None
    branch: str | None = None


class Config(_Frozen):
    default_profile: str | None = None
    profiles: dict[str, Profile] = Field(default_factory=dict)
    defaults: Defaults = Field(default_factory=Defaults)
    columns: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    # Local, named filter sets keyed `<tag>.<resource>.<name> = {filter_key: value}`.
    # The leaf dict is exactly a `FilterState.as_params()` payload so a saved search
    # round-trips through the TUI filter screen and the CLI `--saved` flag alike.
    saved_searches: dict[str, dict[str, dict[str, dict[str, str]]]] = Field(default_factory=dict)
