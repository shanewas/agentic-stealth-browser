# Agentic Stealth Browser

Production-grade, human-mimicking browser automation framework for autonomous agents. Built to survive modern anti-bot systems (Cloudflare, LinkedIn, Amazon, Upwork, etc.).

## Features

- **Stealth Layer** — TLS fingerprint profiles (US, Japan, EU, Korea), canvas/WebGL/AudioContext spoofing, WebRTC isolation, JA3/JA4 fingerprinting
- **Human Behavior** — Bézier curve mouse movement, natural typing with pauses/corrections, variable-speed scrolling, distraction simulation, fatigue-aware degradation
- **Anti-Block Recovery** — Automatic detection of CAPTCHAs, rate limits, account restrictions, and proxy blocks with platform-specific recovery strategies
- **Account Management** — Health scoring with automatic cooling off, 14-day warming schedules, session checkpointing for cross-host migration
- **Proxy Support** — Residential proxy integration with health tracking, rotation, and HTTP/SOCKS format support
- **Platform Presets** — Pre-configured profiles for LinkedIn, Amazon, Cloudflare, and more
- **MCP Integration** — Model Context Protocol server for AI agent integration

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
    browser = AgentBrowser(session_name="my-session")
    await browser.launch(headless=True)

    # Navigate with full stealth + automatic recovery
    await browser.safe_goto("https://example.com")

    # Human-like behavior
    await browser.human.scroll_naturally(400)
    await browser.human.think(1500, 2800)

    await browser.close()

asyncio.run(main())
```

## Production Flow

For protected sites (LinkedIn, Upwork, etc.):

```python
from core.agent_browser import AgentBrowser
import asyncio

async def main():
    browser = AgentBrowser(session_name="production")
    await browser.launch(headless=True, preset="linkedin_2026")

    # Load real cookies exported from your browser
    await browser.load_cookies_from_file("cookies.json")

    # Warm up with human-like behavior
    await browser.warm_up_before_work(intensity="heavy")

    # Navigate with built-in recovery
    await browser.safe_goto(
        "https://www.linkedin.com/in/target-profile",
        platform="linkedin"
    )

    await browser.close()

asyncio.run(main())
```

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

## Testing

```bash
# All tests
python -m pytest tests/ -q

# Fast subset
python -m pytest tests/test_stealth_modules.py tests/test_contract_agent_browser.py -q
```

493 tests across 23 test files.

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
└── tests/          # Full test suite
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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License. See [LICENSE](LICENSE) for details.
