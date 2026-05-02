"""Persist generated CommandModels under `~/.nsc/cache/<profile>/<hash>.json`."""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from nsc.model.command_model import CommandModel

_LOG = logging.getLogger(__name__)
_PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class CacheStore:
    root: Path

    def load(self, profile: str, schema_hash: str) -> CommandModel | None:
        self._validate_profile(profile)
        if not _HASH_RE.match(schema_hash):
            return None
        target = self._path_for(profile, schema_hash)
        if not target.exists():
            return None
        try:
            text = target.read_text()
            model = CommandModel.model_validate_json(text)
        except Exception as exc:  # broad: corrupt JSON, schema mismatch, etc.
            _LOG.warning("cache: ignoring corrupt entry %s (%s)", target, exc)
            return None
        if model.schema_hash != schema_hash:
            _LOG.warning("cache: hash mismatch for %s (file says %s)", target, model.schema_hash)
            return None
        return model

    def save(self, profile: str, model: CommandModel) -> Path:
        self._validate_profile(profile)
        target = self._path_for(profile, model.schema_hash)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(model.model_dump_json(indent=2))
        return target

    def clear(self, *, profile: str | None = None) -> None:
        if profile is None:
            if self.root.exists():
                shutil.rmtree(self.root)
            return
        self._validate_profile(profile)
        target = self.root / profile
        if target.exists():
            shutil.rmtree(target)

    def move(self, old: str, new: str) -> None:
        """Rename a profile's cache directory from `old` to `new`.

        No-op when `old` does not exist (the profile was never warmed). Raises
        `FileExistsError` when `new` already exists — the caller must purge
        the target first if that's the intent. Both names are validated to
        prevent path-component injection (matches `_PROFILE_RE`).
        """
        self._validate_profile(old)
        self._validate_profile(new)
        src = self.root / old
        dst = self.root / new
        if not src.exists():
            return
        if dst.exists():
            raise FileExistsError(f"cache directory for profile {new!r} already exists at {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)

    def purge(self, profile: str) -> None:
        """Remove a profile's cache directory entirely. No-op if missing."""
        self._validate_profile(profile)
        target = self.root / profile
        if target.exists():
            shutil.rmtree(target)

    def _path_for(self, profile: str, schema_hash: str) -> Path:
        return self.root / profile / f"{schema_hash}.json"

    @staticmethod
    def _validate_profile(profile: str) -> None:
        if not _PROFILE_RE.match(profile):
            raise ValueError(f"invalid profile name {profile!r}: must match {_PROFILE_RE.pattern}")
