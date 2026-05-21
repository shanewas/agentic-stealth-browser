# Changelog

All notable changes to the Agentic Stealth Browser will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — Phase 8 DX & Debug Release (2026-05)

### Added — High-Value DX Features (closes #265, #273, #288, #281, #257, #297, #241 and many documentation issues)

- **Debug Mode (#265)**: `AgentBrowser(launch(debug=True))` now produces exact, machine-readable + human-pretty dumps of:
  - TLS fingerprint (full ciphers, extensions, curves, signature algorithms, launch args)
  - Exact HTTP headers sent to Playwright
  - All stealth JS patches applied
  - Full `debug_report(print_report=True)` and `stealth_debug_report()` in MCP
  - Structured debug JSONL logs alongside normal audit trails (`AuditLogger` + `DebugReporter`)

- **"Explain Why Blocked" Analyzer (#273)**: New `explain_why_blocked()` + orchestrator integration + MCP `stealth_explain_blocked()`.
  - Returns clear English explanation, root cause hypothesis, and **prioritized, copy-paste actionable recommendations**.
  - LinkedIn/Amazon/Cloudflare-specific advice.
  - Perfect companion to debug dumps when you hit a wall.

- **Platform Presets for 2026 (#288)**: `stealth/presets.py` + first-class support in `launch(preset=...)` and `apply_preset()`.
  - `linkedin_2026` (P1 target): US TLS, heavy behavior, heavy warm-up, 6 retries, professional persona notes.
  - `amazon_2026`, `upwork_2026`, `cloudflare_generic`, `general_high_stealth`.
  - `stealth_list_presets()`, `stealth_apply_preset("linkedin_2026")`, MCP exposure.
  - `build_launch_config_from_preset` for easy extension.

- **Status / Health Command (#281)**: `get_health_status()`, enhanced `stealth_status()`, `stealth_health()`.
  - Launched state, current preset, TLS profile, recent blocks, cookie health, current URL, recovery stats.
  - Immediately useful for operators, dashboards, and MCP consumers.

- **Quick-Start Notebook (#257)**: `examples/quick_start.ipynb` (created) with runnable cells covering:
  - Basic launch, safe_goto, warm-up
  - Debug mode + full fingerprint dump
  - LinkedIn 2026 preset end-to-end
  - explain_blocked + health checks
  - MCP usage patterns

- **Changelog & Release Notes Experience (#297)**: This `CHANGELOG.md` + docs/THREAT_MODEL.md + improved README sections.
  - Clear "Unreleased" section linking to closed issues.
  - Future releases will follow the same format.

- **Security / Threat Model Documentation (#241)**: `docs/THREAT_MODEL.md`
  - What the library actually defends against vs. limitations
  - Operational security best practices for 2026
  - Responsible use guidance

### Changed / Improved
- `AgentBrowser.launch()` now accepts `debug`, `preset`, `region` — fully backwards compatible.
- MCP tools (`stealth-playwright-mcp/mcp_tools.py` + `stealth_mcp.py`) expose all new DX capabilities.
- `AuditLogger` extended with `enable_debug_mode()`, `log_debug_dump()`, `DebugReporter` class.
- Recovery orchestrator now produces richer logs when blocks occur.
- README updated with "Quick Start", "Debugging & Diagnostics", "Platform Presets 2026", "Health & Status", "MCP DX Tools".

### Documentation
- Many [documentation] and [DX] issues addressed via the above + inline docstrings, preset notes, and threat model.

---

## [0.2.0] — 2026-05 (Phase 7 Reliability)

- Core context manager (`async with AgentBrowser()`) — #292
- Major bug fixes (BUG-01..05): rng, Page vs Context, page_getter for detection, rate limiter correctness
- Recovery integration improvements
- Test coverage for critical paths (`tests/test_phase7_fixes.py`)

---

## [0.1.0] — Initial Public Foundation (2026-05)

- First release of modular stealth + recovery + human behavior + TLS fingerprinting architecture.
- Basic AgentBrowser, AuditLogger, presets groundwork, MCP skill skeleton.

---

[Unreleased]: https://github.com/shanewas/agentic-stealth-browser/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/shanewas/agentic-stealth-browser/releases/tag/v0.2.0
[0.1.0]: https://github.com/shanewas/agentic-stealth-browser/releases/tag/v0.1.0
