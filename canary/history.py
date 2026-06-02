"""Append-only JSONL history for canary runs."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def append_history(path: Path, record: dict[str, Any]) -> None:
    """Append one canary run record (never rewrite prior lines)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_history(path: Path) -> list[dict[str, Any]]:
    """Read all history entries; returns [] if file missing or empty."""
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        entries.append(json.loads(line))
    return entries


def _parse_ts(ts: str) -> datetime:
    normalized = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def entries_last_n_days(
    history: list[dict[str, Any]], days: int = 7
) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result: list[dict[str, Any]] = []
    for entry in history:
        try:
            if _parse_ts(str(entry["ts"])) >= cutoff:
                result.append(entry)
        except (KeyError, ValueError):
            continue
    return result


def average_score(history: list[dict[str, Any]], days: int | None = None) -> float | None:
    """Mean score over history; optional window in days."""
    subset = entries_last_n_days(history, days) if days else history
    scores = [int(e["score"]) for e in subset if "score" in e]
    if not scores:
        return None
    return sum(scores) / len(scores)


def sparkline_scores(history: list[dict[str, Any]], limit: int = 50) -> list[int]:
    """Last N scores in chronological order."""
    scores = [int(e["score"]) for e in history if "score" in e]
    return scores[-limit:]


def per_site_stats(
    history: list[dict[str, Any]], days: int = 7
) -> dict[str, dict[str, float | str | None]]:
    """Last status and 7d pass rate per site key."""
    from canary.sites import SITE_KEYS

    recent = entries_last_n_days(history, days)
    stats: dict[str, dict[str, float | str | None]] = {}
    for key in SITE_KEYS:
        statuses: list[str] = []
        for entry in recent:
            per_site = entry.get("per_site") or {}
            if key in per_site:
                statuses.append(str(per_site[key]))
        last_status: str | None = None
        if history:
            last_per = history[-1].get("per_site") or {}
            last_status = str(last_per[key]) if key in last_per else None
        pass_rate = 0.0
        if statuses:
            passes = sum(1 for s in statuses if s == "pass")
            pass_rate = passes / len(statuses) * 100
        stats[key] = {"last_status": last_status, "pass_rate_7d": pass_rate}
    return stats


def consecutive_low_scores(
    history: list[dict[str, Any]],
    threshold: int = 75,
    count: int = 3,
) -> bool:
    """True if the last `count` runs all scored below threshold."""
    if len(history) < count:
        return False
    tail = history[-count:]
    return all(int(e.get("score", 100)) < threshold for e in tail)