# Show HN: Agentic Stealth Browser

## Title options

**Best:** Show HN: Agentic Stealth Browser – Playwright that survives Cloudflare and LinkedIn

**Alternative:** Show HN: Agentic Stealth Browser – open-source browser automation with TLS fingerprint spoofing + human behavior

---

## First comment (explainer — post this right after submitting)

Hey HN,

I built this because vanilla Playwright's `page.goto()` / `page.click()` gets detected instantly by modern anti-bot systems. They don't just check your User-Agent — they check your TLS handshake (JA3/JA4), WebGL rendering, Canvas buffers, AudioContext, navigator.webdriver, and a dozen other vectors.

Agentic Stealth Browser is an MIT-licensed Python library that survives these checks by looking human at every layer:

**What it does differently:**
• **TLS fingerprint spoofing** — region-specific TLS handshakes (Japan, US, EU, Korea), not Python's standard TLS
• **JavaScript patch injection** — `navigator.webdriver` removed, `plugins` populated, `languages` aligned to region — all before the first paint
• **Human behavior simulation** — Bézier mouse curves, variable typing speed, random micro-adjustments, fatigue patterns
• **Auto-recovery** — detects CAPTCHAs, rate limits, blocks → rotates proxy/session → retries automatically
• **Account warming** — 14-day graduated ramp-up for new accounts on sensitive platforms

**The stack:**
- Async Python 3.10+ with Playwright under the hood
- Built-in MCP server (works with Claude Desktop, Cursor, etc.)
- Operator dashboard for live DevTools + CAPTCHA intervention
- Workflow system — record real browser actions via CDP, replay as YAML
- Orchestrator for scheduling, domain concurrency, retries

**Test results (headless, VPS):**
- bot.sannysoft.com ✓passes all JavaScript checks
- pixelscan.net ✓no automation flags detected
- CreepJS ✓conceals headless fingerprint
- LinkedIn (homepage, feed, company page) ✓loads without blocks

**Install:**
```
pip install agentic-stealth-browser
playwright install --with-deps chromium
```

GitHub: https://github.com/shanewas/agentic-stealth-browser

This is very much a work in progress (v2.1.1, ~880 tests). I'd love feedback on:
- What sites do you need to scrape that you're currently blocked on?
- What's missing from the stealth layer?
- Would you deploy this as a service, or keep it as a library?

Thanks for checking it out!
