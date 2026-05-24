# Agentic Stealth Browser

[![CI](https://github.com/shanewas/agentic-stealth-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/shanewas/agentic-stealth-browser/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-1.0.1-blue.svg)](https://pypi.org/project/agentic-stealth-browser/)
[![Tests](https://img.shields.io/badge/tests-500%2B%20passing-brightgreen)](tests/)

A Python framework that makes browser automation look human. Built for autonomous agents that need to navigate websites protected by Cloudflare, LinkedIn, Amazon, and other anti-bot systems. **v1.0.0** introduced the Teach/Replay workflow system — record real user interactions and replay them with full stealth. **v1.0.1** ships critical security fixes for MCP redaction and JS injection, plus workflow library cleanup.

## Why This Exists

Standard browser automation (`page.goto()`, `page.click()`) gets detected instantly. This framework solves that by combining:

- **TLS fingerprint spoofing** — matches real browser TLS handshakes
- **Human behavior simulation** — natural mouse, typing, scrolling with realistic imperfections
- **Automatic recovery** — detects blocks (CAPTCHAs, rate limits) and recovers without crashing
- **Account lifecycle management** — warming, health scoring, cooling off
- **Workflow Teach/Replay** — record real user actions via CDP, save as YAML, replay with fallbacks

## Installation

```bash
pip install agentic-stealth-browser
playwright install --with-deps chromium
```

## Quick Start

```python
from core.agent_browser import AgentBrowser
import asyncio

async def main():
    browser = AgentBrowser(session_name="demo")
    await browser.launch(headless=True)

    # This handles stealth, human behavior, and recovery automatically
    await browser.safe_goto("https://example.com")

    # Add human-like actions
    await browser.human.scroll_naturally(400)
    await browser.human.think(1500, 2800)

    await browser.close()

asyncio.run(main())
```

## Real-World Example

For protected sites, load real cookies and use a platform preset:

```python
browser = AgentBrowser(session_name="linkedin")
await browser.launch(preset="linkedin_2026")
await browser.load_cookies_from_file("cookies.json")
await browser.warm_up_before_work(intensity="heavy")
await browser.safe_goto("https://www.linkedin.com/feed/", platform="linkedin")
```

The flow: **cookies → warm-up → navigate → recover if blocked → act human**.

## Workflow System (v1.0.0)

Record real user interactions and replay them autonomously — the "teach mode" for browser automation.

### Teach — Record a Workflow

```python
from workflows.recorder import WorkflowRecorder

recorder = WorkflowRecorder(cdp_url="http://localhost:9222")
async with recorder:
    await recorder.start_capture()
    # User performs actions in their real browser...
    workflow = await recorder.stop_and_save("upwork_edit_title.yaml")
```

### Replay — Execute a Saved Workflow

```python
from workflows.player import WorkflowPlayer
from workflows.schema import load_workflow

workflow = load_workflow("workflows/library/upwork/edit-title.yaml")
player = WorkflowPlayer(browser, workflow)
result = await player.execute()
print(f"Done: {result.success} — {result.steps_passed}/{result.steps_total}")
```

### Workflow Library

Pre-built, production-tested workflows included out of the box:

| Workflow | Platform | What It Does |
|---|---|---|
| `edit-title` | Upwork | Updates profile title |
| `update-rate` | Upwork | Changes hourly rate |
| `add-portfolio` | Upwork | Adds portfolio item |
| `submit-proposal` | Upwork | Submits a proposal |
| `send-connection-request` | LinkedIn | Sends connection request |

### From MCP (AI Agent)

```json
{
  "tool": "stealth_teach",
  "args": { "session_name": "my-flow", "cdp_url": "http://localhost:9222" }
}
```

```json
{
  "tool": "stealth_replay",
  "args": { "workflow_path": "upwork/edit-title.yaml" }
}
```

### Workflow Schema

Each workflow is a YAML file with typed steps. 13 step types supported:

`navigate` · `click` · `fill` · `type` · `select` · `verify` · `wait` · `wait_for_element` · `scroll` · `screenshot` · `execute_js` · `conditional` · `run_workflow`

Variables (`{{variable}}`) resolve at runtime with built-in support for `timestamp`, `date`, `random_name`, `last_url`.

## Remote Bridge

Connect the stealth framework to a browser running on another machine — ideal for keeping cookies/sessions on your local Windows PC while the agent runs on a VPS.

```
Windows (Edge + CDP)  ←ngrok→  VPS (Agentic Stealth Browser)
```

Setup scripts included for both Linux (`scripts/setup_rbb.sh`) and Windows (`scripts/setup_rbb.ps1`). Requires Edge/Chrome launched with `--remote-debugging-port=9222`.

See [docs/OPERATOR_SETUP.md](docs/OPERATOR_SETUP.md) for full setup guide, failure modes, and backend selection.

## How It Works

```
AgentBrowser
├── Stealth      → TLS profiles, canvas/WebGL spoofing, WebRTC isolation
├── Behavior     → Bézier mouse, natural typing, distraction simulation
├── Recovery     → Detects blocks → rotates proxy/session → retries
├── Accounts     → Health scoring, 14-day warming, session checkpointing
├── Proxy        → Residential proxy with rotation and health tracking
└── Workflows    → Record, replay, library (v1.0.0)

Remote Bridge (optional)
└── CDP Proxy    → Connect to local browser from VPS via ngrok
```

## Key Features

| Feature | What It Does |
|---|---|
| **TLS Fingerprinting** | Region-specific profiles (US, Japan, EU, Korea) with JA3/JA4 support |
| **Human Behavior** | Mouse with wobble, typing with mistakes, variable scrolling, fatigue |
| **Auto Recovery** | Detects CAPTCHAs, rate limits, blocks — recovers automatically |
| **Account Warming** | 14-day gradual ramp-up so new accounts don't get flagged |
| **Session Checkpoints** | Export/import browser state for cross-host migration |
| **Platform Presets** | Pre-configured profiles for LinkedIn, Amazon, Cloudflare |
| **Workflow Recorder** | Capture real user actions via CDP → reproducible YAML workflows |
| **Workflow Player** | Execute workflows with fallback selectors, retries, checkpoint resumption |
| **Workflow Library** | Pre-built workflows for Upwork, LinkedIn — usable immediately |
| **Remote Bridge** | Drive a local Windows browser from a VPS via CDP + ngrok |
| **MCP Server** | Integration with AI agents via Model Context Protocol |

## MCP Setup

Use this framework with AI agents (Claude Desktop, Cursor, Windsurf, etc.) via MCP.

### 1. Install the MCP Server

```bash
pip install agentic-stealth-browser
```

### 2. Configure Your MCP Client

**Claude Desktop** — Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "stealth-browser": {
      "command": "python",
      "args": ["-m", "production.mcp_server"],
      "env": {}
    }
  }
}
```

**Cursor / Windsurf** — Add to `.cursorrules` or MCP settings:

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

### 3. Available MCP Tools

| Tool | Description | Added |
|---|---|---|
| `stealth_launch` | Launch browser with stealth + region preset | v0.8 |
| `stealth_navigate` | Navigate with full recovery and human behavior | v0.8 |
| `stealth_load_cookies` | Load cookies from real browser | v0.8 |
| `stealth_set_region` | Switch TLS fingerprint region (US, Japan, EU, Korea) | v0.8 |
| `stealth_scrape` | Navigate and extract page content | v0.8 |
| `stealth_status` | Check browser health and session state | v0.8 |
| `stealth_capabilities` | Show MCP server/runtime version and available tools | v0.9 |
| `stealth_tabs_list` | List open tabs/pages and active tab metadata | v0.9 |
| `stealth_tab_snapshot` | Capture screenshot + metadata for a specific tab/page | v0.9 |
| `stealth_session_timeline` | Fetch replay/timeline events for debugging and recovery analysis | v0.9 |
| `stealth_debug_report` | Return full debug report payload for current session | v0.9 |
| `stealth_close` | Close browser and cleanup | v0.8 |
| `stealth_teach` | Start recording a workflow session (CDP capture → YAML) | v1.0 |
| `stealth_replay` | Execute a saved workflow by name or path | v1.0 |
| `stealth_workflow_list` | List available workflows in the library | v1.0 |
| `stealth_workflow_delete` | Delete a workflow from the library | v1.0 |

> **Operator Guide**: For detailed workflows on observing what the MCP-driven browser is actually doing (tabs, snapshots, timelines, debug reports, security notes, CDP fallbacks), see [docs/MCP_BROWSER_OBSERVABILITY.md](docs/MCP_BROWSER_OBSERVABILITY.md).

### 4. MCP Server Environment Variables

| Variable | Description | Default |
|---|---|---|
| `STEALTH_MCP_ALLOWED_DIRS` | Extra allowed directories for MCP file-access policy (comma/semicolon separated) | _(empty)_ |
| `STEALTH_MCP_SNAPSHOT_DIR` | Snapshot output root for `stealth_tab_snapshot` | `~/.agentic-browser/mcp_snapshots` |
| `STEALTH_MCP_SNAPSHOT_MAX_PER_SESSION` | Max screenshots retained per session directory (older files are pruned) | `20` |
| `STEALTH_MCP_TIMELINE_DEFAULT_LIMIT` | Default event limit when `stealth_session_timeline` is called without `limit` | `30` |
| `STEALTH_MCP_TIMELINE_MAX_LIMIT` | Hard upper bound for `stealth_session_timeline.limit` | `200` |
| `STEALTH_MCP_OBSERVABILITY_MAX_CHARS` | Max serialized response size for observability payloads before truncation | `50000` |

## Configuration

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `STEALTH_REGION` | TLS fingerprint region | `japan` |
| `STEALTH_HEADLESS` | Run browser headless | `true` |
| `STEALTH_PROXY` | Use residential proxy | `false` |

### Platform Presets

```python
await browser.launch(preset="linkedin_2026")   # LinkedIn
await browser.launch(preset="amazon_2026")     # Amazon
await browser.launch(preset="cloudflare")      # Cloudflare-protected sites
```

## Project Structure

```
agentic-stealth-browser/
├── core/           # AgentBrowser main class
├── stealth/        # TLS fingerprinting, script injection, caching
├── behavior/       # Human-like mouse, typing, scrolling, personas
├── recovery/       # Block detection, anti-block orchestrator
├── proxy/          # Proxy management and rotation
├── sessions/       # Session and cookie management
├── workflows/      # Teach/Replay workflow system (v1.0.0)
│   ├── recorder.py          # CDP capture → YAML
│   ├── player.py            # Execute saved workflows
│   ├── schema.py            # Workflow models & validation
│   ├── recovery.py          # Fallback controller
│   ├── variable_resolver.py # {{variable}} resolution
│   ├── selector_generator.py# CSS selector from recorded actions
│   └── library/             # Pre-built workflows (Upwork, LinkedIn)
├── scripts/        # Deployment & ops (RBB setup, health check)
├── audit/          # Structured logging and audit trails
├── ai/             # AI hooks and content analysis
├── production/     # CLI, Docker, MCP server, rate limiting, metrics
├── linkedin/       # LinkedIn-specific actions
├── scraping/       # Safe page scraping utilities
├── docs/           # Architecture Decision Records and guides
└── tests/          # 500+ tests across 25+ files
```

## Documentation

- [Architecture Decision Records](docs/adr/)
- [Operator Setup Guide](docs/OPERATOR_SETUP.md)
- [MCP Browser Observability](docs/MCP_BROWSER_OBSERVABILITY.md)
- [Visual Debugging Guide](docs/VISUAL_DEBUGGING.md)
- [Stealth Limitations](docs/STEALTH_LIMITATIONS.md)
- [Threat Model](docs/THREAT_MODEL.md)
- [Common Pitfalls](docs/COMMON_PITFALLS.md)
- [Rate Limiting & Backoff](docs/RATE_LIMITING_BACKOFF.md)
- [Cookie & Session Resilience](docs/COOKIE_SESSION_RESILIENCE.md)

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting and best practices.

## Responsible Use

This framework is designed for legitimate automation use cases such as:

- Testing your own applications and infrastructure
- Automating workflows on platforms that permit automation
- Research and security analysis
- Accessibility testing

**Important:** Many websites (including LinkedIn, Amazon, and others) prohibit automated access in their Terms of Service. Always:

1. Review the target site's Terms of Service and robots.txt
2. Obtain proper authorization before automating access
3. Respect rate limits and avoid causing harm to services
4. Use this tool responsibly and legally

This project is provided as-is under the MIT License. Users are responsible for complying with applicable laws and terms of service.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License. See [LICENSE](LICENSE) for details.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full release history.
