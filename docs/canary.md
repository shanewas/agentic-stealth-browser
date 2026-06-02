# ASB Canary (asb-canary v0.1)

The **canary** package runs a scheduled, public honesty check against six known
bot-detection sites. Results are appended to `docs/canary/history.jsonl`, and a
static dashboard is regenerated under `docs/canary/` for hosting (e.g.
Cloudflare Pages).

## Run locally

```bash
pip install -e ".[dev]"
playwright install --with-deps chromium
python scripts/canary_run.py
```

Environment variables:

| Variable | Default |
|----------|---------|
| `CANARY_HISTORY_PATH` | `docs/canary/history.jsonl` |
| `CANARY_DASHBOARD_PATH` | `docs/canary/index.html` |
| `CANARY_BADGE_PATH` | `docs/canary/badge.svg` |
| `CANARY_README_PATH` | `docs/canary/README.md` |

## CI

`.github/workflows/canary.yml` runs every four hours and on `workflow_dispatch`.
It commits updated files under `docs/canary/` and opens a GitHub issue when the
score stays below 75% for three consecutive runs.

## Scoring

Per site: `pass`, `soft-detect`, `detected`, or `fail`.

```
score = (passes × 1.0 + soft-detects × 0.5) / 6 × 100
```

## Relation to `tests/detection_runner.py`

`detection_runner.py` is an internal stealth QA suite with different sites and
goals. The canary is a **public, append-only record** with a fixed six-site
catalog and a simple weighted score for the dashboard.