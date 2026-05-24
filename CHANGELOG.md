# Changelog

All notable changes to the Agentic Stealth Browser will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.0] — Reliability, CI, and Backlog Convergence (2026-05-25)

### Added
- **Unit test expansion** (#6): 6 new test files with 180+ tests covering rate limiter, cookie health, recovery state machine, proxy config, workflow schema, and metrics collector.
- **CI pipeline** (#21): `.github/workflows/ci.yml` with ruff lint, pytest coverage (45% gate), Docker build smoke, and nightly detection regression.
- **Production deployment docs** (`docs/DEPLOYMENT.md`): Docker deployment guide with volume mounts, health checks, and operator runbook.
- **Upgrade notes** (`docs/UPGRADE-v1.1.md`): v1.0→v1.1 migration guide.
- **Docker healthcheck**: Stdio-based healthcheck script verifying core imports (MCP server is stdio-only, not HTTP).
- **MCP server health endpoint**: JSON-RPC method `"health"` returning server status, version, and active session count.
- **`.dockerignore`**: Excludes tests, docs, CI files, and dev artifacts from Docker builds.

### Fixed
- **Backoff jitter clamping** (`recovery/anti_block_orchestrator.py`): Jitter could push backoff above `max_backoff`. Now clamped with `min(max_backoff, backoff + jitter)`.
- **Cookie health naive date comparison** (`sessions/cookie_manager.py`): `datetime.fromtimestamp()` without `tz=timezone.utc` created naive datetimes that broke expiry comparison vs timezone-aware `now`.
- **Docker healthcheck HTTP dead code**: Removed non-functional HTTP health check — MCP server uses stdio JSON-RPC, not HTTP.

### Changed
- **Dockerfile**: Non-root user (`appuser`), HEALTHCHECK directive, proper MCP server ENTRYPOINT, volume mounts for sessions/logs/screenshots/cookies, `workflows/` COPY.
- **Stale PRs closed**: 10 feature branches from v0.9 development cycle closed (content already in v1.0.0).

---

## [1.0.1] — Security & Cleanup Patch (2026-05-25)

### Fixed
- **Security: mcp_security redaction regex now actually redacts** (#420): All 8 `SENSITIVE_PATTERNS` regexes had inverted group capture — group 1 captured the secret value, so replacements output `actual_value=[REDACTED_*]` instead of `[REDACTED_*]`. Fixed by capturing the key/prefix in group 1 instead of the value.
- **Security: JS injection in Workflow Player and Recovery** (#421): All `_evaluate()` calls in `workflows/player.py` (13 sites) and `workflows/recovery.py` (3 sites) now use `json.dumps()` instead of bare f-string interpolation for selectors, URLs, and user-controlled values.
- **Bug: Wrong timeout recovery action for verify/wait_for_element** (#422): `_handle_timeout_error` in `workflows/recovery.py` was dispatching `safe_type()` for non-input step types when the browser had `safe_type` available. Now correctly gates `safe_type` to `fill`/`type` steps only and falls through to sleep for `verify`/`wait_for_element`.
- **Workflow library: Upwork profile URL parameterized** (#423): Three Upwork workflow YAMLs (add-portfolio-item, edit-title, update-rate) now use `{{profile_url}}` variable instead of hardcoded URL.
- **Removed empty apply.yaml stub** (#424): Deleted the unimplemented `workflows/library/upwork/apply.yaml`.
- **Removed low-precision SSN detection from recorder** (#425): `_VARIABLE_PATTERNS` in `workflows/recorder.py` no longer contains the heuristic SSN matching pattern that caused false positives.

---

## [1.0.0] — Workflow Teach/Replay + Remote Bridge (2026-05-23)

### Added — Workflow System (M0–M5)
- **Workflow Schema + Validator** (#389): Dataclass models for all 13 step types (navigate, click, fill, type, select, verify, wait, wait_for_element, scroll, screenshot, execute_js, conditional, run_workflow) with required/optional field validation.
- **Variable Resolver** (#389): `{{variable}}` resolution with runtime > default > builtin precedence. Builtins: timestamp, date, random_name, last_url.
- **Workflow Player** (#390): Bridge-first player executing workflows via CDP/Playwright with selector fallback chain, step timeouts, checkpoint progress, variable resolution, and structured ExecutionResult.
- **Recorder** (#391): Passive CDP capture → workflow YAML with noise filtering, event grouping, CSS selector generation (ranked by stability), and variable detection.
- **Recovery & Checkpoint** (#393): FallbackController for element-not-found (exponential backoff), timeout handling (doubled timeout retry), block/challenge detection, checkpoint save/load with resume capability.
- **MCP Integration** (#392): 4 new MCP tools — stealth_teach, stealth_replay, stealth_workflow_list, stealth_workflow_delete — with path traversal protection and confirmation gates.

### Added — Deployment & Operations (M5)
- **Production Workflow Library**: Upwork (edit-title, update-rate, add-portfolio, submit-proposal) and LinkedIn (send-connection-request) workflows.
- **Operator Setup Guide** (#394): docs/OPERATOR_SETUP.md with quick start, MCP tools, bridge setup, troubleshooting, failure modes, backend selection guidance.
- **RBB Setup Scripts**: scripts/setup_rbb.sh (Linux systemd + cloudflared) and setup_rbb.ps1 (Windows nssm service wrapper).
- **Health Check**: scripts/health_check.py — validates MCP server, workflow library, bridge status, disk, and memory.
- **Deprecation Policy** (#378): MCP/CLI backward-compatibility aliases with 1-minor-version deprecation window and structured deprecation warnings.

### Changed / Improved
- CI includes MCP tool manifest smoke test ensuring all 17 tools present with valid schemas (#371).
- ConnectionPool renamed to NavigationHistory for honest telemetry-only semantics (#374).
- All CLI examples/docs normalized to canonical `agentic-stealth-browser` command (#372).
- Deterministic launch args via shared `_build_launch_args()` and `_merge_custom_options()` helpers (#373).

### Documentation
- docs/MCP_DEPRECATION.md — migration table and deprecation policy.
- docs/OPERATOR_SETUP.md — full operator guide.
- All stale module references removed from docs and changelog (#372).

### Migration Notes (v0.9 → v1.0)
- MCP tools extended with 4 workflow tools — validate existing clients handle unknown tools gracefully or update to list tools dynamically.
- CLI commands unchanged from v0.9.0.
- Legacy `ConnectionPool` → `NavigationHistory` rename: update any external references.

---

## [0.9.0] — MCP Runtime, Observability & CI Strictness (2026-05-23)

### Added — MCP Server & Observability (closes #369, #370, #379, #375)
- **Full in-repo MCP stdio runtime** (`production/mcp_server.py`): JSON-RPC 2.0 lifecycle, `tools/list`, `tools/call`.
  - Core stealth tools: `stealth_launch`, `stealth_navigate`, `stealth_load_cookies`, `stealth_set_region`, `stealth_scrape`, `stealth_status`, `stealth_close`, `stealth_capabilities`.
  - **Observability tools** (stacked on runtime): `stealth_tabs_list`, `stealth_tab_snapshot`, `stealth_session_timeline`, `stealth_debug_report`.
  - Security: `MCPSecurityContext`, path policy for cookies/snapshots, automatic redaction of secrets in responses/audit.
- **Guardrails & hardening** (#385): Env-configurable limits (`STEALTH_MCP_SNAPSHOT_MAX_PER_SESSION`, timeline limits, `OBSERVABILITY_MAX_CHARS`), pruning, truncation, root-boundary checks.
- **Operator Guide** (#375): New `docs/MCP_BROWSER_OBSERVABILITY.md` — primary MCP-native path, env vars, security notes, fallback headed mode, optional CDP, troubleshooting, copy-paste examples, and workflow table.
- README MCP section expanded with full tool table + env var reference + link to the guide.
- Deterministic runtime tests (`tests/test_mcp_server_runtime.py`) using fake browser — runs in CI without Playwright.

### Changed / Improved — CI, Compatibility & DX
- Pytest marker taxonomy + `--strict-markers` (registered: `e2e`, `live_network`, `slow`, `contract`, `mcp`) for deterministic, drift-proof CI selection (#380).
- Coverage gate adjusted to realistic 45% baseline during v0.9.0 rollout (many low-coverage modules); raising plan documented.
- Audit redaction tightened to preserve `session_name` and public identifiers while still protecting real secrets.
- Local stashed work on secure login / google / recovery preserved for follow-up.

### Documentation & Policy
- Backward-compat & deprecation policy foundation for v0.9.0 MCP surface (#378) — existing flows continue or receive clear migration errors.
- Updated tests/README.md with marker usage and CI commands.
- All v0.9.0 MCP changes include contract tests and smoke validation.

### Migration Notes (v0.8 → v0.9)
- New primary way to run as MCP server: `python -m production.mcp_server`.
- Old external `stealth-playwright-mcp` bridge is superseded by the in-tree runtime (aliases/deprecation helpers to be expanded in patch releases per #378).
- All observability responses now bounded and redacted by default.

See the full v0.9.0 milestone and the stacked PRs #383/#384/#385 for implementation details.

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

[unreleased]: https://github.com/shanewas/agentic-stealth-browser/compare/v0.9.0...HEAD
[1.0.0]: https://github.com/shanewas/agentic-stealth-browser/releases/tag/v1.0.0
[0.9.0]: https://github.com/shanewas/agentic-stealth-browser/releases/tag/v0.9.0
[0.2.0]: https://github.com/shanewas/agentic-stealth-browser/releases/tag/v0.2.0
[0.1.0]: https://github.com/shanewas/agentic-stealth-browser/releases/tag/v0.1.0
