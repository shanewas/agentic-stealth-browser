# Agentic Stealth Browser

Production-grade, human-mimicking browser automation framework designed for autonomous agents.

## Goals

- Extremely high undetectability (LinkedIn, Upwork, general scraping)
- Deep human behavior simulation
- Isolated named + anonymous sessions
- Reusable across projects

## Current Status (Iteration 1)

- [x] Advanced fingerprint spoofing (WebGL, Canvas, Audio, Permissions, WebRTC)
- [x] Human behavior primitives (mouse, typing, scrolling, thinking)
- [x] Session management (named + anonymous sessions)
- [x] Core `AgentBrowser` class

## Next Iterations

- Behavioral orchestration engine
- Automatic session warming
- Detection evasion testing suite
- Proxy integration layer
- Autonomous decision making

## Usage

```python
from core.agent_browser import AgentBrowser

browser = AgentBrowser(session_name="my-linkedin", anonymous=False)
await browser.launch(headless=True)
await browser.goto("https://www.linkedin.com/in/someone")
await browser.close()
```
