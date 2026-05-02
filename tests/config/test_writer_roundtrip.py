"""End-to-end round-trip behavior: load mutate dump preserves comments."""

from __future__ import annotations

from pathlib import Path

from nsc.config.writer import dump_round_trip, load_round_trip, set_path


def test_round_trip_preserves_comments_and_env_tag(tmp_path: Path) -> None:
    body = (
        "# top comment\n"
        "default_profile: prod  # used unless --profile is passed\n"
        "profiles:\n"
        "  prod:\n"
        "    # secondary comment\n"
        "    url: https://nb.example/\n"
        "    token: !env NSC_PROD_TOKEN\n"
    )
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")

    doc = load_round_trip(path)
    set_path(doc, "defaults.page_size", 100)
    out = dump_round_trip(doc)

    assert "# top comment" in out
    assert "# used unless --profile is passed" in out
    assert "# secondary comment" in out
    assert "!env NSC_PROD_TOKEN" in out
    assert "page_size: 100" in out
