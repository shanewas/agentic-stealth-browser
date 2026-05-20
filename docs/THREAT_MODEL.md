# Security & Threat Model — Agentic Stealth Browser

**Document for operators and security reviewers (addresses #241)**

**Version:** 2026-05 (Phase 8 DX release)
**Audience:** Developers, SREs, and security teams using the library for production agent workloads.

---

## 1. What This Library Defends Against

The agentic-stealth-browser is designed to survive **common commercial anti-bot / anti-automation systems** used by:

- LinkedIn (2026 "unusual activity", security verification, rate limits)
- Amazon (CAPTCHA, robot checks, 403/429)
- Cloudflare (JS challenges, Turnstile, "checking your browser")
- Upwork, Google, and similar high-value targets

### Defenses Implemented

| Layer                  | Technique                                      | Effectiveness |
|------------------------|------------------------------------------------|---------------|
| TLS / Network          | Region-aligned Chrome 124+ fingerprints (ciphers, extensions, curves, sig algos) via launch args | High |
| HTTP Headers           | Realistic Sec-CH-UA, Accept, language, fetch metadata | High |
| JS Environment         | webdriver removal, hardware spoofing, canvas noise, WebGL spoof, AudioContext, chrome.runtime | Medium-High |
| Behavior               | Human-like typing, scrolling, micro-movements, idle, warm-up flows | Medium |
| Recovery               | Intelligent detection + backoff + session/proxy rotation | High (resilience) |
| Sessions/Cookies       | Persistent user_data_dir + real cookie import | Very High |

These close the most common "easy" detection vectors that cause 80%+ of blocks in 2025-2026.

---

## 2. Threat Model — What the Attacker (Website) Can See / Do

**Assumed attacker capabilities (realistic 2026):**

- Full TLS ClientHello inspection (JA3/JA4 style)
- HTTP header + order + value fingerprinting
- JS runtime probing (navigator, canvas, WebGL, Audio, fonts, WebRTC, permissions, etc.)
- Behavioral signals (mouse curves, scroll velocity, typing rhythm, dwell time)
- IP reputation + datacenter / proxy lists + residential rotation detection
- Account-level signals (login patterns, action velocity, graph of viewed profiles)
- Cross-session correlation via cookies, localStorage, indexedDB, canvas seeds
- ML-based "human or not" classifiers trained on millions of sessions

**What we currently defeat well:** Static + low-interaction fingerprinting + basic timing.

**What we do NOT reliably defeat (known limitations):**

- Advanced ML behavioral models that watch long sessions (hours/days)
- 0-day or very new challenge types
- Account graph anomalies (sudden new connections after stealth session)
- Device fingerprinting via WebAuthn, battery API, sensor APIs (partially mitigated)
- Very long-term cookie + local storage correlation without proper session hygiene

---

## 3. Operational Security Recommendations

1. **Never use for TOS-violating activity.** Stealth reduces detection risk but does not make illegal or policy-violating automation legal or safe.
2. **Always use real exported cookies** from the target account's normal browser for LinkedIn/Upwork/etc.
3. **Rotate identities frequently.** One persona should not perform >30-50 high-value actions per day without cooling off.
4. **Combine with residential proxies** that have good reputation (Decodo, etc.). Never rely on the stealth layer alone.
5. **Use the linkedin_2026 (and other) presets** — they encode hard-won operational knowledge.
6. **Monitor with debug + explain tools.** When a block occurs, immediately run `debug_report()` + `explain_blocked()` and adjust (new preset, longer backoff, different proxy).
7. **Run headed=True during development** of new flows so you can see exactly what the site sees.
8. **Keep the library and your Playwright version reasonably up to date.**

---

## 4. Data & Privacy

- The library writes local logs and user_data_dirs under `~/.agentic-browser/`.
- No telemetry or phoning home by default.
- Cookies and session data are only as secure as the host machine.
- Audit logs may contain URLs and error messages — treat them as potentially sensitive.

---

## 5. Reporting Issues

If you discover a new detection vector that bypasses the current stealth + presets, please open a GitHub issue with:
- The exact `debug_report()` output
- The `explain_blocked()` result
- Target URL + platform
- Any public reproduction steps (without sharing private cookies)

This helps the whole community improve the shared presets and patches.

---

**Summary:** Excellent defense-in-depth against 2026 commercial bot detection for short-to-medium sessions. Not a silver bullet for nation-state or long-term persistent surveillance. Use responsibly.

See also: README "Security & Ethics", production docs, and the linked GitHub issues #241, #265, #273.
