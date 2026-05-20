# Agentic Stealth Browser — Improvement Tasks

**Goal:** Turn the current solid foundation into a production-grade, hard-to-detect browser automation system suitable for real autonomous agents.

**Last Updated:** May 20, 2026

---

## Phase 1: Core Robustness (Highest Priority)

### 1.1 Recovery Integration
- [ ] Wire `AntiBlockOrchestrator` into `AgentBrowser`
  - Create `safe_goto(url, platform)` method that uses recovery logic
  - Create `safe_click(selector)` and `safe_type(selector, text)` wrappers
  - Implement automatic retry + backoff on detected blocks
- [ ] Add platform-specific recovery strategies (LinkedIn vs Amazon vs Cloudflare)
- [ ] Log every recovery attempt with context (block type, attempt count, proxy used)

### 1.2 Proxy Hardening
- [ ] Implement real proxy connection testing in `ProxyManager`
- [ ] Add automatic proxy fallback / rotation when a proxy fails or gets blocked
- [ ] Support multiple proxy providers (Decodo + self-hosted residential)
- [ ] Add proxy health monitoring (latency, success rate)

### 1.3 Error Handling & Logging
- [ ] Create centralized error taxonomy for browser actions
- [ ] Improve `AuditLogger` to capture full context on every navigation/action
- [ ] Add structured logging (JSON) for easier analysis
- [ ] Implement graceful degradation (continue with reduced stealth if one layer fails)

---

## Phase 2: Human Mimicry (Critical for Detection Evasion)

### 2.1 Advanced Mouse Behavior
- [ ] Implement realistic mouse movement using Bézier curves + natural acceleration
- [ ] Add random micro-movements and idle behavior
- [ ] Create `human_move_to(x, y)` and `human_click()` methods

### 2.2 Scroll & Viewport Patterns
- [ ] Simulate natural scrolling (variable speed, pauses, direction changes)
- [ ] Add viewport size jitter and occasional resizing
- [ ] Implement reading simulation (scroll + pause patterns)

### 2.3 Typing & Interaction Polish
- [ ] Expand `type_like_human()` with variable speed, backspacing, and thinking pauses
- [ ] Add occasional "fat finger" corrections
- [ ] Create `human_scroll_to_element()` helper

---

## Phase 3: Detection Testing & Evaluation

### 3.1 Automated Detection Test Suite
- [ ] Build a test runner that visits real protected sites:
  - Cloudflare challenge pages
  - LinkedIn profile/login
  - Amazon JP product pages
  - Upwork job search
- [ ] Create fingerprinting scorecard (TLS, canvas, WebGL, fonts, audio, WebRTC)
- [ ] Measure detection rate before/after each stealth improvement

### 3.2 Continuous Evaluation
- [ ] Add nightly detection tests (cron or GitHub Action)
- [ ] Store historical detection scores
- [ ] Alert when stealth effectiveness drops

---

## Phase 4: Cookie & Session Resilience

### 4.1 Cookie Management
- [ ] Improve `load_cookies()` to handle encrypted/expired cookies gracefully
- [ ] Add automatic cookie refresh logic when sessions expire
- [ ] Support exporting cookies back to real browser format

### 4.2 Multi-Session Orchestration
- [ ] Build higher-level `AgentOrchestrator` that manages multiple `AgentBrowser` instances
- [ ] Add session rotation and warm-up strategies
- [ ] Implement shared proxy pool with usage tracking

---

## Phase 5: Documentation & Usability

### 5.1 Documentation
- [ ] Create architecture diagram (Mermaid or Excalidraw)
- [ ] Write detailed API reference for `AgentBrowser` and key modules
- [ ] Add usage examples:
  - LinkedIn profile scraping
  - Amazon product monitoring
  - Upwork proposal automation
- [ ] Document all environment variables and configuration options

### 5.2 MCP Skill Polish
- [ ] Ensure all tools in `stealth-playwright-mcp` have proper error handling and return values
- [ ] Add `stealth_screenshot()` and visual debugging tools
- [ ] Document how to use the MCP server from Hermes

---

## Phase 6: Production Hardening (Later)

- [ ] Add metrics / observability (Prometheus compatible)
- [ ] Implement rate limiting per domain / account
- [ ] **Headed vs Headless + visual debugging**
  - Toggle between headless and headed mode at runtime
  - Automatic screenshots on error / block detection
  - Visual debugging overlay (mouse path, click highlights)
  - Headed fallback when recovery is triggered
- [ ] Create Docker image for easy deployment
- [ ] **Performance profiling and optimization**
  - Profile navigation, typing, and recovery latency
  - Identify bottlenecks in stealth injection and human behavior
  - Optimize Playwright launch args and script injection
  - Add timing metrics for safe_goto, safe_click, warm_up
---

## Quick Wins (Can be done in 1–2 days)

1. Wire basic `safe_goto()` with recovery in `AgentBrowser`
2. Add realistic mouse movement using simple Bézier curves
3. Create a minimal detection test script against Cloudflare
4. Improve README with usage examples
5. Add proxy health check method

---

## Suggested Order

**Week 1–2:** Phase 1 (Recovery + Proxy) — biggest impact on reliability  
**Week 3:** Phase 2 (Human Behavior) — biggest impact on detection  
**Week 4:** Phase 3 (Detection Testing) — validate improvements  
**Ongoing:** Documentation and MCP improvements

---

**Next Step:** Pick the first task from Phase 1 and start implementing.