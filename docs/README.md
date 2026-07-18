# Documentation

Operator and contributor reference for `agentic-stealth-browser`.

## Operator docs

- **[ATTACH_OVER_CDP.md](ATTACH_OVER_CDP.md)** — attach to a running Chromium
  via the Chrome DevTools Protocol. Covers WSL→Windows, container→host,
  teardown modes, and the stealth degradation matrix.
- **[canary.md](canary.md)** — the public 4-hourly detection canary. What it
  scores, how to run it locally, where the dashboard is regenerated.

## Planning & historical

- **[agentic-stealth-browser-analysis-report.md](agentic-stealth-browser-analysis-report.md)** — historical v0.8.0 architecture snapshot; superseded, kept for context.
- **[plans/2026-06-01-v2.4.0-attach-mode-hardening.md](plans/2026-06-01-v2.4.0-attach-mode-hardening.md)**
  — the v2.4.0 attach-mode hardening plan (RFC-1918 gate, `TeardownMode`
  enum, stealth install surface).
- **[plans/2026-06-03-v2.5.0-real-backend-adapters.md](plans/2026-06-03-v2.5.0-real-backend-adapters.md)**
  — the v2.5.0 BackendAdapter protocol plan (M0–M4 shipped).
- **[plans/misc/](plans/misc/)** — historical planning artifacts from prior
  self-driven release prep (open-source readiness assessment, Show HN draft,
  autonomous release log, dashboard goal-mode brief). Preserved for context.
