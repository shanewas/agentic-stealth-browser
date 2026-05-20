# Agentic Stealth Browser

Production-grade, human-mimicking browser automation framework for autonomous agents. Built to survive modern anti-bot systems (Cloudflare, LinkedIn, Amazon, Upwork, etc.).

**Repository:** https://github.com/shanewas/agentic-stealth-browser

---

## Current Status (May 2026)

**Maturity:** Early-to-Mid Implementation (Foundation + Core Stealth Layer)

This project has a **solid architectural base** but is not yet production-hardened. The main `AgentBrowser` class integrates stealth, human behavior, recovery, proxy, and sessions. Several critical pieces are implemented, while others remain partial or untested at scale.

### What's Working Well

- **Core AgentBrowser** (`core/agent_browser.py`)
  - Persistent context launch with realistic viewport, locale, timezone
  - Full stealth script injection (`advanced_stealth.py`)
  - TLS fingerprint manager wired in
  - Human behavior + orchestration layer attached
  - Recovery orchestrator, scraper, AI hooks, proxy, and session manager initialized

- **Stealth Layer**
  - Region-aware TLS fingerprint profiles (US, Japan, EU, Korea, Global)
  - Advanced stealth script (canvas, WebGL, AudioContext, WebRTC, permissions spoofing)
  - Custom HTTP headers

- **Anti-Block Recovery** (`recovery/anti_block_orchestrator.py`)
  - `AntiBlockOrchestrator` with clear `BlockType` enum (CAPTCHA, soft/hard rate limit, account restriction, proxy block, etc.)
  - `RecoveryContext` dataclass for tracking attempts and metadata

- **Human Behavior** (`behavior/human_behavior.py`)
  - Realistic typing with occasional pauses and corrections
  - Thinking delays (`think()`)

- **Infrastructure**
  - `SessionManager` with anonymous/persistent sessions
  - `ProxyManager` with Decodo sticky session support
  - Basic audit logging and AI hooks

- **MCP Integration**
  - Exposed via `stealth-playwright-mcp` skill for use inside Hermes Agent

### What's Incomplete or Weak

| Area                        | Status          | Notes |
|----------------------------|-----------------|-------|
| **Proxy Execution**        | Partial         | Manager exists but real connection testing + fallback logic is minimal |
| **Recovery Integration**   | Partial         | Orchestrator defined but not deeply wired into `safe_goto()`, clicks, or navigation |
| **Human Behavior Depth**   | Basic           | Typing + think delays present. Missing realistic mouse trajectories, scroll heatmaps, viewport jitter, idle patterns |
| **TLS Fingerprinting**     | Good start      | Launch args + profiles exist. True low-level ClientHello spoofing is limited in stock Playwright |
| **Detection Testing**      | Manual          | Basic test scripts exist. No automated "detection score" runner against live protected sites |
| **Cookie & Login Resilience** | Basic       | Loading works, but battle-tested flows for 2FA bypass / session restoration are missing |
| **Multi-Agent Orchestration** | Early      | SessionManager exists but high-level agent coordination / rotation is thin |
| **Error Handling & Logging** | Moderate     | Audit logger present but not comprehensive across all failure paths |
| **Documentation**          | Minimal         | Only high-level README. No architecture diagram, API reference, or usage examples |

### Overall Assessment

**Strengths:**
- Clean modular architecture (stealth / recovery / behavior / proxy / sessions)
- Good foundation for region-specific fingerprinting
- Recovery model is well thought out on paper

**Risks / Gaps:**
- Many components are initialized but not stress-tested together
- Real-world survival rate against aggressive detectors (especially LinkedIn, Amazon JP, Cloudflare) is unknown
- Human mimicry is still relatively shallow
- Proxy + recovery loop is not yet battle-hardened

---

## Roadmap

### Next Priorities (Iteration 4–5)

1. **Deep Recovery Integration**
   - Wire `AntiBlockOrchestrator` into all navigation and interaction methods
   - Implement exponential backoff + proxy rotation on block detection

2. **Advanced Human Behavior**
   - Realistic mouse movement paths (Bézier curves, natural acceleration)
   - Scroll pattern simulation
   - Idle behavior + micro-movements

3. **Proxy Hardening**
   - Actual connection testing + automatic fallback
   - Residential proxy rotation strategies

4. **Detection Evaluation Suite**
   - Automated tests against real Cloudflare / LinkedIn / Amazon challenges
   - Fingerprinting scorecard (TLS, canvas, WebGL, fonts, etc.)

5. **MCP Tool Polish**
   - Full `stealth_navigate` with recovery
   - Cookie loading from real browser exports
   - Region switching at runtime

6. **Documentation & Examples**
   - Architecture diagram
   - Usage examples for Upwork / LinkedIn scraping
   - Configuration guide

---

## Quick Start (via MCP)

```bash
python3 /root/.hermes/skills/stealth-playwright-mcp/server.py
```

Then use tools:
- `stealth_launch`
- `stealth_navigate`
- `stealth_load_cookies`
- `stealth_set_region`
- `stealth_scrape`

---



## Usage Examples

### Basic Stealth Navigation

```python
from core.agent_browser import AgentBrowser

async def basic_example():
    browser = AgentBrowser(session_name="example")
    await browser.launch(headless=True)
    
    # Navigate with full stealth + recovery
    await browser.safe_goto("https://www.linkedin.com/in/williamhgates", platform="linkedin")
    
    # Human-like behavior
    await browser.human.scroll_naturally(400)
    await browser.human.think(1500, 2800)
    
    await browser.close()
```

### Loading Cookies from Real Browser (Recommended for Upwork/LinkedIn)

```python
async def with_cookies():
    browser = AgentBrowser(session_name="upwork-session")
    await browser.launch(headless=True)
    
    # Load cookies exported from real Edge/Chrome
    await browser.load_cookies_from_file("~/.upwork/cookies.json")
    
    # Warm up the session
    await browser.warm_up_before_work(intensity="medium")
    
    # Now perform actions with fresh cookies + human behavior
    await browser.safe_goto("https://www.upwork.com/nx/search/jobs/", platform="upwork")
    await browser.human.simulate_reading(8.0)
    
    await browser.close()
```

### Region-Specific Fingerprinting

```python
from stealth.tls_fingerprint import get_tls_manager

# Use Japanese TLS fingerprint
tls = get_tls_manager("japan")
tls.log_fingerprint_choice()
```

### Detection Testing

```python
from tests.detection_runner import DetectionTester

tester = DetectionTester()
await tester.run_full_suite()
tester.save_results()
```




## Configuration Reference

### Environment Variables

| Variable              | Description                        | Default     |
|-----------------------|------------------------------------|-------------|
| `STEALTH_REGION`      | TLS fingerprint region             | `japan`     |
| `STEALTH_HEADLESS`    | Run browser in headless mode       | `true`      |
| `STEALTH_PROXY`       | Use residential proxy              | `false`     |

### Recommended Settings

```python
# For maximum stealth (LinkedIn / Upwork)
browser = AgentBrowser(session_name="production")
await browser.launch(headless=True)
await browser.load_cookies_from_file("cookies.json")
await browser.warm_up_before_work("heavy")
await browser.ensure_cookies_fresh(max_age_hours=6)
```


## License

Private repository. All rights reserved.

---

*Last updated: May 2026*