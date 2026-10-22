"""`nsc login --store keyring` and `!keyring` resolution at request time."""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import pytest
import respx
from typer.testing import CliRunner

from nsc.auth.keyring_store import SERVICE_NAME
from nsc.cli.app import app
from nsc.output.errors import EXIT_CODES, ErrorType

_CONFIG_EXIT = EXIT_CODES[ErrorType.CONFIG]
_AUTH_EXIT = EXIT_CODES[ErrorType.AUTH]
_USAGE_EXIT = 2

_KEYRING_PROFILE = (
    "default_profile: prod\n"
    "profiles:\n"
    "  prod:\n"
    "    url: https://nb.example/\n"
    "    token: !keyring my-token\n"
)


def _plain(output: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", output)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".nsc"
    home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NSC_HOME", str(home))
    for var in ("NSC_URL", "NSC_TOKEN", "NSC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    return home


def _seed(home: Path, body: str) -> None:
    (home / "config.yaml").write_text(body, encoding="utf-8")


def _config_text(home: Path) -> str:
    return (home / "config.yaml").read_text(encoding="utf-8")


def _good_status(httpx2_mock: respx.Router) -> respx.Route:
    httpx2_mock.get("https://nb.example/api/status/").respond(200, json={"netbox-version": "4.5.9"})
    return httpx2_mock.get("https://nb.example/api/users/tokens/").respond(
        200, json={"results": [{"user": {"username": "alice"}}]}
    )


def _mock_schema(httpx2_mock: respx.Router) -> None:
    bundled = next(Path("nsc/schemas/bundled").glob("*.json*"))
    body = bundled.read_bytes()
    if bundled.name.endswith(".gz"):
        body = gzip.decompress(body)
    httpx2_mock.get("https://nb.example/api/schema/?format=json").respond(
        200, content=body, headers={"content-type": "application/json"}
    )


def _login_new(*extra: str) -> list[str]:
    return [
        "login",
        "--new",
        "--profile",
        "prod",
        "--url",
        "https://nb.example/",
        "--store",
        "keyring",
        *extra,
    ]


def test_login_new_keyring_round_trips_into_a_request(
    home: Path,
    httpx2_mock: respx.Router,
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    _good_status(httpx2_mock)
    runner = CliRunner()
    result = runner.invoke(app, _login_new("--keyring-name", "my-token"), input="SECRET-T123\nn\n")
    assert result.exit_code == 0, result.output

    body = _config_text(home)
    assert "token: !keyring my-token" in body
    assert "SECRET-T123" not in body
    assert fake_keyring == {(SERVICE_NAME, "my-token"): "SECRET-T123"}

    _mock_schema(httpx2_mock)
    devices = httpx2_mock.get("https://nb.example/api/dcim/devices/").respond(
        200, json={"count": 0, "next": None, "previous": None, "results": []}
    )
    listed = runner.invoke(app, ["dcim", "devices", "list", "--output", "json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.stdout) == []
    assert devices.calls.last.request.headers["Authorization"] == "Token SECRET-T123"
    assert "SECRET-T123" not in _config_text(home)


def test_login_new_keyring_defaults_name_to_profile(
    home: Path,
    httpx2_mock: respx.Router,
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    _good_status(httpx2_mock)
    result = CliRunner().invoke(app, _login_new(), input="T123\nn\n")
    assert result.exit_code == 0, result.output
    assert "token: !keyring prod" in _config_text(home)
    assert fake_keyring == {(SERVICE_NAME, "prod"): "T123"}


@pytest.mark.usefixtures("no_keyring")
def test_login_new_keyring_without_backend_emits_envelope_and_writes_nothing(
    home: Path, httpx2_mock: respx.Router
) -> None:
    _good_status(httpx2_mock)
    result = CliRunner().invoke(app, _login_new(), input="T123\nn\n")
    assert result.exit_code == _CONFIG_EXIT, result.output
    assert "Traceback" not in result.output
    assert "keyring" in result.output.lower()
    assert not (home / "config.yaml").exists()


def test_login_rotate_keyring_reuses_existing_reference_name(
    home: Path,
    httpx2_mock: respx.Router,
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    fake_keyring[(SERVICE_NAME, "shared-name")] = "OLD"
    _seed(
        home,
        "default_profile: prod\n"
        "profiles:\n"
        "  prod:\n"
        "    url: https://nb.example/\n"
        "    token: !keyring shared-name  # stays put\n",
    )
    _good_status(httpx2_mock)
    result = CliRunner().invoke(
        app, ["login", "--rotate", "--profile", "prod", "--store", "keyring"], input="NEW\n"
    )
    assert result.exit_code == 0, result.output
    assert fake_keyring == {(SERVICE_NAME, "shared-name"): "NEW"}
    body = _config_text(home)
    assert "token: !keyring shared-name" in body
    assert "# stays put" in body
    assert "NEW" not in body


def test_login_rotate_plaintext_to_keyring_drops_plaintext(
    home: Path,
    httpx2_mock: respx.Router,
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    _seed(
        home,
        "default_profile: prod\nprofiles:\n  prod:\n    url: https://nb.example/\n    token: OLD\n",
    )
    _good_status(httpx2_mock)
    result = CliRunner().invoke(
        app, ["login", "--rotate", "--profile", "prod", "--store", "keyring"], input="NEW\n"
    )
    assert result.exit_code == 0, result.output
    assert fake_keyring == {(SERVICE_NAME, "prod"): "NEW"}
    body = _config_text(home)
    assert "token: !keyring prod" in body
    assert "OLD" not in body
    assert "NEW" not in body


def test_login_bare_verifies_keyring_profile(
    home: Path,
    httpx2_mock: respx.Router,
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    fake_keyring[(SERVICE_NAME, "my-token")] = "T123"
    _seed(
        home,
        "default_profile: prod\n"
        "profiles:\n"
        "  prod:\n"
        "    url: https://nb.example/\n"
        "    token: !keyring my-token\n",
    )
    users = _good_status(httpx2_mock)
    result = CliRunner().invoke(app, ["login"])
    assert result.exit_code == 0, result.output
    assert users.calls.last.request.headers["Authorization"] == "Token T123"


@pytest.mark.usefixtures("fake_keyring")
def test_login_bare_with_missing_keyring_entry_emits_config_envelope(home: Path) -> None:
    _seed(
        home,
        "default_profile: prod\n"
        "profiles:\n"
        "  prod:\n"
        "    url: https://nb.example/\n"
        "    token: !keyring absent\n",
    )
    result = CliRunner().invoke(app, ["login"])
    assert result.exit_code == _CONFIG_EXIT, result.output
    assert "Traceback" not in result.output
    assert "absent" in result.output


@pytest.mark.usefixtures("fake_keyring")
def test_request_with_missing_keyring_entry_emits_config_envelope(home: Path) -> None:
    _seed(
        home,
        "default_profile: prod\n"
        "profiles:\n"
        "  prod:\n"
        "    url: https://nb.example/\n"
        "    token: !keyring absent\n",
    )
    result = CliRunner().invoke(app, ["dcim", "devices", "list", "--output", "json"])
    assert result.exit_code == _CONFIG_EXIT, result.output
    assert "Traceback" not in result.output
    envelope = json.loads(result.output.strip().splitlines()[-1])
    assert envelope["type"] == "config"
    assert "absent" in envelope["error"]


@pytest.mark.usefixtures("no_keyring")
def test_request_without_keyring_backend_emits_config_envelope(home: Path) -> None:
    _seed(
        home,
        "default_profile: prod\n"
        "profiles:\n"
        "  prod:\n"
        "    url: https://nb.example/\n"
        "    token: !keyring my-token\n",
    )
    result = CliRunner().invoke(app, ["dcim", "devices", "list"])
    assert result.exit_code == _CONFIG_EXIT, result.output
    assert "no usable OS keyring backend" in result.output


def test_login_rotate_without_store_keeps_existing_keyring_reference(
    home: Path,
    httpx2_mock: respx.Router,
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    fake_keyring[(SERVICE_NAME, "my-token")] = "OLD"
    _seed(
        home,
        "default_profile: prod\n"
        "profiles:\n"
        "  prod:\n"
        "    url: https://nb.example/\n"
        "    token: !keyring my-token\n",
    )
    _good_status(httpx2_mock)
    result = CliRunner().invoke(app, ["login", "--rotate", "--profile", "prod"], input="NEW\n")
    assert result.exit_code == 0, result.output
    assert fake_keyring == {(SERVICE_NAME, "my-token"): "NEW"}
    body = _config_text(home)
    assert "token: !keyring my-token" in body
    assert "NEW" not in body


def test_login_new_rejects_unknown_store_before_prompting(home: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["login", "--new", "--profile", "prod", "--url", "https://nb.example/", "--store", "kr"],
        input="T123\nn\n",
    )
    assert result.exit_code == 2
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "--store must be one of" in plain
    assert "Token" not in plain
    assert not (home / "config.yaml").exists()


@pytest.mark.usefixtures("no_keyring")
def test_token_flag_overrides_keyring_without_touching_it(
    home: Path, httpx2_mock: respx.Router
) -> None:
    _seed(
        home,
        "default_profile: prod\n"
        "profiles:\n"
        "  prod:\n"
        "    url: https://nb.example/\n"
        "    token: !keyring my-token\n",
    )
    _mock_schema(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/dcim/devices/").respond(
        200, json={"count": 0, "next": None, "previous": None, "results": []}
    )
    result = CliRunner().invoke(
        app, ["--token", "OVERRIDE", "dcim", "devices", "list", "--output", "json"]
    )
    assert result.exit_code == 0, result.output


def _rejected_token(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get("https://nb.example/api/status/").respond(200, json={"netbox-version": "4.5.9"})
    httpx2_mock.get("https://nb.example/api/users/tokens/").respond(403, json={})


def test_login_new_keyring_with_rejected_token_leaves_keyring_untouched(
    home: Path,
    httpx2_mock: respx.Router,
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    _rejected_token(httpx2_mock)
    result = CliRunner().invoke(app, _login_new(), input="BAD\nn\n")
    assert result.exit_code == _AUTH_EXIT, result.output
    assert fake_keyring == {}
    assert not (home / "config.yaml").exists()


def test_login_rotate_keyring_with_rejected_token_keeps_old_secret(
    home: Path,
    httpx2_mock: respx.Router,
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    fake_keyring[(SERVICE_NAME, "my-token")] = "OLD"
    _seed(home, _KEYRING_PROFILE)
    _rejected_token(httpx2_mock)
    result = CliRunner().invoke(app, ["login", "--rotate", "--profile", "prod"], input="BAD\n")
    assert result.exit_code == _AUTH_EXIT, result.output
    assert fake_keyring == {(SERVICE_NAME, "my-token"): "OLD"}
    assert _config_text(home) == _KEYRING_PROFILE


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--store", "kr"], "--store must be one of"),
        (["--store", "env"], "--store=env requires --env-var"),
        (["--store", "keyring", "--keyring-name", "   "], "--keyring-name"),
    ],
)
def test_login_rotate_rejects_bad_options_before_prompting(
    home: Path,
    fake_keyring: dict[tuple[str, str], str],
    args: list[str],
    message: str,
) -> None:
    fake_keyring[(SERVICE_NAME, "my-token")] = "OLD"
    _seed(home, _KEYRING_PROFILE)
    result = CliRunner().invoke(
        app, ["login", "--rotate", "--profile", "prod", *args], input="NEW\n"
    )
    assert result.exit_code == _USAGE_EXIT, result.output
    plain = _plain(result.output)
    assert message in plain
    assert "New token" not in plain
    assert fake_keyring == {(SERVICE_NAME, "my-token"): "OLD"}
    assert _config_text(home) == _KEYRING_PROFILE


@pytest.mark.parametrize("name", ["", " ", "   "])
def test_login_new_rejects_blank_keyring_name_before_prompting(
    home: Path,
    fake_keyring: dict[tuple[str, str], str],
    name: str,
) -> None:
    result = CliRunner().invoke(app, _login_new("--keyring-name", name), input="T123\nn\n")
    assert result.exit_code == _USAGE_EXIT, result.output
    plain = _plain(result.output)
    assert "--keyring-name" in plain
    assert "Token" not in plain
    assert fake_keyring == {}
    assert not (home / "config.yaml").exists()


@pytest.mark.parametrize("name", ["prod ", " prod", "  prod  "])
def test_login_new_strips_padded_keyring_name_so_loader_finds_it(
    home: Path,
    httpx2_mock: respx.Router,
    fake_keyring: dict[tuple[str, str], str],
    name: str,
) -> None:
    users = _good_status(httpx2_mock)
    runner = CliRunner()
    result = runner.invoke(app, _login_new("--keyring-name", name), input="T123\nn\n")
    assert result.exit_code == 0, result.output
    assert fake_keyring == {(SERVICE_NAME, "prod"): "T123"}
    assert "token: !keyring prod\n" in _config_text(home)

    verified = runner.invoke(app, ["login"])
    assert verified.exit_code == 0, verified.output
    assert users.calls.last.request.headers["Authorization"] == "Token T123"


def test_login_rotate_strips_padded_keyring_name(
    home: Path,
    httpx2_mock: respx.Router,
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    fake_keyring[(SERVICE_NAME, "my-token")] = "OLD"
    _seed(home, _KEYRING_PROFILE)
    _good_status(httpx2_mock)
    result = CliRunner().invoke(
        app,
        ["login", "--rotate", "--profile", "prod", "--keyring-name", " fresh "],
        input="NEW\n",
    )
    assert result.exit_code == 0, result.output
    assert fake_keyring[(SERVICE_NAME, "fresh")] == "NEW"
    assert (SERVICE_NAME, " fresh ") not in fake_keyring
    assert "token: !keyring fresh\n" in _config_text(home)


_LEGACY_HOLDS_PROD = (
    "default_profile: legacy\n"
    "profiles:\n"
    "  legacy:\n"
    "    url: https://old.example/\n"
    "    token: !keyring prod\n"
)


def test_login_new_refuses_keyring_entry_held_by_renamed_profile(
    home: Path,
    httpx2_mock: respx.Router,
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    _good_status(httpx2_mock)
    runner = CliRunner()
    first = runner.invoke(app, _login_new(), input="TOKEN-A\nn\n")
    assert first.exit_code == 0, first.output
    renamed = runner.invoke(app, ["profiles", "rename", "prod", "legacy"])
    assert renamed.exit_code == 0, renamed.output
    before = _config_text(home)

    second = runner.invoke(app, _login_new(), input="TOKEN-B\nn\n")
    assert second.exit_code == _CONFIG_EXIT, second.output
    plain = _plain(second.output)
    assert "legacy" in plain
    assert "--keyring-name" in plain
    assert fake_keyring == {(SERVICE_NAME, "prod"): "TOKEN-A"}
    assert _config_text(home) == before


def test_login_new_refuses_explicit_keyring_name_held_by_other_profile(
    home: Path,
    httpx2_mock: respx.Router,
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    fake_keyring[(SERVICE_NAME, "prod")] = "TOKEN-A"
    _seed(home, _LEGACY_HOLDS_PROD)
    _good_status(httpx2_mock)
    result = CliRunner().invoke(
        app,
        [
            "login",
            "--new",
            "--profile",
            "other",
            "--url",
            "https://nb.example/",
            "--store",
            "keyring",
            "--keyring-name",
            "prod",
        ],
        input="TOKEN-B\nn\n",
    )
    assert result.exit_code == _CONFIG_EXIT, result.output
    assert "legacy" in _plain(result.output)
    assert fake_keyring == {(SERVICE_NAME, "prod"): "TOKEN-A"}
    assert _config_text(home) == _LEGACY_HOLDS_PROD


def test_login_rotate_plaintext_refuses_keyring_entry_held_by_other_profile(
    home: Path,
    httpx2_mock: respx.Router,
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    fake_keyring[(SERVICE_NAME, "prod")] = "TOKEN-A"
    body = _LEGACY_HOLDS_PROD + "  prod:\n    url: https://nb.example/\n    token: OLD\n"
    _seed(home, body)
    _good_status(httpx2_mock)
    result = CliRunner().invoke(
        app, ["login", "--rotate", "--profile", "prod", "--store", "keyring"], input="NEW\n"
    )
    assert result.exit_code == _CONFIG_EXIT, result.output
    assert "legacy" in _plain(result.output)
    assert fake_keyring == {(SERVICE_NAME, "prod"): "TOKEN-A"}
    assert _config_text(home) == body


def test_login_rotate_keyring_profile_with_missing_entry_recovers(
    home: Path,
    httpx2_mock: respx.Router,
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    _seed(home, _KEYRING_PROFILE)
    _good_status(httpx2_mock)
    result = CliRunner().invoke(
        app, ["login", "--rotate", "--profile", "prod", "--store", "keyring"], input="NEW\n"
    )
    assert result.exit_code == 0, result.output
    assert fake_keyring == {(SERVICE_NAME, "my-token"): "NEW"}
    assert _config_text(home) == _KEYRING_PROFILE


@pytest.mark.usefixtures("fake_keyring")
@pytest.mark.parametrize("command", ["ls", "get", "rm", "search"])
def test_static_command_help_works_with_missing_keyring_entry(home: Path, command: str) -> None:
    _seed(home, _KEYRING_PROFILE)
    result = CliRunner().invoke(app, [command, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage" in _plain(result.output)


@pytest.mark.usefixtures("fake_keyring")
def test_static_command_without_help_still_reports_missing_keyring_entry(home: Path) -> None:
    _seed(home, _KEYRING_PROFILE)
    result = CliRunner().invoke(app, ["ls", "dcim.devices"])
    assert result.exit_code == _CONFIG_EXIT, result.output
    assert "my-token" in result.output
