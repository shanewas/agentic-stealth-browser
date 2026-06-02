"""Canary score calculation."""

from typing import Mapping

SITE_COUNT = 6
PASS_WEIGHT = 1.0
SOFT_DETECT_WEIGHT = 0.5


def score_results(per_site: Mapping[str, str]) -> int:
    """Compute 0–100 score from per-site status strings."""
    pass_count = sum(1 for v in per_site.values() if v == "pass")
    soft_count = sum(1 for v in per_site.values() if v == "soft-detect")
    raw = (pass_count * PASS_WEIGHT + soft_count * SOFT_DETECT_WEIGHT) / SITE_COUNT * 100
    return round(raw)


def score_color(score: int) -> str:
    """Return CSS color name for dashboard/badge styling."""
    if score >= 90:
        return "green"
    if score >= 75:
        return "yellow"
    return "red"