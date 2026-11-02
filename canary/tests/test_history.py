"""Tests for JSONL history I/O."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from canary.history import (
    append_history,
    average_score,
    consecutive_low_scores,
    entries_last_n_days,
    per_site_stats,
    read_history,
    sparkline_scores,
)


def _record(score: int, ts: str, **per_site: str) -> dict[str, Any]:
    base = {
        "sannysoft": "pass",
        "browserleaks": "pass",
        "pixelscan": "pass",
        "nowsecure": "pass",
        "fingerprint_demo": "pass",
        "creepjs": "pass",
    }
    base.update(per_site)
    return {
        "ts": ts,
        "version": "2.4.0",
        "score": score,
        "per_site": base,
        "duration_s": 100,
        "error": None,
    }


def test_append_and_read(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    r1 = _record(80, "2026-06-01T00:00:00Z")
    r2 = _record(90, "2026-06-02T00:00:00Z")
    append_history(path, r1)
    append_history(path, r2)
    history = read_history(path)
    assert len(history) == 2
    assert history[0]["score"] == 80
    assert history[1]["score"] == 90
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 2
    json.loads(lines[0])


def test_read_missing_file(tmp_path: Path) -> None:
    assert read_history(tmp_path / "missing.jsonl") == []


def test_read_history_skips_truncated_last_line(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    good = json.dumps(_record(80, "2026-06-01T00:00:00Z"))
    path.write_text(good + "\n" + '{"ts": "2026-06-02T00:0', encoding="utf-8")
    history = read_history(path)
    assert len(history) == 1
    assert history[0]["score"] == 80


def test_read_history_skips_non_numeric_score(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    good = json.dumps(_record(80, "2026-06-01T00:00:00Z"))
    bad = json.dumps({**_record(0, "2026-06-02T00:00:00Z"), "score": "high"})
    path.write_text(good + "\n" + bad + "\n" + good + "\n", encoding="utf-8")
    history = read_history(path)
    assert len(history) == 2
    assert all(e["score"] == 80 for e in history)


def test_read_history_all_malformed_reads_empty(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    bad_score = json.dumps({**_record(0, "2026-06-02T00:00:00Z"), "score": "high"})
    path.write_text(
        '{"ts": "2026-06-01T00:0' + "\n" + "not json\n" + bad_score + "\n",
        encoding="utf-8",
    )
    assert read_history(path) == []


def test_naive_ts_treated_as_utc_in_window() -> None:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    inside = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    outside = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    history = [_record(80, inside), _record(90, outside)]
    recent = entries_last_n_days(history, days=7)
    assert [e["score"] for e in recent] == [80]


def test_zero_window_arguments() -> None:
    history = [
        _record(100, "2026-06-03T10:00:00Z"),
        _record(50, "2026-06-03T11:00:00Z", sannysoft="detected"),
    ]
    assert average_score(history, days=0) is None
    assert sparkline_scores(history, limit=0) == []
    # None (the default) still means "no window" for average_score.
    assert average_score(history, days=None) == 75.0
    assert average_score(history) == 75.0


def test_sparkline_limit() -> None:
    history = [_record(i, f"2026-06-01T{i:02d}:00:00Z") for i in range(60)]
    scores = sparkline_scores(history, limit=50)
    assert len(scores) == 50
    assert scores[0] == 10


def test_consecutive_low_scores() -> None:
    history = [
        _record(90, "2026-06-01T00:00:00Z"),
        _record(70, "2026-06-02T00:00:00Z"),
        _record(60, "2026-06-03T00:00:00Z"),
        _record(50, "2026-06-04T00:00:00Z"),
    ]
    assert consecutive_low_scores(history, threshold=75, count=3) is True
    assert consecutive_low_scores(history[:2], threshold=75, count=3) is False


def test_average_and_per_site(tmp_path: Path) -> None:
    # Relative to now: fixed calendar dates fall out of the 7-day
    # window as time passes and the test time-bombs.
    now = datetime.now(timezone.utc)
    history = [
        _record(100, (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")),
        _record(
            50,
            (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            sannysoft="detected",
        ),
    ]
    assert average_score(history) == 75.0
    recent = entries_last_n_days(history, days=7)
    assert len(recent) == 2
    stats = per_site_stats(history, days=7)
    assert stats["sannysoft"]["last_status"] == "detected"
