# Agentic Stealth Browser

**Playwright gets detected. This doesn't.**

[![CI](https://github.com/shanewas/agentic-stealth-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/shanewas/agentic-stealth-browser/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/agentic-stealth-browser.svg)](https://pypi.org/project/agentic-stealth-browser/)
[![Tests](https://img.shields.io/badge/tests-890%2B%20passing-brightgreen)](tests/)
[![GitHub Stars](https://img.shields.io/github/stars/shanewas/agentic-stealth-browser?style=flat&logo=github)](https://github.com/shanewas/agentic-stealth-browser)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-ffdd00?logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/shanewas)

<p align="center">
  <img src="assets/hn-demo.gif" alt="Agentic Stealth Browser Demo" width="90%">
</p>

Production-grade stealth browser automation that **survives Cloudflare, LinkedIn, Amazon, and other anti-bot systems** by looking convincingly human at every layer.

```bash
pip install agentic-stealth-browser
playwright install --with-deps chromium
```

```python
from core.agent_browser import AgentBrowser

async with AgentBrowser(session_name="demo") as browser:
    await browser.launch(headless=True)
    await browser.safe_goto("https://bot.sannysoft.com")
    # ✓ passes WebGL, Canvas, AudioContext, WebRTC, and TLS fingerprinting
```

---

## Why vanilla Playwright fails

Sites don't just check your User-Agent anymore. They check *everything*:

| Attack Surface | Vanilla Playwright | This library |
|---|---|---|
| **TLS handshake** (JA3/JA4 fingerprint) | Standard Python TLS — instantly identifiable | Region-spoofed profiles (US, Japan, EU, Korea) |
| **Navigator APIs** (`navigator.webdriver`, `plugins`, `languages`) | Leaks automation flags everywhere | Every property patched before first paint |
| **WebGL / Canvas fingerprint** | Headless GPU renders differently | Consistent buffers across sessions |
| **Human behavior** | Robotic clicks, instant typing | Bézier mouse curves, variable speed, fatigue simulation |
| **Auto-recovery** | None — blocks = failure | CAPTCHA detection → proxy rotation → retry chain |
| **Account warming** | Nothing | 14-day graduated ramp-up per account |

Result: **passes bot.sannysoft.com, pixelscan.net, and CreepJS** with zero flags in headless mode.

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
async with AgentBrowser(session_name="attached") as browser:
    await browser.attach_over_cdp(
        "http://127.0.0.1:9222",   # or the Windows host IP from WSL
        new_context=True,           # don't disturb the user's tabs
    )
    await browser.safe_goto("https://bot.sannysoft.com")
    # close() will NOT terminate the external browser
```

See [docs/ATTACH_OVER_CDP.md](docs/ATTACH_OVER_CDP.md) for the WSL→Windows
walkthrough, the MCP `stealth_attach_over_cdp` tool, and the stealth
degradation matrix (init-script stealth still applies; TLS/JA3 does not).

---

## Key Features

| Feature | What It Does |
|---|---|
| **TLS Fingerprinting** | JA3/JA4 region profiles |
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

## New in v2.3.0

- **Show HN launch** — README overhaul, demo GIF, streamlined community onboarding
- **Buy Me A Coffee** — sponsor the project directly
- **PID tracking** — `AgentBrowser._browser_process` for external process monitoring
- **PyPI publish automation** — OIDC trusted publishing on every release tag

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
└── tests/          890+ contract + integration tests
```

## License

MIT. See [LICENSE](LICENSE) and [CHANGELOG.md](CHANGELOG.md).
