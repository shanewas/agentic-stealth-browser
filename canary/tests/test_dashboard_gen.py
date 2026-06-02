"""Tests for dashboard HTML generation."""

from pathlib import Path
from typing import Any

from canary.dashboard_gen import build_dashboard_context, generate_dashboard, render_dashboard


def _sample_history() -> list[dict[str, Any]]:
    return [
        {
            "ts": "2026-06-03T00:30:00Z",
            "version": "2.4.0",
            "score": 92,
            "per_site": {
                "sannysoft": "pass",
                "browserleaks": "pass",
                "pixelscan": "pass",
                "nowsecure": "soft-detect",
                "fingerprint_demo": "pass",
                "creepjs": "detected",
            },
            "duration_s": 287,
            "error": None,
        }
    ]


def test_render_contains_required_sections() -> None:
    html = render_dashboard(_sample_history())
    assert "<html" in html.lower()
    assert "Detection Score" in html
    assert "92" in html
    assert "sparkline" in html.lower() or "canvas" in html.lower()
    assert "Privacy" in html
    assert "What does this measure" in html


def test_generate_writes_file(tmp_path: Path) -> None:
    out = tmp_path / "index.html"
    generate_dashboard(_sample_history(), out)
    text = out.read_text(encoding="utf-8")
    assert len(text) < 50_000
    assert "browserleaks" in text.lower() or "BrowserLeaks" in text


def test_empty_history_context() -> None:
    ctx = build_dashboard_context([])
    assert ctx["current_score"] == 0