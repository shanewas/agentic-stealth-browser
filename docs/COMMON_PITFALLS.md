# Common Pitfalls & Troubleshooting (#83)

This guide covers the most common issues users encounter and how to resolve them.

---

## Navigation Issues

### "Timeout 45000ms exceeded"

**Cause:** The page is slow to load or the site is blocking access.

**Fix:**
```python
# 1. Increase timeout
await browser.page.goto(url, timeout=60000)

# 2. Use domcontentloaded instead of load
await browser.page.goto(url, wait_until="domcontentloaded")

# 3. Try a different region
await browser.launch(region="eu")

# 4. Check if the site is accessible
import httpx
async with httpx.AsyncClient() as client:
    resp = await client.get(url)
    print(f"Status: {resp.status_code}")
```

### Navigation succeeds but page shows CAPTCHA

**Cause:** The site detected automated access.

**Fix:**
```python
# 1. Load fresh cookies
await browser.load_cookies_from_file("cookies.json")

# 2. Use heavy warm-up
await browser.warm_up_before_work("heavy")

# 3. Use platform-specific preset
await browser.launch(preset="linkedin_2026")

# 4. Check debug report
report = await browser.debug_report(print_report=True)
```

---

## Cookie Issues

### Cookies expire quickly

**Cause:** Cookies have a short TTL or the session was flagged.

**Fix:**
```python
# Check cookie health
health = await browser.get_cookie_health()
print(health)

# Refresh cookies if needed
await browser.ensure_cookies_fresh(max_age_hours=4)

# Export fresh cookies from your browser regularly
```

### "No cookie manager initialized"

**Cause:** You're calling cookie methods before loading cookies.

**Fix:**
```python
# Always load cookies first
await browser.load_cookies_from_file("cookies.json")
# Now cookie_manager is initialized
health = await browser.get_cookie_health()
```

---

## Proxy Issues

### Proxy connection fails

**Cause:** Incorrect proxy configuration or proxy is down.

**Fix:**
```python
# Test proxy connection
result = await browser.proxy_manager.test_proxy_connection()
print(result)

# Verify configuration
info = browser.proxy_manager.get_current_proxy_info()
print(info)

# Rotate to a fresh proxy
if browser.proxy_manager.should_rotate_proxy():
    browser.proxy_manager.rotate_proxy(reason="connection_failed")
```

### High block rate with proxy

**Cause:** Proxy IP is flagged or reputation is poor.

**Fix:**
```python
# Check proxy health
health = browser.proxy_manager.get_proxy_health()
print(health)

# Rotate proxy
browser.proxy_manager.rotate_proxy(reason="high_block_rate")

# Use a different tier for sensitive sites
browser.proxy_manager.select_tier("mobile", country="us")
```

---

## Memory Issues

### High memory usage

**Cause:** Too many concurrent browsers or sessions not being cleaned up.

**Fix:**
```python
# 1. Use light mode
browser = AgentBrowser(light_mode=True)

# 2. Use pooled contexts
browser = AgentBrowser(use_pooled_context=True)

# 3. Close browsers promptly
async with AgentBrowser() as browser:
    # ... do work ...
    # Auto-closes on exit

# 4. Prune ephemeral sessions
browser.session_manager.prune_ephemeral(max_age_hours=24)
```

### Memory leak over time

**Cause:** Sessions accumulating on disk.

**Fix:**
```python
# Clean up old sessions
import shutil
from pathlib import Path

sessions_dir = Path.home() / ".agentic-browser" / "sessions"
for session in sessions_dir.iterdir():
    if session.is_dir():
        meta = session / "meta.json"
        if meta.exists():
            import json
            with open(meta) as f:
                m = json.load(f)
            if m.get("compromised"):
                shutil.rmtree(session, ignore_errors=True)
```

---

## Recovery Issues

### Recovery keeps retrying without success

**Cause:** The block is persistent (account restriction, IP ban).

**Fix:**
```python
# 1. Check block type
from recovery.anti_block_orchestrator import BlockType

# 2. Use explain_blocked for diagnosis
from recovery.explain_blocked import explain_why_blocked
explanation = await explain_why_blocked(platform="linkedin", recent_error="...")
print(explanation)

# 3. Clean up compromised session
await browser.cleanup_compromised_session(remove_dir=True)

# 4. Start fresh with new cookies and proxy
```

### Circuit breaker keeps tripping

**Cause:** Too many failures in a short period.

**Fix:**
```python
# Check circuit breaker status
if browser.recovery:
    print(f"Failure counts: {browser.recovery.failure_counts}")
    print(f"Circuit open until: {browser.recovery.circuit_open_until}")

# Reset circuit breaker (use with caution)
browser.recovery._reset_circuit("platform-name")

# Investigate root cause before retrying
```

---

## Human Behavior Issues

### Actions feel too robotic

**Cause:** Realism level is too low or light mode is enabled.

**Fix:**
```python
# Set realism to full
import os
os.environ["AGENTIC_STEALTH_REALISM"] = "full"

# Or disable light mode
browser = AgentBrowser(light_mode=False)

# Use heavy warm-up
await browser.warm_up_before_work("heavy")
```

### Slow performance in CI

**Cause:** Human behavior adds latency.

**Fix:**
```python
# Set light realism for CI
os.environ["AGENTIC_STEALTH_REALISM"] = "light"
os.environ["CI"] = "1"

# Or use light mode
browser = AgentBrowser(light_mode=True)
```

---

## MCP Issues

### "File access denied" error

**Cause:** The file path is outside allowed directories.

**Fix:**
```python
# Allowed directories by default:
# - ~/.agentic-browser/
# - ~/.stealth-browser/

# Move your files to an allowed directory
# Or add a directory to the allowed list (in mcp_security.py)
from mcp_security import default_security_context
default_security_context.file_policy.add_allowed_dir("/path/to/your/dir")
```

### "LLM call not authorized" error

**Cause:** The prompt contains blocked patterns or exceeds rate limits.

**Fix:**
```python
# Check LLM authorization status
from mcp_security import default_security_context
print(default_security_context.llm_policy.max_calls_per_minute)

# Wait for rate limit to reset
import time
time.sleep(60)
```

---

## Getting Help

1. Check the [First Success Checklist](FIRST_SUCCESS_CHECKLIST.md)
2. Review the [Stealth Limitations](STEALTH_LIMITATIONS.md)
3. Search [GitHub Issues](https://github.com/shanewas/agentic-stealth-browser/issues)
4. Open a new issue with:
   - Error message
   - Code snippet
   - Debug report (`await browser.debug_report(print_report=True)`)
   - Health status (`await browser.get_health_status()`)
