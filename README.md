# Agentic Stealth Browser

**Playwright gets detected. This is much harder to detect.**

[![CI](https://github.com/shanewas/agentic-stealth-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/shanewas/agentic-stealth-browser/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/agentic-stealth-browser.svg)](https://pypi.org/project/agentic-stealth-browser/)
[![GitHub Stars](https://img.shields.io/github/stars/shanewas/agentic-stealth-browser?style=flat&logo=github)](https://github.com/shanewas/agentic-stealth-browser)

<p align="center">
  <img src="assets/hn-demo.gif" alt="Agentic Stealth Browser Demo" width="90%">
</p>

## Legal & Acceptable Use

This is an anti-bot-evasion tool. Read the [Acceptable Use Policy](ACCEPTABLE_USE.md) before use — you are responsible for using it lawfully and within the target site's Terms of Service.

## What is this

A production-grade stealth browser automation library for Python, built on Playwright.
It survives modern anti-bot systems (Cloudflare, LinkedIn, Amazon, etc.) by looking
convincingly human at every layer — TLS, navigator, WebGL/Canvas, behavior, recovery.

**When to use it** — you are building an autonomous agent, scraper, or operator tool
that needs to pass bot detection in headless mode on protected sites.

**When NOT to use it** — you only need to scrape public, unprotected pages (use
`httpx` + `selectolax` or `playwright` directly). You need a real uTLS stack at the
wire level (use `curl_cffi`). You need CAPTCHA solving (this project intentionally
stops at detection + intervention; see Limitations below).

```bash
pip install agentic-stealth-browser
playwright install --with-deps chromium
```

```python
from core.agent_browser import AgentBrowser

async with AgentBrowser(session_name="demo") as browser:
    await browser.launch(headless=True)
    await browser.safe_goto("https://bot.sannysoft.com")
    # passes WebGL, Canvas, AudioContext, WebRTC, and TLS fingerprint checks
```

---

## Why vanilla Playwright fails

Sites don't just check your User-Agent anymore. They check *everything*:

| Attack Surface | Vanilla Playwright | This library |
|---|---|---|
| **TLS handshake** (client hello / JA3/JA4-ish) | Standard Python TLS — instantly identifiable | Region-spoofed TLS profile (process-level, not custom uTLS) |
| **Navigator APIs** (`navigator.webdriver`, `plugins`, `languages`) | Leaks automation flags everywhere | Every property patched before first paint |
| **WebGL / Canvas fingerprint** | Headless GPU renders differently | Consistent buffers across sessions |
| **Human behavior** | Robotic clicks, instant typing | Bézier mouse curves, variable speed, fatigue simulation |
| **Auto-recovery** | None — blocks = failure | CAPTCHA detection → proxy rotation → retry chain |
| **Account warming** | Nothing | 14-day graduated ramp-up per account |

Result: **passes bot.sannysoft.com, pixelscan.net, and CreepJS** with zero flags in
headless mode as of the latest 4-hourly canary run (detection canaries run every 4 hours
via `docs/canary.md`).

---

## Limitations & honest claims

This library is opinionated and has real limits. Operators should know them up front:

- **Not a real uTLS stack.** TLS fingerprinting is process-level (region-matched
  client-hello, init-script negotiation). It is *not* `curl_cffi`-grade wire-level
  impersonation. Attach mode (CDP) degrades further: the host browser's TLS is whatever
  the user already has.
- **Headless detection is a moving target.** Detection vendors change heuristics
  weekly. This project runs a 4-hourly detection canary
  ([docs/canary.md](docs/canary.md)) and patches regressions, but zero-flag is a
  snapshot, not a guarantee.
- **No CAPTCHA solving.** The recovery chain *detects* CAPTCHAs and surfaces them to
  the operator dashboard for manual intervention. It does not call solving services.
  If you need solver integration, build a `BasePlugin` that calls your provider and
  drops the cookie back into the session.
- **E2E tests against live protected sites are opt-in.** The default CI runs
  contract + mocked integration tests. Live-site E2E (`RUN_E2E_ANTI_BLOCK=1`) is
  flaky by nature and skipped on PRs.
- **Login credentials are not shipped.** Examples that touch authenticated endpoints
  stop at the search/listing stage.

---

## Quick Start

### CLI (easiest)

```bash
# Health check + stealth fingerprint test
stealth-browser health --preset linkedin_2026 --region us

# Start the operator dashboard
agentic-stealth-browser dashboard
```

### Python SDK

```python
from core.agent_browser import AgentBrowser

async with AgentBrowser(
    session_name="my-session",
    region="japan",
    headless=True
) as browser:
    await browser.launch()
    await browser.safe_goto("https://example.com")
    # TLS-spoofed, no webdriver leak, human-like interaction ready
```

### MCP (for AI agent clients)

```json
{
  "mcpServers": {
    "stealth-browser": {
      "command": "python",
      "args": ["-m", "production.mcp_server"]
    }
  }
}
```

Then: `stealth_launch` → `stealth_navigate` → `stealth_scrape` → `stealth_close`.

### Attach to an existing browser (WSL → Windows, container → host)

Instead of launching a new Chromium, you can attach to a Chrome you already
have running with `--remote-debugging-port=9222`:

```python
# Attach mode: use a fresh instance (async-with auto-launches a new browser first).
browser = AgentBrowser(session_name="attached")
await browser.attach_over_cdp(
    "http://127.0.0.1:9222",   # or the Windows host IP from WSL
    new_context=True,           # don't disturb the user's tabs
)
await browser.safe_goto("https://bot.sannysoft.com")
# safe actions + MCP scrape now operational on attached; close() leaves external browser running.
await browser.close()
```

See [docs/ATTACH_OVER_CDP.md](docs/ATTACH_OVER_CDP.md) for the WSL→Windows
walkthrough, the MCP `stealth_attach_over_cdp` tool, and the stealth
degradation matrix (init-script stealth still applies; TLS/JA3 does not).

---

## Install from source

```bash
git clone https://github.com/shanewas/agentic-stealth-browser.git
cd agentic-stealth-browser
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
pytest tests/ -q
```

The dev extras pull in `pytest`, `pytest-asyncio`, `ruff`, and the test fixture
deps. The full suite takes ~2 minutes on a warm cache; the default run skips
live E2E (`RUN_E2E_ANTI_BLOCK=1` to enable).

---

## Key Features

| Feature | What It Does |
|---|---|
| **TLS Fingerprinting** | Region client-hello profiles (JA3/JA4 surface); attach mode degrades (process-level) |
| **Human Behavior** | Mouse wobble, typing mistakes, fatigue, distraction |
| **Auto Recovery** | Block detection → proxy/session rotation → retry |
| **Account Warming** | 14-day gradual ramp-up for new accounts |
| **Workflow Orchestrator** | Queue, schedule, domain concurrency, retries, persistence |
| **Python SDK** | `StealthClient` — async API without MCP |
| **Security Governance** | Input validation, session isolation, policy engine, approval gates |
| **Adaptive Stealth** | Per-domain behavior profiles with FeedbackStore telemetry |
| **Plugin System** | Lifecycle hooks via `BasePlugin` |
| **Operator Dashboard** | Live DevTools, CAPTCHA intervention, workflow recording |
| **Feature Flags** | Runtime capability discovery per browser backend |
| **Performance Profiling** | Timing decorators + `perf_benchmark.py` |

---

## New in v2.6.0

- **Stealth patch isolation** — per-patch try/catch in `advanced_stealth.py`; one
  API mismatch no longer aborts every patch queued after it
- **Attach-mode fingerprint coherence** — new `attach_mode` skips
  navigator.platform / WebGL vendor-renderer / screen-DPR overrides that would
  otherwise contradict a real attached browser's OS/GPU
- **WebRTC leak hardening** — per-instance `onicecandidate` rebind (no
  prototype-global leak); the `addEventListener('icecandidate')` variant is
  now filtered too
- **MCP policy/approval gates** — `PolicyEngine` + `ApprovalGate` wired into
  the dispatch path, fail-open by default (opt-in enforcement via
  `STEALTH_MCP_POLICY` env)
- **Adapter `isError` surfacing** — failed MCP tool calls now raise
  `AdapterToolError` instead of reporting silent success; playwright-mcp
  pinned to 0.0.78 with the corrected tool schema
- **Recovery rotation-failure correctness** — failed rotations now propagate
  and record history instead of silently succeeding

See [CHANGELOG.md](CHANGELOG.md) for the full release history.

---

## New in v2.5.0

- **BackendAdapter protocol** — pluggable execution backends (M0–M4 shipped)
  across CDP-bridge, playwright-mcp, and agentic-stealth-mcp
- **Real dashboard backends** — the Hermes dashboard now wires a thin shim over
  the adapter protocol, so the same UI drives all three backends
- **Attach-mode hardening** — adopted tabs are preserved on `close()`; bad
  context/stealth installs roll back cleanly; `human`/`scraper`/`recovery`
  initialized for attach
- **CLI `status`** — added `--headless` and `--session` flags for headless
  operator checks against a named session

See [CHANGELOG.md](CHANGELOG.md) for the full release history.

---

## Full Documentation

- **[Operator Dashboard](production/hermes_dashboard.py)** — Grok/X-inspired dark UI, live browser view, CAPTCHA solving, workflow recording
- **[Workflow Orchestrator](production/workflow_orchestrator.py)** — queue, schedule, chain workflows with domain-aware concurrency
- **[Security](production/)** — input validation, session isolation, policy engine, approval gates
- **[SDK](production/sdk/)** — `StealthClient` async API without MCP
- **[Plugins](plugins/)** — lifecycle hooks for custom behavior
- **[VPS Deployment](scripts/setup_rbb.sh)** — systemd, Caddy reverse proxy, Cloudflare Tunnel patterns
- **[Migration v1 → v2](scripts/migrate_v1_to_v2.py)** — deprecation shims, migration guide, script
- **[Documentation index](docs/README.md)** — full docs/ tree: attach-over-CDP, canary, plans, analysis
- **[Examples](examples/recipes/)** — runnable recipes for Cloudflare, LinkedIn, Amazon

Additional references: [CHANGELOG.md](CHANGELOG.md) · [Workflow Library](workflows/library/) · [Migration Guide](scripts/migrate_v1_to_v2.py)

---

## Project Structure

```
├── core/           AgentBrowser, connection pool, session checkpoints
├── stealth/        TLS, scripts, Firefox adapter, caching
├── behavior/       Human simulation, personas, adaptive tuning
├── recovery/       Anti-block orchestrator
├── workflows/      Recorder, player, schema, library
├── production/     MCP server, SDK, orchestrator, security, profiler
├── plugins/        Plugin system with template
├── scripts/        Migration, evaluation, benchmarking
├── docs/           Attach-over-CDP, canary, plans, analysis
├── examples/       Runnable recipes (Cloudflare, LinkedIn, Amazon)
└── tests/          Contract + integration tests (live E2E opt-in)
```

## License

MIT. See [LICENSE](LICENSE) and [CHANGELOG.md](CHANGELOG.md).
