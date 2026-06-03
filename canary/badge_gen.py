"""Shields.io-style static SVG badge generation."""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from canary.score import score_color

_TEMPLATES = Path(__file__).parent / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(enabled_extensions=("j2",)),
    )


def badge_label(score: int) -> str:
    return f"{score}%"


def badge_fill_color(score: int) -> str:
    color = score_color(score)
    return {
        "green": "#4c1",
        "yellow": "#dfb317",
        "red": "#e05d44",
    }[color]


def render_badge(score: int, label: str = "canary") -> str:
    template = _env().get_template("badge.svg.j2")
    return str(
        template.render(
            label=label,
            message=badge_label(score),
            color=badge_fill_color(score),
        )
    )


def generate_badge(history: list[dict[str, Any]], path: Path) -> None:
    """Write badge SVG from latest history entry (0% if empty)."""
    score = int(history[-1]["score"]) if history else 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_badge(score), encoding="utf-8")
