"""Canary score calculation."""

from typing import Mapping

SITE_COUNT = 6
PASS_WEIGHT = 1.0
SOFT_DETECT_WEIGHT = 0.5


def score_results(per_site: Mapping[str, str]) -> int | None:
    """Compute 0–100 score from per-site status strings.

    Scores over the sites actually present in ``per_site``. An empty
    ``per_site`` is no measurement (``None``), not a 0 score.
    """
    if not per_site:
        return None
    pass_count = sum(1 for v in per_site.values() if v == "pass")
    soft_count = sum(1 for v in per_site.values() if v == "soft-detect")
    raw = (
        (pass_count * PASS_WEIGHT + soft_count * SOFT_DETECT_WEIGHT)
        / len(per_site)
        * 100
    )
    return max(0, min(100, round(raw)))


def score_color(score: int) -> str:
    """Return CSS color name for dashboard/badge styling."""
    if score >= 90:
        return "green"
    if score >= 75:
        return "yellow"
    return "red"
