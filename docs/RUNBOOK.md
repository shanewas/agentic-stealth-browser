# Operator Runbook

## CAPTCHA intervention (intervention_requested)

Recovery detects `BlockType.CAPTCHA` -> dashboard surfaces via `POST /api/intervention/request`. Operator opens `live_view_url` in DevTools. Resolves via `POST /api/intervention/resolve`, only operator-role per OBS-03.

## Block / rate-limit recovery

`blocks_total`/`rotations_total` climbing: orchestrator auto-rotates via `PLATFORM_STRATEGIES`. Intervene on `circuit_breaker_open` / `MaxRetriesExceeded`. `safe_mode`/fail-fast stops proxy churn.

## Where to look

- Dashboard `/metrics`, `/api/usage`
- Persistent audit log `~/.agentic-browser/hermes_dashboard/audit.jsonl`
- docs/SLO.md
