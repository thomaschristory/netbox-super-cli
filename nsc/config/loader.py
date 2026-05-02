"""Config loader for `~/.nsc/config.yaml`, backed by ruamel.yaml round-trip mode.

ruamel.yaml's `YAML(typ="rt")` preserves comments, key order, anchors, and
custom tags through subsequent writes (see `nsc/config/writer.py`). The parsed
document is a `CommentedMap` (dict-compatible); we hand it to
`Config.model_validate` for the structural validation gate.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from ruamel.yaml.nodes import ScalarNode

from nsc.config.models import Config


class ConfigParseError(Exception):
    """Raised when ~/.nsc/config.yaml cannot be parsed or is structurally invalid."""


def _construct_env(loader: Any, node: ScalarNode) -> str | None:
    raw = str(node.value)
    parts = raw.strip().split(maxsplit=1)
    var = parts[0]
    parts_count = 2
    default = parts[1] if len(parts) == parts_count else None
    return os.environ.get(var, default)


def _round_trip_yaml() -> YAML:
    """Build the singleton-shaped YAML parser used by both loader and writer."""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.constructor.add_constructor("!env", _construct_env)
    return yaml


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigParseError(f"could not read {path}: {exc}") from exc
    try:
        data: Any = _round_trip_yaml().load(io.StringIO(text))
    except YAMLError as exc:
        raise ConfigParseError(f"YAML parse error in {path}: {exc}") from exc
    if data is None:
        return Config()
    if not isinstance(data, dict):
        raise ConfigParseError(f"{path}: top-level value must be a mapping")
    profiles = data.get("profiles") or {}
    if isinstance(profiles, dict):
        for pname, pbody in profiles.items():
            if isinstance(pbody, dict):
                pbody.setdefault("name", pname)
    try:
        return Config.model_validate(dict(data))
    except ValidationError as exc:
        raise ConfigParseError(f"{path}: {exc}") from exc
