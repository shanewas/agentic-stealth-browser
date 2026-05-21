# Using Agentic Stealth Browser as a Library

## Installation

### Install from source (editable / dev mode)

```bash
git clone https://github.com/shanewas/agentic-stealth-browser.git
cd agentic-stealth-browser
pip install -e .
```

### Install with dev dependencies

```bash
pip install -e ".[dev]"
```

This installs `pytest`, `pytest-asyncio`, and `pytest-cov` in addition to the runtime dependencies.

### Install Playwright browsers

After installing the package, you must also install the Playwright browser binaries:

```bash
playwright install chromium
```

## Quick Start

### Basic stealth navigation

```python
import asyncio
from core.agent_browser import AgentBrowser

async def main():
    browser = AgentBrowser(session_name="example")
    await browser.launch(headless=True)

    await browser.safe_goto("https://example.com", platform="generic")

    await browser.human.scroll_naturally(400)
    await browser.human.think(1500, 2800)

    await browser.close()

asyncio.run(main())
```

### Stealth script injection

```python
from stealth.advanced_stealth import get_stealth_script
from stealth.tls_fingerprint import get_tls_manager

script = get_stealth_script()

tls = get_tls_manager("japan")
tls.log_fingerprint_choice()
```

### Region-specific TLS fingerprinting

```python
from stealth.tls_fingerprint import get_tls_manager

tls_us = get_tls_manager("us")
tls_japan = get_tls_manager("japan")
tls_eu = get_tls_manager("eu")
```

### Session management

```python
from core.agent_browser import AgentBrowser

async def with_session():
    browser = AgentBrowser(session_name="linkedin-pro", anonymous=False)
    await browser.launch(headless=True, region="us", preset="linkedin_2026")

    await browser.load_cookies_from_file("~/.linkedin/cookies.json")
    await browser.warm_up_before_work(intensity="heavy")

    success = await browser.safe_goto(
        "https://www.linkedin.com/in/williamhgates",
        platform="linkedin",
    )

    await browser.close()
```

### Audit logging

```python
from audit.logger import AuditLogger

logger = AuditLogger("my-session")
logger.log_action("navigate", {"url": "https://example.com", "status": "ok"})
```

### Human behavior simulation

```python
from behavior.human_behavior import HumanBehavior

async def simulate(browser):
    await browser.human.move_mouse_naturally(500, 300)
    await browser.human.human_click("#search-box")
    await browser.human.type_like_human("#search-box", "agentic stealth browser")
    await browser.human.scroll_naturally(600)
    await browser.human.simulate_reading(8.0)
    await browser.human.random_idle_behavior(3.0)
```

### Recovery and anti-block

```python
from recovery.anti_block_orchestrator import AntiBlockOrchestrator, BlockType

orchestrator = AntiBlockOrchestrator(browser)
result = await orchestrator.handle_block(BlockType.CAPTCHA)
```

### Proxy management

```python
from proxy.proxy_manager import ProxyManager

pm = ProxyManager()
proxy_url = pm.get_proxy_url(region="us")
ok = await pm.test_proxy_connection(proxy_url)
```

## CLI Usage

After installation, the `agentic-stealth-browser` command is available:

```bash
# Health check
agentic-stealth-browser health --preset linkedin_2026 --region us --headless

# Status alias
agentic-stealth-browser status

# List available presets
agentic-stealth-browser list-presets

# Replay audit logs
agentic-stealth-browser replay --session my-session --limit 15
```

## Running Tests

```bash
pip install -e ".[dev]"
pytest
```

With coverage:

```bash
pytest --cov=core --cov=stealth --cov=sessions --cov=behavior --cov=recovery --cov=audit --cov=proxy --cov=production
```