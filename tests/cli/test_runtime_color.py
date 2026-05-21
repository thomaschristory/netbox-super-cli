from __future__ import annotations

import pytest
from pydantic import HttpUrl

from nsc.cli.runtime import ResolvedProfile, RuntimeContext, resolve_color
from nsc.config.models import ColorMode, Config, OutputFormat
from nsc.http.client import NetBoxClient
from nsc.model.command_model import CommandModel


class _Profile:
    url = "https://nb.example"
    token = "t0ken"
    verify_ssl = True
    timeout = 5.0


def _base_ctx() -> RuntimeContext:
    profile = ResolvedProfile(
        name="test",
        url=HttpUrl("https://nb.example"),
        token="t0ken",
        verify_ssl=True,
        timeout=5.0,
        schema_url=None,
    )
    return RuntimeContext(
        resolved_profile=profile,
        config=Config(),
        command_model=CommandModel(info_title="t", info_version="v", schema_hash="x"),
        client=NetBoxClient(_Profile()),
        output_format=OutputFormat.TABLE,
        color=False,
    )


@pytest.mark.parametrize(
    "mode, is_tty, expected",
    [
        (ColorMode.ON, True, True),
        (ColorMode.ON, False, True),
        (ColorMode.OFF, True, False),
        (ColorMode.OFF, False, False),
        (ColorMode.AUTO, True, True),
        (ColorMode.AUTO, False, False),
    ],
)
def test_resolve_color(mode: ColorMode, is_tty: bool, expected: bool) -> None:
    assert resolve_color(mode, is_tty=is_tty) == expected


def test_runtime_context_accepts_color_field() -> None:
    ctx = _base_ctx()
    assert ctx.color is False
