"""Read-only YAML loader for ~/.nsc/config.yaml.

Phase 2 uses `pyyaml`. Phase 4 swaps to `ruamel.yaml` when the first writer
(`nsc config set/edit`) lands.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from nsc.config.models import Config


class ConfigParseError(Exception):
    """Raised when ~/.nsc/config.yaml cannot be parsed or is structurally invalid."""


class _NSCLoader(yaml.SafeLoader):
    pass


def _construct_env(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> str | None:
    raw = loader.construct_scalar(node)
    parts = raw.strip().split(maxsplit=1)
    var = parts[0]
    parts_count = 2
    default = parts[1] if len(parts) == parts_count else None
    return os.environ.get(var, default)


_NSCLoader.add_constructor("!env", _construct_env)


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigParseError(f"could not read {path}: {exc}") from exc
    try:
        data: Any = yaml.load(text, Loader=_NSCLoader)
    except yaml.YAMLError as exc:
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
        return Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigParseError(f"{path}: {exc}") from exc
