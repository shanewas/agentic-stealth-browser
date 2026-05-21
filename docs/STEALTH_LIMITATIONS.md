# Stealth Limitations & Honest Assessment (#86)

This document provides an honest assessment of what the Agentic Stealth Browser can and cannot do. Understanding these limitations is critical for setting realistic expectations and avoiding account blocks.

---

## What We Do Well

### ✅ Strong Points
1. **Human behavior simulation** — Bézier curve mouse movements, realistic typing with mistakes, scroll patterns, idle behavior, fatigue modeling
2. **Recovery system** — Full anti-block orchestrator with circuit breaker, platform-specific strategies, history learning, proxy/session rotation
3. **TLS fingerprint profiles** — Region-aware profiles (US, EU, Japan, Korea, Global) with realistic cipher suites and extensions
4. **Canvas/WebGL/Audio spoofing** — Seeded, per-session unique fingerprints that defeat common detection scripts
5. **WebRTC protection** — Prevents local IP leaks via ICE candidate mangling
6. **Session management** — Isolated sessions, encrypted cookies, health checks, automatic cleanup on compromise
7. **MCP integration** — Full Model Context Protocol support for AI agent workflows
8. **Proxy management** — Tier-aware selection, health tracking, smart rotation based on site sensitivity

---

## Known Limitations

### ⚠️ Partial Coverage

1. **TLS ClientHello spoofing**
   - **What we do:** Region-aligned cipher/extension profiles + launch args
   - **What we can't do:** Bit-perfect wire-level ClientHello byte manipulation in stock Playwright
   - **Workaround:** Layer uTLS (Go) + custom proxy or patched Chromium builds for true wire-level spoofing

2. **Font fingerprinting**
   - **What we do:** Patched `measureText` with jitter, realistic font list
   - **What we can't do:** Full `document.fonts` replacement (too risky, side effects)
   - **Impact:** Sophisticated font fingerprinting may still detect anomalies

3. **Browser automation signals**
   - **What we do:** Remove `navigator.webdriver`, spoof Chrome runtime, plugins, permissions
   - **What we can't do:** Remove all automation signals that newer Chromium versions may introduce
   - **Mitigation:** Monitor Playwright/Chromium updates; review issue #279

4. **Human behavior depth**
   - **What we do:** Mouse, typing, scroll, idle, distractions, fatigue, terms reading
   - **What we can't do:** Full eye-tracking simulation, realistic tab-switching patterns, variable reading speeds based on content complexity
   - **Impact:** Very sophisticated behavioral analysis may still detect patterns

### ❌ Not Covered

1. **CAPTCHA solving** — We detect CAPTCHAs but don't solve them. Use external CAPTCHA solving services.
2. **Fingerprint consistency across restarts** — Each launch generates new fingerprints. For persistent fingerprints, use the same `fingerprint_seed`.
3. **Mobile browser emulation** — We simulate desktop Chrome only. Mobile fingerprinting requires different profiles.
4. **Extension fingerprinting** — We don't spoof Chrome extension lists. Sites checking for specific extensions may detect absence.
5. **Hardware-level fingerprinting** — We can't spoof GPU renderer strings beyond what Chromium reports.
6. **Network-level fingerprinting** — TCP/IP stack fingerprinting (p0f-style) is outside our scope.

---

## Detection Pass Rates (Estimated)

| Site | Pass Rate | Notes |
|---|---|---|
| Cloudflare (standard) | 85-95% | Higher with cookies + warm-up |
| Cloudflare (under attack) | 60-80% | May require manual CAPTCHA solve |
| LinkedIn | 70-90% | Requires fresh cookies + heavy warm-up |
| Amazon | 75-90% | Residential proxy recommended |
| Upwork | 80-95% | Cookies + medium warm-up sufficient |
| Google | 60-80% | Aggressive detection, frequent updates |
| DataDome | 70-85% | Varies by site implementation |
| PerimeterX | 65-80% | Requires residential proxy |

**These are estimates, not guarantees.** Actual pass rates depend on:
- Cookie freshness and quality
- Proxy reputation and type
- Region alignment (TLS profile matches proxy location)
- Warm-up intensity
- Human behavior realism settings
- Target site's current detection rules

---

## Honest Recommendations

### When to Use This Tool
- You need **self-hosted** browser automation with anti-detection
- You're targeting **moderately protected** sites (LinkedIn, Amazon, Upwork)
- You need **multi-account** isolation
- You want **human-like behavior** for AI agent workflows
- You're comfortable with **Python** and **Playwright**

### When to Look Elsewhere
- You need **100% undetectable** automation (no tool can guarantee this)
- You're targeting **heavily protected** sites (banking, government)
- You need **mobile browser** emulation
- You want a **managed service** (use Browser Use Cloud or human-browser)
- You need **high-speed** scraping (human behavior adds latency)

### Best Practices for Maximum Success
1. **Always use fresh cookies** from a real browser profile
2. **Always warm up** before navigating to high-value targets
3. **Use region-aligned** TLS profiles matching your proxy location
4. **Rotate proxies** per account; never share across high-risk accounts
5. **Monitor block rates** and adjust behavior accordingly
6. **Use `safe_goto`** instead of raw `page.goto` for automatic recovery
7. **Keep the library updated** — anti-detection is an arms race

---

## Security Disclaimer

This tool is designed for legitimate automation use cases. Using it to:
- Violate terms of service
- Access accounts you don't own
- Conduct fraudulent activities
- Harass or spam users

...is both unethical and potentially illegal. Use responsibly.
