# First Success Checklist (#91)

Follow this checklist to get your first successful stealth browser run.

---

## Prerequisites

- [ ] Python 3.11+ installed
- [ ] Playwright installed: `pip install playwright && playwright install chromium`
- [ ] (Optional) Proxy credentials if using residential proxies

---

## Step 1: Install

```bash
pip install -e .
```

Or clone and install:

```bash
git clone https://github.com/shanewas/agentic-stealth-browser.git
cd agentic-stealth-browser
pip install -e .
```

---

## Step 2: Quick Smoke Test

```python
import asyncio
from core.agent_browser import AgentBrowser

async def test():
    async with AgentBrowser(session_name="first-test", anonymous=True) as browser:
        await browser.launch(headless=True, region="us")
        success = await browser.safe_goto("https://example.com")
        print(f"Navigation success: {success}")
        title = await browser.page.title()
        print(f"Page title: {title}")

asyncio.run(test())
```

Expected output:
```
Navigation success: True
Page title: Example Domain
```

---

## Step 3: Verify Stealth

```python
async def check_stealth():
    async with AgentBrowser(session_name="stealth-check") as browser:
        await browser.launch(headless=True, debug=True, region="us")
        await browser.safe_goto("https://bot.sannysoft.com")
        
        # Get debug report
        report = await browser.debug_report()
        print(f"TLS Profile: {report['report']['tls_fingerprint']['name']}")
        print(f"Stealth patches: {report['report']['patch_count']}")
        
        # Check for webdriver flag
        is_webdriver = await browser.page.evaluate("navigator.webdriver")
        print(f"webdriver flag: {is_webdriver}")  # Should be False

asyncio.run(check_stealth())
```

---

## Step 4: Test with Cookies (For Login-Protected Sites)

1. Export cookies from your real browser (use a browser extension like "EditThisCookie")
2. Save as `cookies.json`
3. Load them:

```python
async def with_cookies():
    async with AgentBrowser(session_name="cookie-test") as browser:
        await browser.launch(headless=True, region="us")
        
        # Load cookies
        result = await browser.load_cookies_from_file("cookies.json")
        print(f"Cookies loaded: {result['status']}")
        
        # Warm up
        await browser.warm_up_before_work("medium")
        
        # Navigate
        await browser.safe_goto("https://linkedin.com", platform="linkedin")
        print(f"Current URL: {browser.page.url}")

asyncio.run(with_cookies())
```

---

## Step 5: Verify No Blocks

```python
async def check_health():
    async with AgentBrowser(session_name="health-check") as browser:
        await browser.launch(headless=True, preset="linkedin_2026")
        await browser.load_cookies_from_file("linkedin_cookies.json")
        await browser.warm_up_before_work("medium")
        await browser.safe_goto("https://linkedin.com/feed", platform="linkedin")
        
        health = await browser.get_health_status()
        print(f"Block rate: {health['block_rate_pct']}%")
        print(f"Account state: {health['account_state']}")
        print(f"Stealth score: {health['stealth_score']['config_hint']}")

asyncio.run(check_health())
```

---

## Troubleshooting

### "Browser not launched" error
- Make sure you call `await browser.launch()` before any browser actions
- Or use `async with AgentBrowser() as browser:` for automatic launch

### Navigation fails with timeout
- Try a different region: `region="eu"` or `region="japan"`
- Check your internet connection
- If using a proxy, verify credentials

### Getting blocked/CAPTCHA
- Load fresh cookies from your real browser
- Use `warm_up_before_work("heavy")` before navigating
- Try a different preset: `preset="linkedin_2026"`
- Check the debug report: `await browser.debug_report(print_report=True)`

### High memory usage
- Use `light_mode=True` for lower memory footprint
- Use `use_pooled_context=True` to share a browser process
- Close browsers promptly with `await browser.close()`

---

## Next Steps

- Read the [README](../README.md) for full API documentation
- Check out [Platform Recipes](../README.md#platform-recipes--cookbook-p1-189) for LinkedIn, Upwork, Amazon
- See [Common Pitfalls & Troubleshooting](COMMON_PITFALLS.md) for known issues
- Join discussions on GitHub Issues
