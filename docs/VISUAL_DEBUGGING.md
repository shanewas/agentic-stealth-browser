# Visual Debugging & Headed Mode Tutorial

Guide for effectively using headed mode, screenshots, and visual debugging when developing or troubleshooting stealth browser flows.

## Table of Contents

- [Headed Mode Basics](#headed-mode-basics)
- [Headless Server / Xvfb](#headless-server--xvfb)
- [Screenshot Helpers](#screenshot-helpers)
- [Profile Action Debugging](#profile-action-debugging)
- [Visual Debugging Workflow](#visual-debugging-workflow)
- [Common Debugging Scenarios](#common-debugging-scenarios)
- [Performance Tips](#performance-tips)

## Headed Mode Basics

### Enable Headed Mode

Set `HEADLESS=0` or pass `headless=False` to the browser launch:

```python
from core.agent_browser import AgentBrowser

# Via environment
import os
os.environ["HEADLESS"] = "0"

# Or via launch options
browser = AgentBrowser()
await browser.launch(headless=False)
```

### What You'll See

In headed mode, you'll see:
- Real browser window with actual page rendering
- Mouse cursor moving naturally (bezier curves, micro-movements)
- Typing with realistic delays and occasional mistakes
- Scroll animations with backticks (re-read patterns)
- Distraction behaviors (cursor drift, tab hesitation)

### When to Use Headed Mode

- **Development**: Testing new stealth features
- **Debugging**: Understanding why a site detects automation
- **Demo**: Showing realistic browser behavior
- **Troubleshooting**: Visual confirmation of mouse/typing patterns

**Never use headed mode in production** — it's slower, uses more resources, and defeats the purpose of stealth.

## Headless Server / Xvfb

### Running Headed on a Headless Server

Use Xvfb (X Virtual Framebuffer) to run headed mode on servers without displays:

```bash
# Install Xvfb
sudo apt-get install -y xvfb

# Start virtual display
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99

# Run your script
python your_script.py
```

### Docker with Xvfb

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    xvfb \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright browsers
RUN playwright install chromium

# Start Xvfb and run
CMD Xvfb :99 -screen 0 1920x1080x24 & \
    DISPLAY=:99 python your_script.py
```

### Verify Xvfb is Working

```bash
# Take a screenshot to verify
DISPLAY=:99 python -c "
from playwright.async_api import async_playwright
import asyncio

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto('https://example.com')
        await page.screenshot(path='test.png')
        await browser.close()

asyncio.run(test())
"
```

## Screenshot Helpers

### Basic Screenshot

```python
# Full page screenshot
await page.screenshot(path="full_page.png", full_page=True)

# Visible viewport only
await page.screenshot(path="viewport.png")

# Specific element
element = await page.query_selector("button.submit")
await element.screenshot(path="button.png")
```

### Screenshot with Timestamp

```python
import time
from pathlib import Path

DEBUG_DIR = Path("debug_screenshots")
DEBUG_DIR.mkdir(exist_ok=True)

async def debug_screenshot(page, name: str):
    """Take timestamped screenshot for debugging."""
    timestamp = int(time.time())
    path = DEBUG_DIR / f"{timestamp}_{name}.png"
    await page.screenshot(path=str(path), full_page=True)
    print(f"Screenshot saved: {path}")
```

### Screenshot on Detection

```python
async def safe_goto_with_screenshot(browser, url: str):
    """Navigate and screenshot if blocked."""
    try:
        await browser.goto(url)
        content = await browser.page.content()

        # Check for common block indicators
        block_indicators = ["captcha", "challenge", "blocked", "verify"]
        if any(indicator in content.lower() for indicator in block_indicators):
            await debug_screenshot(browser.page, "BLOCKED")
            raise Exception(f"Blocked on {url}")

    except Exception as e:
        await debug_screenshot(browser.page, f"ERROR_{type(e).__name__}")
        raise
```

### Video Recording

```python
# Record video of entire browser session
context = await browser.new_context(
    record_video_dir="videos/",
    record_video_size={"width": 1280, "height": 720}
)
page = await context.new_page()
# ... do stuff ...
await context.close()  # Video saved automatically
```

## Profile Action Debugging

### What is Profile Action?

Profile actions are sequences of browser actions that simulate a specific user behavior pattern. They're used for:
- Account warming
- Session maintenance
- Behavioral consistency

### Debugging Profile Actions

```python
from behavior.persona_rotator import PersonaRotator

rotator = PersonaRotator(account_id="debug_user")
rotator.set_current_persona("casual_user")

# Get current behavior params
params = rotator.get_behavior_params()
print(f"Typing delay: {params['typing_delay_min']}-{params['typing_delay_max']}ms")
print(f"Scroll depth: {params['scroll_pixels']}px")
print(f"Mouse steps: {params['mouse_steps']}")

# Watch trait evolution
print("\nInitial traits:")
print(rotator.get_trait_values())

rotator.evolve(7)  # 7 days
print("\nAfter 7 days:")
print(rotator.get_trait_values())
```

### Logging Profile Actions

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("profile_actions")

async def debug_profile_action(page, action_name: str, **kwargs):
    """Execute and log a profile action."""
    logger.info(f"Starting action: {action_name}")
    logger.debug(f"Parameters: {kwargs}")

    start_time = time.time()
    try:
        # Execute action
        result = await execute_action(page, action_name, **kwargs)
        duration = time.time() - start_time
        logger.info(f"Action {action_name} completed in {duration:.2f}s")
        return result
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Action {action_name} failed after {duration:.2f}s: {e}")
        await debug_screenshot(page, f"action_error_{action_name}")
        raise
```

## Visual Debugging Workflow

### 1. Start with Headed Mode

```bash
HEADLESS=0 python your_script.py
```

Watch the browser interact with the site. Look for:
- Mouse movements that look robotic (straight lines, instant jumps)
- Typing that's too fast or too consistent
- Scroll patterns that don't match human behavior
- Missing or incorrect fingerprints

### 2. Add Strategic Screenshots

```python
# Before critical actions
await debug_screenshot(page, "before_login")

# After navigation
await debug_screenshot(page, "after_navigation")

# On errors
await debug_screenshot(page, "error_state")
```

### 3. Check Detection Results

```bash
python tests/detection_runner.py
cat tests/detection_results_*.json | python -m json.tool
```

### 4. Iterate on Stealth Settings

```python
# Adjust realism level
os.environ["AGENTIC_STEALTH_REALISM"] = "full"  # or "light", "medium", "off"

# Adjust persona
rotator.transition_to("power_user", transition_days=7)
```

### 5. Verify with Detection Tests

Run detection tests after each change to ensure improvements.

## Common Debugging Scenarios

### Scenario 1: Site Detects Automation

**Symptoms**: CAPTCHA, "unusual activity" message, redirect to verification page.

**Debug Steps**:
1. Run in headed mode: `HEADLESS=0 python script.py`
2. Take screenshot on detection
3. Check fingerprint scorecard: `python tests/fingerprint_scorecard.py`
4. Verify stealth scripts are injected: check browser console for errors
5. Compare with known-good persona settings

**Common Fixes**:
- Ensure `webdriver` property is properly spoofed
- Check canvas/WebGL noise is applied
- Verify TLS fingerprint matches browser version
- Add more realistic mouse/typing patterns

### Scenario 2: Mouse Looks Robotic

**Symptoms**: Straight-line movements, instant jumps, no micro-movements.

**Debug Steps**:
1. Watch in headed mode
2. Check `realism_level` setting
3. Verify bezier curve generation

**Fix**:
```python
# Increase realism
os.environ["AGENTIC_STEALTH_REALISM"] = "full"

# Or adjust manually
human.realism_level = 3  # Full realism
```

### Scenario 3: Typing Too Fast

**Symptoms**: Characters appear instantly, no mistakes, consistent rhythm.

**Debug Steps**:
1. Watch typing in headed mode
2. Check persona typing speed

**Fix**:
```python
# Use slower persona
rotator.set_current_persona("casual_user")

# Or adjust directly
params = rotator.get_behavior_params()
print(f"Typing delay: {params['typing_delay_min']}-{params['typing_delay_max']}ms")
```

### Scenario 4: Session Not Persisting

**Symptoms**: Login required every time, cookies lost.

**Debug Steps**:
1. Check cookie storage
2. Verify localStorage persistence
3. Use session checkpoint

**Fix**:
```python
from core.session_checkpoint import SessionManager

manager = SessionManager(data_dir="./sessions")

# Save session
checkpoint = await manager.capture_from_browser(page, account_id="user123")
manager.save_checkpoint(checkpoint)

# Restore session
checkpoint = manager.load_latest("user123")
await manager.restore_to_browser(page, checkpoint)
```

## Performance Tips

### Headed Mode is Slow

- Use `AGENTIC_STEALTH_REALISM=light` for faster headed debugging
- Reduce micro-movement frequency
- Use shorter think delays during development

### Screenshot Overhead

- Only screenshot on errors or key milestones
- Use viewport screenshots instead of full_page when possible
- Compress screenshots if storing many

### Xvfb Memory

- Limit Xvfb screen size to what you need
- Kill Xvfb process when done: `kill $(pgrep Xvfb)`
- Use `xvfb-run` wrapper for automatic cleanup:

```bash
xvfb-run --auto-servernum --server-args="-screen 0 1280x1024x24" python script.py
```

### Video Recording

- Videos are large; only record when needed
- Use smaller resolution: `record_video_size={"width": 640, "height": 480}`
- Delete videos after debugging

## Quick Reference

| Task | Command |
|------|---------|
| Run headed | `HEADLESS=0 python script.py` |
| Run with Xvfb | `xvfb-run python script.py` |
| Screenshot | `await page.screenshot(path="debug.png")` |
| Check detection | `python tests/detection_runner.py` |
| Fingerprint check | `python tests/fingerprint_scorecard.py` |
| Light realism | `AGENTIC_STEALTH_REALISM=light python script.py` |
| Full realism | `AGENTIC_STEALTH_REALISM=full python script.py` |
| Video record | `context = await browser.new_context(record_video_dir="videos/")` |
