"""Run the canary, write history + dashboard, print summary."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from canary.badge_gen import generate_badge
from canary.dashboard_gen import generate_dashboard
from canary.history import append_history, consecutive_low_scores, read_history
from canary.readme_gen import generate_readme
from canary.runner import CanaryRunner


async def main() -> None:
    history_path = Path(
        os.environ.get("CANARY_HISTORY_PATH", "docs/canary/history.jsonl")
    )
    dashboard_path = Path(
        os.environ.get("CANARY_DASHBOARD_PATH", "docs/canary/index.html")
    )
    badge_path = Path(os.environ.get("CANARY_BADGE_PATH", "docs/canary/badge.svg"))
    readme_path = Path(os.environ.get("CANARY_README_PATH", "docs/canary/README.md"))

    history_path.parent.mkdir(parents=True, exist_ok=True)

    runner = CanaryRunner()
    result = await runner.run_all()
    print(json.dumps(result, indent=2))

    append_history(history_path, result)
    history = read_history(history_path)

    generate_dashboard(history, dashboard_path)
    generate_badge(history, badge_path)
    generate_readme(history, readme_path)

    if "GITHUB_OUTPUT" in os.environ:
        alert = consecutive_low_scores(history, threshold=75, count=3)
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"score={result['score']}\n")
            f.write(f"ts={result['ts']}\n")
            f.write(f"alert={'true' if alert else 'false'}\n")

    sys.exit(0 if result["error"] is None else 1)


if __name__ == "__main__":
    asyncio.run(main())