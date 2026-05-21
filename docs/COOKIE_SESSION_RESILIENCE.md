# Cookie & Session Resilience Guide (#60)

This guide covers everything you need to know about managing cookies and sessions for maximum resilience.

---

## Overview

Cookies and sessions are the foundation of stealth browser automation. Fresh, healthy cookies dramatically improve success rates on login-protected sites.

---

## Exporting Cookies

### From Chrome/Edge

1. Install the "EditThisCookie" extension
2. Navigate to the target site and log in
3. Click the extension icon → Export
4. Save as `cookies.json`

### From Firefox

1. Install the "Cookie Quick Manager" extension
2. Navigate to the target site and log in
3. Open the extension → Export all cookies
4. Save as `cookies.json`

### Cookie Format

The browser expects cookies in Netscape or JSON format:

```json
[
  {
    "name": "session_id",
    "value": "abc123...",
    "domain": ".linkedin.com",
    "path": "/",
    "secure": true,
    "httpOnly": true,
    "sameSite": "None",
    "expires": 1735689600
  }
]
```

---

## Loading Cookies

### Basic Load

```python
await browser.load_cookies_from_file("cookies.json")
```

### Encrypted Load (Recommended)

```python
# Save with encryption
await browser.save_cookies_to_file(
    "cookies.enc.json",
    encrypt=True,
    encryption_key="my-secret-key"
)

# Load with decryption
await browser.load_cookies_from_file(
    "cookies.enc.json",
    encryption_key="my-secret-key"
)
```

### Key Rotation

```python
# Rotate encryption keys
await browser.load_cookies_from_file(
    "cookies.enc.json",
    encryption_key=["new-key", "old-key"]  # Tries new first, falls back to old
)
```

---

## Cookie Health Checks

### Check Health

```python
health = await browser.get_cookie_health()
print(health)
# Output:
# {
#   "status": "healthy",
#   "count": 45,
#   "oldest_cookie_age_hours": 2.5,
#   "expired_count": 0
# }
```

### Health Status Values

| Status | Meaning | Action |
|---|---|---|
| `healthy` | Cookies are fresh and valid | Continue |
| `aging` | Cookies are getting old (>6 hours) | Plan to refresh soon |
| `expired` | Some cookies have expired | Refresh cookies |
| `no_manager` | Cookie manager not initialized | Load cookies first |
| `compromised` | Session was flagged | Clean up and start fresh |

---

## Session Warm-Up

### Why Warm-Up Matters

Sites flag "cold" sessions that immediately navigate to high-value pages. Warm-up simulates natural browsing behavior before the real work.

### Warm-Up Intensities

```python
# Light: Quick scroll + short think (~1-2 seconds)
await browser.warm_up_before_work("light")

# Medium: Scroll + think + micro-movement + occasional idle (~3-6 seconds)
await browser.warm_up_before_work("medium")

# Heavy: Reading simulation + viewport jitter + fake search + idle (~8-15 seconds)
await browser.warm_up_before_work("heavy")
```

### When to Use Each

| Scenario | Intensity |
|---|---|
| Quick scrape of public page | Light |
| LinkedIn profile view | Medium |
| Amazon product research | Medium |
| Upwork job search | Medium |
| New account / flagged account | Heavy |
| After cookie refresh | Heavy |

---

## Session Cleanup

### Mark Session as Compromised

```python
# After detecting ACCOUNT_RESTRICTION
await browser.cleanup_compromised_session(remove_dir=False)
```

### Full Cleanup

```python
# Remove session entirely
await browser.cleanup_compromised_session(remove_dir=True)
```

### Prune Ephemeral Sessions

```python
# Clean up all ephemeral sessions older than 24 hours
result = browser.session_manager.prune_ephemeral(max_age_hours=24)
print(f"Removed {result['removed']} sessions")
```

---

## Cookie Freshness

### Auto-Refresh

```python
# Check and refresh if cookies are older than 6 hours
await browser.ensure_cookies_fresh(max_age_hours=6)
```

### Manual Refresh

```python
# Save current cookies
await browser.save_cookies_to_file("backup_cookies.json")

# Load fresh cookies from your browser
await browser.load_cookies_from_file("fresh_cookies.json")

# Warm up before work
await browser.warm_up_before_work("heavy")
```

---

## Best Practices

### 1. Always Load Cookies for Login-Protected Sites

```python
# ❌ Bad: Navigate without cookies
await browser.safe_goto("https://linkedin.com/feed")

# ✅ Good: Load cookies first
await browser.load_cookies_from_file("linkedin_cookies.json")
await browser.warm_up_before_work("heavy")
await browser.safe_goto("https://linkedin.com/feed", platform="linkedin")
```

### 2. Use Encrypted Cookie Storage

```python
# Store cookies securely
await browser.save_cookies_to_file(
    "~/.agentic-browser/linkedin/cookies.enc.json",
    encrypt=True,
    encryption_key=os.environ["COOKIE_ENCRYPTION_KEY"]
)
```

### 3. Monitor Cookie Health Regularly

```python
# Check health before each session
health = await browser.get_cookie_health()
if health["status"] in ("expired", "aging"):
    print("Cookies need refreshing!")
    # Load fresh cookies
```

### 4. Clean Up After Blocks

```python
# After a block, clean up the session
if not success:
    await browser.cleanup_compromised_session(remove_dir=True)
    # Start fresh with new cookies
```

### 5. Rotate Cookies Regularly

```python
# For high-frequency automation, rotate cookies every 4-6 hours
MAX_COOKIE_AGE_HOURS = 6
await browser.ensure_cookies_fresh(max_age_hours=MAX_COOKIE_AGE_HOURS)
```

---

## Troubleshooting

### "Invalid cookie format"

**Cause:** Cookie file is not in the expected format.

**Fix:** Ensure cookies are exported as JSON array with required fields (name, value, domain).

### Cookies not persisting

**Cause:** Session is anonymous or ephemeral.

**Fix:** Use `anonymous=False` and don't use `ephemeral=True`:
```python
browser = AgentBrowser(session_name="persistent-session", anonymous=False)
```

### Session flagged after loading cookies

**Cause:** Cookies are stale or from a different fingerprint.

**Fix:**
1. Export fresh cookies
2. Use matching region/TLS profile
3. Use heavy warm-up
4. Check stealth score: `browser.get_stealth_score()`
