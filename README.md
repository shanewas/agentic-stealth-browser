# Agentic Stealth Browser

[![CI](https://github.com/shanewas/agentic-stealth-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/shanewas/agentic-stealth-browser/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)](https://pypi.org/project/agentic-stealth-browser/)
[![Tests](https://img.shields.io/badge/tests-880%2B%20passing-brightgreen)](tests/)

Python framework for browser automation that looks human. Handles Cloudflare, LinkedIn, Amazon, and other anti-bot systems. **v2.0.0 GA** — SDK, orchestration, security governance, adaptive stealth, plugins.

## Why This Exists

Standard `page.goto()` / `page.click()` gets detected instantly. This solves it with:

- **TLS fingerprint spoofing** — region-specific TLS handshakes (US, Japan, EU, Korea)
- **Human behavior** — Bézier mouse curves, natural typing, distraction simulation
- **Auto recovery** — detects CAPTCHAs, rate limits, blocks and recovers automatically
- **Workflow Teach/Replay** — record real browser actions via CDP, replay as YAML

## Quick Start

```bash
pip install agentic-stealth-browser
playwright install --with-deps chromium
```

```python
from core.agent_browser import AgentBrowser

async with AgentBrowser(session_name="demo") as browser:
    await browser.launch(headless=True)
    await browser.safe_goto("https://example.com")
```

## Workflow System

Record real interactions and replay autonomously:

```python
from workflows.recorder import WorkflowRecorder
from workflows.player import WorkflowPlayer
from workflows.schema import load_workflow

recorder = WorkflowRecorder(cdp_url="http://localhost:9222")
workflow = await recorder.record("upwork_update_title")

player = WorkflowPlayer(browser, workflow)
result = await player.execute()
```

13 step types: `navigate` · `click` · `fill` · `type` · `select` · `verify` · `wait` · `wait_for_element` · `scroll` · `screenshot` · `execute_js` · `conditional` · `run_workflow`

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
| **Plugin System** | Lifecycle hooks via `BasePlugin` (launch, navigate, scrape, close) |
| **Feature Flags** | Runtime capability discovery per browser backend |
| **Migration Tools** | v1→v2 script, deprecation shims, migration guide |
| **Performance Profiling** | Timing decorators + `perf_benchmark.py` |

## MCP Setup

Add to `claude_desktop_config.json`:

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

Tools: `stealth_launch`, `stealth_navigate`, `stealth_load_cookies`, `stealth_scrape`, `stealth_teach`, `stealth_replay`, `stealth_tabs_list`, `stealth_session_timeline`, `stealth_close`, `stealth_capabilities`, and more.

## Orchestrator

Queue, schedule, and chain workflows with domain-aware concurrency:

```python
from production.workflow_orchestrator import WorkflowOrchestrator

orch = WorkflowOrchestrator(domain_concurrency={"linkedin.com": 1})
await orch.enqueue("workflows/upwork/edit-title.yaml", priority=10)
await orch.schedule_recurring("workflows/linkedin/check-notifications.yaml", interval_seconds=3600)
await orch.run()
```

## Security

- **Input validation**: Type, length, pattern checks on all MCP tool params
- **Session isolation**: One context can't access another's browser instances
- **Policy engine**: YAML-based access control per site / step type
- **Approval gates**: Sensitive actions (navigate, execute_js) require explicit approval

## SDK

Use without MCP:

```python
from production.sdk import StealthClient

async with StealthClient(session_name="mybot") as client:
    await client.navigate("https://example.com")
    result = await client.execute_workflow("linkedin/send-connection-request", variables={"name": "Jane"})
```

## Plugins

```python
from plugins.template import ExamplePlugin

class MyPlugin(ExamplePlugin):
    name = "my-plugin"
    async def on_navigate(self, ctx, url):
        ctx.logger.info(f"[{self.name}] Navigating to {url}")
```

Hooks: `on_launch`, `on_navigate`, `on_page_loaded`, `on_scraped`, `on_close`.

## Migration v1 → v2

```bash
python scripts/migrate_v1_to_v2.py --input workflow.yaml --output workflow-v2.yaml
```

Deprecated APIs (`self.context`, `ConnectionPool`, ad-hoc MCP responses) have shims. See [docs/rfc/v2-migration.md](docs/rfc/v2-migration.md).

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
└── docs/           ADRs, RFCs, capability map, guides
```

## Documentation

- [Architecture Decision Records](docs/adr/)
- [Operator Setup Guide](docs/OPERATOR_SETUP.md)
- [Capability Map](docs/CAPABILITY_MAP.md)
- [MCP Browser Observability](docs/MCP_BROWSER_OBSERVABILITY.md)
- [v2 Migration RFC](docs/rfc/v2-migration.md)
- [Stealth Limitations](docs/STEALTH_LIMITATIONS.md)
- [Threat Model](docs/THREAT_MODEL.md)

## License

MIT. See [LICENSE](LICENSE) and [CHANGELOG.md](CHANGELOG.md).
