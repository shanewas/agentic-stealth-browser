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


def test_partial_per_site_scoring() -> None:
    assert score_results({"a": "pass", "b": "pass"}) == 100
    assert score_results({"a": "pass", "b": "detected"}) == 50
    # (1 * 1.0 + 1 * 0.5) / 3 * 100 = 50
    assert score_results({"a": "pass", "b": "soft-detect", "c": "detected"}) == 50


def test_oversized_input_clamped_to_100() -> None:
    per_site = {k: "pass" for k in ("a", "b", "c", "d", "e", "f", "g")}
    assert score_results(per_site) == 100


def test_empty_per_site_is_no_measurement() -> None:
    assert score_results({}) is None


def test_score_color_thresholds() -> None:
    assert score_color(100) == "green"
    assert score_color(90) == "green"
    assert score_color(89) == "yellow"
    assert score_color(75) == "yellow"
    assert score_color(74) == "red"
