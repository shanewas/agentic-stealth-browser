"""Tests for badge SVG generation."""

from pathlib import Path

from canary.badge_gen import generate_badge, render_badge


def test_render_badge_valid_svg() -> None:
    svg = render_badge(92)
    assert svg.strip().startswith("<svg")
    assert "canary" in svg
    assert "92%" in svg
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg


def test_generate_badge_file(tmp_path: Path) -> None:
    history = [{"score": 75, "ts": "2026-06-03T00:00:00Z"}]
    path = tmp_path / "badge.svg"
    generate_badge(history, path)
    content = path.read_text(encoding="utf-8")
    assert "75%" in content


def test_empty_history_defaults_zero(tmp_path: Path) -> None:
    path = tmp_path / "badge.svg"
    generate_badge([], path)
    assert "0%" in path.read_text(encoding="utf-8")
