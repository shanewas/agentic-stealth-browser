# Agentic Stealth Browser

[![CI](https://github.com/shanewas/agentic-stealth-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/shanewas/agentic-stealth-browser/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-493%20passing-brightgreen)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A565%25-green)](https://github.com/shanewas/agentic-stealth-browser/actions/workflows/ci.yml)

A Python framework that makes browser automation look human. Built for autonomous agents that need to navigate websites protected by Cloudflare, LinkedIn, Amazon, and other anti-bot systems.

## Why This Exists

Standard browser automation (`page.goto()`, `page.click()`) gets detected instantly. This framework solves that by combining:

- **TLS fingerprint spoofing** — matches real browser TLS handshakes
- **Human behavior simulation** — natural mouse, typing, scrolling with realistic imperfections
- **Automatic recovery** — detects blocks (CAPTCHAs, rate limits) and recovers without crashing
- **Account lifecycle management** — warming, health scoring, cooling off

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

## How It Works

```
AgentBrowser
├── Stealth      → TLS profiles, canvas/WebGL spoofing, WebRTC isolation
├── Behavior     → Bézier mouse, natural typing, distraction simulation
├── Recovery     → Detects blocks → rotates proxy/session → retries
├── Accounts     → Health scoring, 14-day warming, session checkpointing
└── Proxy        → Residential proxy with rotation and health tracking
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

| Tool | Description |
|---|---|
| `stealth_launch` | Launch browser with stealth + region preset |
| `stealth_navigate` | Navigate with full recovery and human behavior |
| `stealth_load_cookies` | Load cookies from real browser |
| `stealth_set_region` | Switch TLS fingerprint region (US, Japan, EU, Korea) |
| `stealth_scrape` | Navigate and extract page content |
| `stealth_status` | Check browser health and session state |
| `stealth_close` | Close browser and cleanup |

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
├── audit/          # Structured logging and audit trails
├── ai/             # AI hooks and content analysis
├── production/     # CLI, Docker, rate limiting, metrics
├── linkedin/       # LinkedIn-specific actions
├── scraping/       # Safe page scraping utilities
├── docs/           # Architecture Decision Records and guides
└── tests/          # 493 tests across 23 files
```

## Documentation

- [Architecture Decision Records](docs/adr/)
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
