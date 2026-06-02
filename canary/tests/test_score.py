"""Tests for score calculation."""

from canary.score import score_color, score_results


def test_perfect_score() -> None:
    per_site = {k: "pass" for k in ("a", "b", "c", "d", "e", "f")}
    assert score_results(per_site) == 100


def test_all_detected() -> None:
    per_site = {k: "detected" for k in ("a", "b", "c", "d", "e", "f")}
    assert score_results(per_site) == 0


def test_mixed_soft_detect() -> None:
    per_site = {
        "a": "pass",
        "b": "pass",
        "c": "pass",
        "d": "soft-detect",
        "e": "detected",
        "f": "fail",
    }
    # 3*1 + 1*0.5 = 3.5 / 6 * 100 = 58.33 -> 58
    assert score_results(per_site) == 58


def test_score_color_thresholds() -> None:
    assert score_color(100) == "green"
    assert score_color(90) == "green"
    assert score_color(89) == "yellow"
    assert score_color(75) == "yellow"
    assert score_color(74) == "red"