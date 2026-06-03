"""Static HTML dashboard generation from canary history."""

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from canary.history import (
    average_score,
    entries_last_n_days,
    per_site_stats,
    sparkline_scores,
)
from canary.score import score_color
from canary.sites import SITES

_TEMPLATES = Path(__file__).parent / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    )


def _status_class(status: str | None) -> str:
    if status is None:
        return "unknown"
    return status.replace("-", "_")


def build_dashboard_context(history: list[dict[str, Any]]) -> dict[str, Any]:
    latest = history[-1] if history else None
    current_score = int(latest["score"]) if latest else 0
    avg_7d = average_score(history, days=7)
    site_stats = per_site_stats(history, days=7)
    rows = []
    for site in SITES:
        key = site["key"]
        st = site_stats.get(key, {})
        rows.append(
            {
                "name": site["name"],
                "url": site["url"],
                "key": key,
                "last_status": st.get("last_status"),
                "pass_rate_7d": st.get("pass_rate_7d", 0.0),
                "status_class": _status_class(
                    str(st["last_status"]) if st.get("last_status") else None
                ),
            }
        )
    last_ts = str(latest["ts"]) if latest else "never"
    recent_count = len(entries_last_n_days(history, 7))
    return {
        "current_score": current_score,
        "score_color": score_color(current_score),
        "avg_7d": round(avg_7d, 1) if avg_7d is not None else None,
        "rows": rows,
        "sparkline_data": json.dumps(sparkline_scores(history, 50)),
        "last_updated": last_ts,
        "run_count": len(history),
        "recent_7d_count": recent_count,
        "version": str(latest.get("version", "unknown")) if latest else "unknown",
    }


def render_dashboard(history: list[dict[str, Any]]) -> str:
    template = _env().get_template("dashboard.html.j2")
    return str(template.render(**build_dashboard_context(history)))


def generate_dashboard(history: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_dashboard(history), encoding="utf-8")
