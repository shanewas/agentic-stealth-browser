# Agentic Stealth Browser

[![CI](https://github.com/shanewas/agentic-stealth-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/shanewas/agentic-stealth-browser/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/agentic-stealth-browser.svg)](https://pypi.org/project/agentic-stealth-browser/)
[![Tests](https://img.shields.io/badge/tests-880%2B%20passing-brightgreen)](tests/)

**Production-grade stealth browser automation** that looks human. Handles Cloudflare, LinkedIn, Amazon, and other anti-bot systems.

> **Documentation**: This README is the complete, up-to-date user guide. The previous `docs/` folder has been removed. Historical design documents (ADRs, RFCs) are still available in git history.

## Installation

### From PyPI (Recommended)

```bash
pip install agentic-stealth-browser
playwright install --with-deps chromium
```

### For Development / Contributing

```bash
git clone https://github.com/shanewas/agentic-stealth-browser.git
cd agentic-stealth-browser
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install --with-deps chromium
```

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

async with AgentBrowser(session_name="my-session") as browser:
    await browser.launch(headless=True)
    await browser.safe_goto("https://example.com")
    # ... use stealth navigation, human behavior, recovery, etc.
```

See the full usage guide below for MCP server, dashboard, workflows, and production deployment.

For release history, see [CHANGELOG.md](CHANGELOG.md).

## Why This Exists

Standard `page.goto()` / `page.click()` gets detected instantly. This solves it with:

- **TLS fingerprint spoofing** — region-specific TLS handshakes (US, Japan, EU, Korea)
- **Human behavior** — Bézier mouse curves, natural typing, distraction simulation
- **Auto recovery** — detects CAPTCHAs, rate limits, blocks and recovers automatically
- **Workflow Teach/Replay** — record real browser actions via CDP, replay as YAML

## Local vs VPS Usage

### Local (Developer / Daily Driver)

Use this when running on your laptop for development, testing stealth, or pairing with Claude Desktop / Cursor / Windsurf.

- Default binding is `127.0.0.1:8443` (safe).
- Great for visual debugging with the dashboard.
- Use the MCP server for agent clients on the same machine.

### VPS / Production / Headless Server (Always-on Automation)

Use this for 24/7 LinkedIn automation, scraping fleets, account warming, etc.

**Key rules for VPS:**
- Never expose the dashboard directly on the public internet.
- Always run behind HTTPS (Caddy, Nginx, Cloudflare Tunnel, or Tailscale).
- Use a dedicated low-privilege user (`stealth`).
- Persist `~/.agentic-browser/` (or mounted volume) for cookies, profiles, and workflows.
- Strong random password for the dashboard.

**Recommended production setup:**
1. Systemd service for the dashboard or MCP server.
2. Reverse proxy (Caddy is easiest) for HTTPS.
3. (Optional but recommended) Cloudflare Tunnel or Tailscale so you only reach the dashboard from your IP / team.

Example systemd service (`/etc/systemd/system/hermes-dashboard.service`):

```ini
[Unit]
Description=Hermes Stealth Browser Dashboard
After=network.target

[Service]
Type=simple
User=stealth
WorkingDirectory=/opt/agentic-stealth-browser
Environment=HERMES_DASHBOARD_PASSWORD=REPLACE_WITH_VERY_LONG_RANDOM_STRING
ExecStart=/opt/agentic-stealth-browser/.venv/bin/agentic-stealth-browser dashboard --host 127.0.0.1 --port 8443
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hermes-dashboard
journalctl -u hermes-dashboard -f
```

**HTTPS + Reverse Proxy (Caddy example — simplest)**

```
your-stealth.example.com {
    reverse_proxy localhost:8443
}
```

For Nginx or more advanced `cookie_secure + security headers`, here is a minimal production-hardened pattern:

**Nginx snippet (HTTPS termination)**

```nginx
server {
    listen 443 ssl http2;
    server_name stealth.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8443;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

After putting Nginx/Caddy in front, update the dashboard launch to use secure cookies (recommended):

```bash
HERMES_DASHBOARD_COOKIE_SECURE=true agentic-stealth-browser dashboard ...
```

(You can also set it via the `DashboardSettings` class if running the Python API directly.)

## MCP + Dashboard Quick Start

Run the MCP server when an agent client needs tool access to the browser:

```bash
python -m production.mcp_server
```

Add this server to your MCP client config:

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

Common MCP flow:

```text
1. stealth_launch      -> start a named browser session
2. stealth_navigate    -> open a URL with recovery behavior
3. stealth_tabs_list   -> inspect current tabs/pages
4. stealth_tab_snapshot -> capture screenshot + metadata
5. stealth_teach       -> save a demonstrated workflow
6. stealth_replay      -> replay a saved workflow YAML
7. stealth_close       -> close the session
```

### Hermes Operator Dashboard (Recommended for Human-in-the-Loop)

The dashboard has been completely revamped with a clean, dark, Grok/X-inspired design (deep zinc palette, blue accents, modern cards, real-time polling, modals, live activity, workflow management, and intervention flows).

```bash
export HERMES_DASHBOARD_PASSWORD="a-strong-unique-password"
agentic-stealth-browser dashboard --host 127.0.0.1 --port 8443
```

Open **http://127.0.0.1:8443**, log in, and:

- Launch / restart / stop managed browser sessions
- Watch live DevTools (best with `cdp-bridge` backend)
- Navigate + manual actions (click, fill, type)
- Request human intervention on CAPTCHAs / logins
- Record real interactions → save as YAML workflows
- Replay workflows with variable substitution
- Live searchable activity timeline + screenshots

The dashboard is the recommended way to visually debug, handle CAPTCHAs/logins manually, teach workflows, and monitor automation. Full usage details are in the "Hermes Operator Dashboard" section below.

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

Add to `claude_desktop_config.json` or the equivalent MCP client config:

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

Useful observability tools:

- `stealth_tabs_list`: list active tabs/pages.
- `stealth_tab_snapshot`: capture screenshot and page metadata.
- `stealth_session_timeline`: inspect recent action/recovery/debug events.
- `stealth_debug_report`: get redacted runtime diagnostics.

To expose a local CDP endpoint for supported clients, launch with `debug_cdp: true`, then call `stealth_get_cdp_endpoint`. The endpoint is localhost-only and should not be exposed directly to the internet.

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

Deprecated APIs (`self.context`, `ConnectionPool`, ad-hoc MCP responses) have shims. See the v2 migration notes in CHANGELOG.md.

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
└── tests/          880+ contract + integration tests
```

This project keeps design history in git and prioritizes a single, practical README for users.

## License

MIT. See [LICENSE](LICENSE) and [CHANGELOG.md](CHANGELOG.md).
