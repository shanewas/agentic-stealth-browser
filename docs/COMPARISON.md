# Comparison with Alternatives (#156)

This document compares the Agentic Stealth Browser with other popular browser automation frameworks.

---

## Quick Comparison Table

| Feature | Agentic Stealth Browser | Browser Use | Playwright Stealth | human-browser | Agent Browser |
|---|---|---|---|---|---|
| **Language** | Python | Python | TypeScript/Python | JavaScript/Python | TypeScript (Rust core) |
| **Anti-detection** | ✅ 8+ layers | ✅ Cloud-based | ✅ Basic | ✅ Residential proxy | ❌ None |
| **Human behavior** | ✅ Advanced (Bézier, fatigue, distractions) | ✅ Basic | ❌ | ❌ | ❌ |
| **Recovery system** | ✅ Full orchestrator with circuit breaker | ✅ Basic retry | ❌ | ❌ | ❌ |
| **TLS fingerprinting** | ✅ Region-aware profiles | ✅ Cloud-managed | ❌ | ❌ | ❌ |
| **MCP support** | ✅ Full | ❌ | ❌ | ❌ | ❌ |
| **Session pooling** | ✅ Shared browser contexts | ❌ | ❌ | ❌ | ✅ |
| **Proxy rotation** | ✅ Smart, tier-aware | ✅ Cloud-managed | Manual | ✅ Residential | ❌ |
| **Cookie management** | ✅ Encrypted, health checks | ✅ Basic | Manual | Manual | Manual |
| **Multi-account** | ✅ Per-instance isolation | ❌ | Manual | Manual | ✅ |
| **Open source** | ✅ MIT | ✅ Apache 2.0 | ✅ MIT | ❌ Commercial | ✅ Apache 2.0 |
| **Self-hosted** | ✅ Full | Partial | ✅ | ❌ Cloud-only | ✅ |

---

## Detailed Comparisons

### vs Browser Use

**Browser Use** is the dominant Python browser automation framework with 13k+ stars. It excels at LLM-driven autonomous navigation.

**Choose Agentic Stealth Browser when:**
- You need self-hosted, full control over the browser
- Anti-detection is critical (LinkedIn, Amazon, Cloudflare)
- You need human-like behavior simulation
- You want MCP integration for AI agents
- You need multi-account isolation

**Choose Browser Use when:**
- You want the largest community and ecosystem
- You need cloud infrastructure (they offer managed browsers)
- You prefer a more mature, battle-tested framework
- You don't need advanced stealth features

### vs Playwright Stealth (playwright-stealth)

**Playwright Stealth** is a lightweight stealth wrapper around Playwright.

**Choose Agentic Stealth Browser when:**
- You need a full recovery system, not just stealth patches
- You need human behavior simulation
- You need proxy management and rotation
- You need session/cookie management
- You need multi-account support

**Choose Playwright Stealth when:**
- You want minimal overhead and simplicity
- You only need basic anti-detection (webdriver flag removal, canvas spoofing)
- You're building a simple scraper, not an agentic system

### vs human-browser

**human-browser** is a commercial service offering residential proxy + stealth Playwright.

**Choose Agentic Stealth Browser when:**
- You want open source and self-hosted
- You don't want to pay per-month fees
- You need full control over the stealth configuration
- You need human behavior simulation

**Choose human-browser when:**
- You want a managed service with zero setup
- You need residential proxies out of the box
- You don't want to maintain infrastructure

### vs Agent Browser (vercel-labs/agent-browser)

**Agent Browser** is a TypeScript/Rust CLI for AI agents with accessibility tree snapshots.

**Choose Agentic Stealth Browser when:**
- You need stealth/anti-detection features
- You need human behavior simulation
- You need Python (not TypeScript)
- You need recovery and proxy management

**Choose Agent Browser when:**
- You want the fastest browser automation CLI
- You need accessibility tree snapshots for AI agents
- You prefer TypeScript/Rust ecosystem
- You don't need stealth features

---

## When to Use Agentic Stealth Browser

### Ideal Use Cases
1. **LinkedIn automation** — Profile scraping, messaging, connection requests
2. **Amazon research** — Product research, price monitoring, review analysis
3. **Upwork/Freelance platforms** — Job searching, proposal submission
4. **Cloudflare-protected sites** — Any site with aggressive bot detection
5. **Multi-account management** — Managing multiple accounts safely
6. **AI agent workflows** — MCP integration for autonomous agents

### Not Ideal For
1. **Simple web scraping** — Use Playwright or BeautifulSoup if no stealth needed
2. **High-speed scraping** — Human behavior adds latency; use faster tools
3. **Mobile app automation** — This is browser-only; use Appium for mobile
4. **Desktop app automation** — Use Playwright Desktop or similar

---

## Performance Comparison

| Metric | Agentic Stealth | Browser Use | Playwright Stealth | Agent Browser |
|---|---|---|---|---|
| Launch time | 2-8s | 3-10s | 1-3s | 0.5-2s |
| Memory per instance | 300-900 MB | 400-1000 MB | 200-500 MB | 100-300 MB |
| Navigation speed | 1-3s | 2-5s | 0.5-2s | 0.3-1s |
| Detection pass rate* | 85-95% | 70-90% | 60-80% | 40-60% |

*Detection pass rate varies by target site and configuration.
