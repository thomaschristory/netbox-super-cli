"""`!keyring NAME` config tag: loader yields a reference, writer round-trips it."""

from __future__ import annotations

from pathlib import Path

import pytest

from nsc.config.loader import ConfigParseError, load_config
from nsc.config.models import KeyringRef
from nsc.config.writer import dump_round_trip, load_round_trip, set_path

_BODY = (
    "# keep me\n"
    "default_profile: prod\n"
    "profiles:\n"
    "  prod:\n"
    "    url: https://nb.example/\n"
    "    token: !keyring my-token\n"
    "  lab:\n"
    "    url: https://lab.example/\n"
    "    token: !env NSC_LAB_TOKEN\n"
)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.mark.usefixtures("no_keyring")
def test_loader_returns_reference_without_touching_keyring(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, _BODY))
    assert cfg.profiles["prod"].token == KeyringRef("my-token")


def test_loader_strips_whitespace_in_name(tmp_path: Path) -> None:
    body = "profiles:\n  prod:\n    url: https://nb.example/\n    token: !keyring '  spaced  '\n"
    cfg = load_config(_write(tmp_path, body))
    assert cfg.profiles["prod"].token == KeyringRef("spaced")


def test_loader_rejects_empty_keyring_name(tmp_path: Path) -> None:
    body = "profiles:\n  prod:\n    url: https://nb.example/\n    token: !keyring ''\n"
    with pytest.raises(ConfigParseError, match="!keyring"):
        load_config(_write(tmp_path, body))


def test_plain_mapping_token_is_not_coerced_into_keyring_ref(tmp_path: Path) -> None:
    body = "profiles:\n  prod:\n    url: https://nb.example/\n    token:\n      name: my-token\n"
    with pytest.raises(ConfigParseError):
        load_config(_write(tmp_path, body))


def test_writer_round_trips_keyring_and_env_tags(tmp_path: Path) -> None:
    doc = load_round_trip(_write(tmp_path, _BODY))
    set_path(doc, "defaults.page_size", 100)
    out = dump_round_trip(doc)
    assert "# keep me" in out
    assert "token: !keyring my-token" in out
    assert "token: !env NSC_LAB_TOKEN" in out
    assert "page_size: 100" in out


def test_keyring_ref_repr_never_carries_a_secret() -> None:
    assert repr(KeyringRef("my-token")) == "KeyringRef(name='my-token')"
