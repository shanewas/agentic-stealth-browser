# Service Level Objectives

SLOs are computed from the `/metrics` Prometheus endpoint.

| SLO | Target | Prometheus expression | Error budget |
|---|---|---|---|
| Navigation success rate | >=95% | `requests_success / (requests_success + requests_failed)` | 5% failures/30d |
| Block rate | <5% | `blocks_total / requests_total` | 5% blocks |
| p95 navigation latency | <10s | derived from `safe_goto_seconds` summary (p95 needs histogram buckets, currently approximated by max) | n/a |

## Recording rules

These become Prometheus recording rules once a scrape job targets `/metrics`. On breach, see docs/RUNBOOK.md.

Metric names are emitted by core/agent_browser.py (`requests_success`, `requests_failed`, `requests_total`) and recovery/anti_block_orchestrator.py (`blocks_total`, `rotations_total`, `captcha_total`).
