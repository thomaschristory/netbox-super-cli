from __future__ import annotations

from pathlib import Path

import pytest

from nsc.config.models import Config
from nsc.config.saved_searches import ConfigFileSavedSearchStore, InvalidSavedSearchName


def _store(tmp_path: Path, config: Config | None = None) -> ConfigFileSavedSearchStore:
    return ConfigFileSavedSearchStore(config or Config(), config_file=tmp_path / "config.yaml")


def test_save_persists_to_file_and_in_memory_config(tmp_path: Path) -> None:
    config = Config()
    store = ConfigFileSavedSearchStore(config, config_file=tmp_path / "config.yaml")
    store.save("dcim", "devices", "active", {"status": "active"})

    assert config.saved_searches == {"dcim": {"devices": {"active": {"status": "active"}}}}
    assert "status: active" in (tmp_path / "config.yaml").read_text()


def test_list_reads_back_what_was_saved(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save("dcim", "devices", "active", {"status": "active"})
    store.save("dcim", "devices", "leafs", {"role": "leaf"})
    assert store.list("dcim", "devices") == {
        "active": {"status": "active"},
        "leafs": {"role": "leaf"},
    }


def test_list_unknown_resource_is_empty(tmp_path: Path) -> None:
    assert _store(tmp_path).list("dcim", "devices") == {}


def test_delete_removes_from_file_and_memory(tmp_path: Path) -> None:
    config = Config()
    store = ConfigFileSavedSearchStore(config, config_file=tmp_path / "config.yaml")
    store.save("dcim", "devices", "active", {"status": "active"})
    store.delete("dcim", "devices", "active")
    assert store.list("dcim", "devices") == {}
    assert config.saved_searches.get("dcim", {}).get("devices", {}) == {}


def test_save_rejects_dotted_name(tmp_path: Path) -> None:
    with pytest.raises(InvalidSavedSearchName):
        _store(tmp_path).save("dcim", "devices", "a.b", {"x": "y"})


def test_list_reflects_a_preloaded_config(tmp_path: Path) -> None:
    config = Config(saved_searches={"ipam": {"prefixes": {"rfc1918": {"within": "10.0.0.0/8"}}}})
    store = ConfigFileSavedSearchStore(config, config_file=tmp_path / "config.yaml")
    assert store.list("ipam", "prefixes") == {"rfc1918": {"within": "10.0.0.0/8"}}
