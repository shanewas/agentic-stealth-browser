# Rate Limiting & Backoff Strategy Reference (#65)

This document explains the rate limiting and backoff strategies available in the Agentic Stealth Browser.

---

## Overview

The browser has two layers of rate limiting:

1. **Account-level rate limiting** — Prevents too many requests per account/domain
2. **Tool-level rate limiting** — Limits MCP tool calls per minute

---

## Account-Level Rate Limiting

### Default Configuration

```python
from production.rate_limiter import AccountRateLimiter, DomainRateLimiter

# Default limits
limiter = AccountRateLimiter()
limiter.set_limit("linkedin.com", requests_per_minute=8, cooldown_seconds=60)
limiter.set_limit("amazon.com", requests_per_minute=10, cooldown_seconds=45)
limiter.set_limit("default", requests_per_minute=15, cooldown_seconds=30)
```

### Per-Instance Rate Limiting

```python
from core.agent_browser import AgentBrowser

# Each browser gets its own rate limiter by default
browser = AgentBrowser(session_name="my-session")

# Or share a limiter across multiple browsers for coordinated rate limiting
shared_limiter = AccountRateLimiter()
browser1 = AgentBrowser(session_name="account-1", rate_limiter=shared_limiter)
browser2 = AgentBrowser(session_name="account-2", rate_limiter=shared_limiter)
```

### Custom Rate Limits

```python
# Set custom limits for a domain
browser.set_rate_limit(
    domain="example.com",
    requests_per_minute=5,
    cooldown_seconds=120,
    account="my-account"
)
```

### Rate Limiting with safe_goto

```python
# safe_goto_with_rate_limit automatically respects rate limits
result = await browser.safe_goto_with_rate_limit(
    url="https://example.com/page",
    domain="example.com",
    account="my-account"
)
```

---

## Tool-Level Rate Limiting

### Configuration

```python
from core.agent_browser import AgentBrowser

# Limit MCP tool calls
browser = AgentBrowser(
    session_name="mcp-session",
    rate_limits={
        "tool_calls_per_minute": 30,
        "total_calls_cap": 600,
    }
)
```

### Affected Methods

The following methods respect tool-level rate limits:
- `goto()`
- `safe_goto()`
- `safe_click()`
- `safe_type()`
- `screenshot_on_error()`
- `safe_goto_with_rate_limit()`

---

## Backoff Strategies

### Recovery Backoff

The `AntiBlockOrchestrator` uses exponential backoff with jitter:

```python
# Platform-specific backoff settings
PLATFORM_STRATEGIES = {
    "linkedin": {
        "base_backoff": 45,      # seconds
        "max_backoff": 300,      # 5 minutes
        "jitter": 0.3,           # ±30% randomization
    },
    "amazon": {
        "base_backoff": 30,
        "max_backoff": 180,
        "jitter": 0.4,
    },
    "google": {
        "base_backoff": 20,
        "max_backoff": 120,
        "jitter": 0.35,
    },
    "default": {
        "base_backoff": 25,
        "max_backoff": 180,
        "jitter": 0.3,
    },
}
```

### Backoff Calculation

```
backoff = min(base * 2^(attempt-1), max_backoff) * multiplier
jitter = backoff * jitter_range * random(-1, 1)
final_backoff = max(3.0, backoff + jitter)
```

### Transient Error Backoff

For transient errors (timeouts, DNS failures), backoff is reduced:

```python
# Transient errors use a lower multiplier
transient_backoff_multiplier = 0.5  # to 0.8 depending on platform
```

---

## Circuit Breaker

The circuit breaker prevents hammering a site that's consistently failing:

```python
# Configuration
circuit_breaker_threshold = 5  # failures before opening
circuit_cooldown = 300         # 5 minutes cooldown

# Check if circuit is open
if orchestrator._check_circuit_breaker("linkedin"):
    print("Circuit is open, waiting for cooldown")

# Reset circuit (use with caution)
orchestrator._reset_circuit("linkedin")
```

---

## Best Practices

### 1. Start Conservative

```python
# Start with low limits and increase gradually
browser.set_rate_limit("linkedin.com", requests_per_minute=5, cooldown_seconds=120)
```

### 2. Monitor Block Rate

```python
health = await browser.get_health_status()
if health["block_rate_pct"] > 10:
    # Reduce rate limits
    browser.set_rate_limit("linkedin.com", requests_per_minute=3, cooldown_seconds=180)
```

### 3. Use Platform-Specific Limits

```python
# LinkedIn is more sensitive
browser.set_rate_limit("linkedin.com", requests_per_minute=5, cooldown_seconds=120)

# Amazon is moderate
browser.set_rate_limit("amazon.com", requests_per_minute=8, cooldown_seconds=60)

# Generic sites can handle more
browser.set_rate_limit("example.com", requests_per_minute=15, cooldown_seconds=30)
```

### 4. Coordinate Multiple Accounts

```python
# Share a rate limiter across accounts to prevent aggregate overloading
shared_limiter = AccountRateLimiter()
browsers = [
    AgentBrowser(session_name=f"account-{i}", rate_limiter=shared_limiter)
    for i in range(5)
]
```

### 5. Handle Rate Limit Errors

```python
from core.agent_browser import RateLimitError

try:
    await browser.safe_goto_with_rate_limit(url, domain="example.com")
except RateLimitError as e:
    print(f"Rate limited, waiting: {e}")
    await asyncio.sleep(60)
```

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `STEALTH_RATE_LIMIT_RPM` | Default requests per minute | 15 |
| `STEALTH_RATE_LIMIT_COOLDOWN` | Default cooldown seconds | 30 |
| `STEALTH_CIRCUIT_THRESHOLD` | Failures before circuit opens | 5 |
| `STEALTH_CIRCUIT_COOLDOWN` | Circuit cooldown seconds | 300 |
