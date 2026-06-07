# Changelog

All notable changes to the Agentic Stealth Browser will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

## [2.5.0] — Real Dashboard Backend Adapters (#444) (2026-06-07)

### Added
- **`BackendAdapter` Protocol + `Capability` enum** (`production/adapters/base.py:84`): runtime-checkable protocol with `launch`/`close`/`navigate`/`click`/`fill`/`screenshot`/`status`/`capabilities` surface. All three backends (M1/M2/M3) implement it. New `AdapterLaunchError` and `AdapterCapabilityError` exception types; `register_adapter` enforces non-empty string names. (#444 M0)
- **`CDPBridgeAdapter`** (`production/adapters/cdp_bridge.py`): Playwright `connect_over_cdp` over WebSocket. Used for adopted-context / WSL-host workflows where the operator already owns a browser process. (#444 M1)
- **`PlaywrightMCPAdapter`** (`production/adapters/playwright_mcp.py`): stdio subprocess + MCP JSON-RPC. Spawns `npx @playwright/mcp` with an explicit env allowlist (PATH, HOME) and a 16 MB `MAX_FRAME_BYTES` frame cap. (#444 M2)
- **`AgenticStealthMCPAdapter`** (`production/adapters/agentic_stealth_mcp.py`): stdio subprocess + MCP JSON-RPC, round-trips through the bundled `production.mcp_server` runtime. Same env allowlist, frame cap, and stderr-drain guarantees as M2. (#444 M3)
- **Dashboard backend wiring (M4)**: `BrowserRuntimeManager` resolves the configured backend through the adapter registry, records an audit event on backend switch, surfaces negotiated capabilities in dashboard status, and rejects unsupported actions with a backend-specific error. `production/dashboard_adapter_bridge.py` is now a thin shim that re-exports the three M1–M3 adapters. (#444 M4)

### Changed
- `production/hermes_dashboard.py` re-exports `BackendAdapter` from `production/adapters/`.
- `production/dashboard_adapter_bridge.py` thin shim replaces the three alias backends.
- `MANIFEST.in`: ships `assets/*.{gif,png,jpg,svg}` (demo GIF), `docs/`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md` (sdist previously dropped the demo GIF and the entire `docs/` tree).
- `README.md`: added "What is this / When to use / When NOT to use" block at top, honest comparison table (region client-hello profiles, not full uTLS), install-from-source section, full project tree + doc index. Dropped unverified test-count badge and Buy Me A Coffee. 177 → 238 lines.
- New `docs/README.md` operator/reference/planning index. Root-level `*PLAN.md` / `*READINESS.md` / `*DASHBOARD.md` / `HN_POST.md` moved to `docs/plans/misc/` as historical.
- Examples rewritten for honesty and reproducibility: `01_cloudflare_bypass.py` (nowsecure.nl + screenshot), `02_linkedin_search.py` (`linkedin_2026` preset + webdriver check + DDG), `03_amazon_product.py` (product → title + price). `recipes/README.md` table updated.
- `pyproject.toml` version 2.4.1 → 2.5.0.

### Fixed
- **#444 M0 review (showstoppers)**:
  - **S1 capability gating**: M2/M3 `navigate`/`click`/`fill`/`screenshot` now call `self.supports()` and raise `AdapterCapabilityError` if the adapter doesn't declare the capability (enforces `base.py:84` protocol contract). New `_require_capability()` helper on each adapter.
  - **S2 stderr drain**: M2/M3 `stderr=PIPE` is now drained by a background task started right after `spawn` and cancelled in `close()`. A noisy child no longer fills the ~64 KB kernel pipe buffer, blocks on its next stderr write, hangs the handshake, and triggers a slow SIGKILL on close.
  - **F1 stale state on retry**: after MCP handshake failure, `terminate_subprocess()` is called and `self._proc` / `self._client` are cleared. A caller that catches `AdapterLaunchError` and then calls `close()` no longer operates on a dead `Process` handle.
- **#444 M0 review (smaller)**:
  - **F2 frame cap**: `_jsonrpc_stdio.readline()` now enforces `MAX_FRAME_BYTES = 16 MB` and raises `ConnectionError` on overflow. A misbehaving server emitting a multi-GB line no longer OOMs the client.
  - **F3 env allowlist**: both stdio adapters now pass an explicit `env={PATH, HOME}` to `asyncio.create_subprocess_exec` instead of inheriting the operator's full environment (`OPENAI_API_KEY`, `AWS_*`, `DATABASE_URL`, ...).
  - **A3 dead tautology**: `cdp_bridge.screenshot()` had a defensive `Capability.SCREENSHOT` check that could never fire (always in `capabilities()`). Branch removed; M0 contract is the only contract that matters.
  - **M0 code-quality review (17abc50)**: exception types narrowed to library-specific where appropriate, `isinstance` coverage tightened, defensive tautology branches removed, transport teardown made symmetric with launch.
- **Adapter capability gating**: now consistent across M1/M2/M3 — each action is contractually declared, not assumed.
- **Ruff/format housekeeping** (4432701): 12 ruff format issues + 1 unused import fixed.

### Tests / CI
- `tests/test_backend_adapter_contract.py` — new contract test pinning the M0 Protocol surface, `Capability` enum members, and `register_adapter` duplicate/empty/non-string rejection.
- `tests/test_adapter_cdp_bridge.py`, `tests/test_adapter_playwright_mcp.py`, `tests/test_adapter_agentic_stealth_mcp.py` — new per-adapter tests covering launch, capability negotiation, action gating, stderr drain, env allowlist, and close lifecycle.
- `tests/test_dashboard_protocol_bridge.py` — new dashboard-wiring test (M4): audit event on backend switch, capability surface, unsupported-action rejection.
- `pytest -q`: 1025 collected, 1023 passed, 2 e2e skipped, 0 failed (139 s; baseline maintained).
- `ruff check` + `ruff format --check` clean across 159 Python files.

Closes #444.

---

## [2.4.1] — v2.4.0 Stabilization Patch (2026-06-03)

### Fixed / Security / Reliability (P0/P1 per #459)
- **#454** MCP nav/scrape: `is_url_safe` now fails closed for non-http(s) schemes (`file:`, `javascript:`, `data:`, `ftp:`, ...), missing hosts, DNS errors, and empty resolutions. Unsafe inputs raise `MCP_SSRF_BLOCKED` before any browser navigation. Added unit matrix + dispatch regression tests.
- **#455** MCP runtime: declarative input validation from `production/mcp_input_validator.py` is now enforced in `tools/call` dispatch (types, lengths, ranges, required, patterns, `additionalProperties: false`). Validation errors return stable `MCP_VALIDATION_ERROR` without invoking handlers. Schema/validator parity and dispatch tests added.
- **#451** CDP attach: adopted user tabs (`new_context=False`) are no longer closed on `close()`. New `_owns_page` tracking + conditional teardown; adopted contexts/pages preserved per contract. Updated tests + docs.
- **#452** CDP attach: post-`connect_over_cdp` failures (bad context_index, new_context, page create, stealth) now best-effort rollback `_pw`, `_remote_browser`, owned ctxs (never adopted), and reset attach flags for clean retry.
- **#453** CDP attach: attach path now initializes `human`, `orchestrator`, `logger`, `scraper`, `ai`, `recovery` (with attach degradation notes). `safe_goto`/`safe_click`/`safe_type` + MCP `stealth_scrape` now operational on attached sessions.
- **#458** Hermes dashboard: startup rejects default/empty/`change-me` password when binding to non-loopback (0.0.0.0, RFC1918, public, IPv6 non-loop). Loopback dev still convenient. Added guard tests.
- **#457** CLI `scrape`: removed double `launch()` (async-with already launches; now passes preset/region via ctor so aenter applies them). Exactly one launch + one close. Aligned all user-facing names/help/examples to `agentic-stealth-browser`. Mocked regression test.
- **#456** Packaging: `pyproject.toml` now includes `production.*`, `workflows.*`, `plugins.*`. `MANIFEST.in` extended. CI verify expanded for SDK import + bundled workflow discovery from clean cwd. MCP server workflow root switched to user-writable `~/.agentic-browser/...` + bundled discovery fallback for install safety.
- **#447** MCP version: `SERVER_VERSION` now derives from `importlib.metadata.version("agentic-stealth-browser")` (falls back to 2.4.1); no longer stale.
- **#448** CDP attach gate: relaxed RFC1918 rejection under `allow_remote=true` for attach (WSL host IPs are intentionally private); link-local/cloud still blocked. Nav remains strict. Reconciled docs + tests with real WSL workflow.
- **#450** Docs/metadata: toned down TLS/JA3/JA4 claims to "region client-hello profiles (process-level)"; attach degradation already documented the limits. No wire-level full-stack spoofing claimed.
- **#449** Release hygiene: refreshed counts, changelog, version to 2.4.1, support notes, publish smoke.

### Added
- Runtime helpers and ownership tracking for attach mode.
- Validation dispatch + matrix tests; single-launch CLI mock test; dashboard bind security tests.

### Changed
- `pyproject.toml` version 2.4.0 → 2.4.1; packages.find + MANIFEST.in for full artifacts.
- Attach lifecycle docs/examples (no more auto-launch + attach in same `async with`).
- MCP attach remote safety contract + tests for WSL compatibility.

### Tests / CI
- All non-e2e/non-live green.
- Focused attach + MCP safety + validation + CLI mocks + dashboard guard.
- `ruff check` + `ruff format --check` pass.
- Wheel build + import + discovery smoke updated in publish.yml.

Closes #447, #448, #449, #450, #451, #452, #453, #454, #455, #456, #457, #458, #459 (patch scope).

---

## [2.4.0] — Attach-Mode Hardening (2026-06-01)

### Fixed
- **#438** `stealth_attach_over_cdp` loopback gate reused `is_url_safe` — DNS rebinding / hostname→private-IP bypass closed. Replaces string match with full RFC-1918 + link-local + cloud-metadata check. The gate is now a two-layer check: `is_loopback_host` first, then `is_url_safe` only when `allow_remote=true` (so even explicitly-allowed remote hosts can't be RFC-1918 or link-local).
- **#441** Link-local IPv6 (`fe80::/10`) added to `_BLOCKED_NETWORKS`. Side-effect of #438's refactor — `is_url_safe` now rejects IPv6 link-local the same way it rejects IPv4 `169.254.0.0/16`.
- **#440** `add_init_script` install failure now surfaces in the return payload as `stealth_applied: false` + `stealth_error: "<ExceptionType>: <message>"`. Previously silent. New `stealth_requested` field distinguishes caller intent from actual install result.
- **#439** `AgentBrowser.close()` teardown logic now uses a typed `TeardownMode` enum (`LAUNCHED | POOLED | ATTACHED_OWNED_CTX | ATTACHED_ADOPTED_CTX`) instead of 3 scattered `getattr` flag checks. Each branch owns exactly one teardown. Easier to reason about, easier to extend.

### Added
- **`is_loopback_host(url: str) -> bool`** helper in `production/mcp_server.py` — literal/IP/DNS loopback check. Used by the attach loopback gate.
- **6 new tests in `tests/test_mcp_url_safety.py`** covering loopback literal, `localhost`, bare `host:port` normalization, RFC-1918 rejection, link-local IPv6 rejection.
- **4 new tests in `tests/test_attach_over_cdp.py`** covering the two-layer gate (RFC-1918, link-local IPv6, with/without `allow_remote=true`).
- **4 new tests in `tests/test_attach_over_cdp.py`** for `TeardownMode` enum and stealth-failure surface (monkeypatched `add_init_script` rejection).

### Changed
- `production/mcp_server.py`: new `is_loopback_host` helper. `_BLOCKED_NETWORKS` extended with `fe80::/10`. `_tool_stealth_attach_over_cdp` rewritten as a two-layer gate.
- `core/agent_browser.py`: new `TeardownMode` enum. `close()` branches on the enum. `attach_over_cdp` return dict now includes `stealth_requested` and `stealth_error` fields.
- `pyproject.toml`: `version` bumped 2.3.0 → 2.4.0.

### Test coverage
- 22/22 pass in `tests/test_attach_over_cdp.py` + `tests/test_mcp_url_safety.py`
- No new regressions in the unit-test suite (3 pre-existing failures on master — `test_human_behavior_fuzz` MockPage signature mismatch + `test_phase7_fixes` merge conflict — both unrelated to this release)

### Closes
- #438, #439, #440, #441

---

## [2.3.0] — Show HN & Community Launch (2026-05-28)

### Added
- **Show HN preparation**: Complete README overhaul with demo GIF, streamlined onboarding, and community-facing tone. (#HN)
- **Buy Me A Coffee badge**: Support link in README for community sponsorship. (#badge)
- **`_browser_process` exposure**: External PID tracking via `AgentBrowser._browser_process`, enabling process-level monitoring and recovery. (#pid)

### Changed
- Full README rewrite for PyPI + HN audience (pip-first install path, Quick Start with CLI + Python SDK + MCP, reduced wall-of-text, more code examples).
- Demo GIF (`assets/hn-demo.gif`) showing end-to-end stealth browser flow.
- Various lint fixes for demo scripts.

### Fixed
- Stray temp files cleaned from repo root.
- Ruff formatting applied across all Python sources.

## [2.1.1] — PyPI & Docs Consolidation (2026-05-27)

### Added
- **PyPI publish workflow** (`.github/workflows/pypi-publish.yml`): OIDC trusted publishing for automated release deployment. (#pypi)
- **PyPI release readiness**: README polished for pip-first consumption, badges and metadata tuned for PyPI listing.

### Changed
- **Docs consolidation**: `docs/` folder removed, all documentation consolidated into README.md for a single source of truth. Content preserved (THREAT_MODEL, STEALTH_LIMITATIONS, ADRs, etc. remain accessible via GitHub blob links).
- ruff formatting applied across dashboard codebase.

## [2.1.0] — Hermes Browser Dashboard (2026-05-30)

### Added
- **Hermes Browser Dashboard** (`production/hermes_dashboard.py`): Single-user operator dashboard with live browser view, execution control, workflow recording/replay, activity timeline, session auth, and CSRF protection. (#434)
- **`stealth-browser dashboard` CLI subcommand**: Starts the dashboard server on `127.0.0.1:8443` with configurable password. (#434)
- **Dashboard tests** (`tests/test_hermes_dashboard.py`): 6 contract tests covering start/stop, recording/replay, intervention state, devtools URL generation, auth+CSRF, and schedules. (#434)

### Fixed
- CI: `setup-python` bumped to v6 across all workflows
- CI: Install `httpx` in stealth recovery workflow
- CI: Python 3.11 test compatibility fixes
- CI: Dashboard file formatting for ruff compliance

### Changed
- `SERVER_VERSION` → `2.1.0`
- `pyproject.toml` version → `2.1.0`

## [2.0.0] — Workflow Platform GA (Major Release) (2026-05-25)

### v1.6.0 — API/SDK and Plugin Ecosystem (incremental)

#### Added
- **Python SDK** (`production/sdk/client.py`): Workflow lifecycle API with async client, type-hinted interfaces, timeout and error handling.
- **MCP JSON Schema output**: `ToolSpec.json_schema()` returns full input+output schemas for every tool. New MCP method `list_tool_schemas`.
- **Unified response envelope**: `StealthMCPServer.unified_result_envelope()` normalizes all tool responses to `{status, data, meta}` structure.
- **Plugin template** (`plugins/template/`): Working example plugin with registration pattern.

### v1.7.0 — Browser/Platform Expansion
#### Added
- **Browser capability map** (`docs/CAPABILITY_MAP.md`): Full feature matrix across backends.
- **Feature flag system** (`core/feature_flags.py`): Dynamic feature toggles for browser-specific capabilities.
- **Firefox adapter** (`stealth/firefox_adapter.py`): Feature-flagged Firefox support with basic stealth patches.

### v1.8.0 — Adaptive Stealth and Learning Loop
#### Added
- **FeedbackStore**: Persistent telemetry ingestion for replay/recovery events. Tracks selector success rates per domain and detection events.
- **Domain-specific tuning profiles**: AdaptiveTuner now maintains per-domain behavior profiles with bounded adaptation (minimum stealth thresholds enforced).
- **Stealth evaluation harness** (`scripts/evaluate_stealth.py`): Comparative evaluation between patched and baseline behavior.

### v1.9.0 — v2 Migration Line
#### Added
- **v2 migration RFC** (`docs/rfc/v2-migration.md`): Documented all planned breaking changes with before/after examples and timeline.
- **Deprecation shims** (`production/deprecations.py`): Backward-compatibility wrappers for APIs changing in v2.
- **Migration script** (`scripts/migrate_v1_to_v2.py`): Converts v1 workflow YAMLs to v2 format with CI validation support.
- **`browser_context` canonical reference**: New `self.browser_context` attribute in AgentBrowser replacing deprecated `self.context`.

### v2.0.0 — Workflow Platform GA
#### Changed
- `SERVER_VERSION` → `2.0.0`
- `pyproject.toml` version → `2.0.0`

### Migration Notes (v1.x → v2.0)
- `self.context` is deprecated in favor of `self.browser_context` (planned removal in v2.1.0)
- MCP tool responses now use unified `{status, data, meta}` envelope — old direct payload parsing will break
- Workflow schema v2 includes required metadata version field — run `scripts/migrate_v1_to_v2.py` to update existing workflows
- See `docs/rfc/v2-migration.md` for complete breaking change list

---

## [1.5.0] — Scale and Performance (2026-05-25)

### Added
- **Timing profiler** (`production/profiler.py`): Decorator and context-manager-based performance instrumentation.
- **Performance benchmark script** (`scripts/perf_benchmark.py`): Benchmarks core operations (safe_goto, safe_click, safe_type) with timing stats.
- Pre-existing bottlenecks documented in `docs/PERFORMANCE_TUNING.md`.

### v1.4.0 — Security and Governance
#### Added
- **MCP input validator** (`production/mcp_input_validator.py`): Parameter type/length/pattern validation for all tool inputs.
- **Session isolation enforcer** (`production/mcp_session_isolation.py`): Ensures one session's tools cannot access another session's data.
- **Workflow policy engine** (`production/policy_engine.py`): YAML-based policy files with path/action/destination controls.
- **Approval gate hooks** (`production/approval_gate.py`): Sensitive actions (navigate to unknown domain, execute_js) require explicit approval.
- **Audit enrichment** (`production/audit_enrichment.py`): Actor/session/workflow correlation data added to all audit log entries.

---

## [1.3.0] — Orchestration and Automation Operations (2026-05-25)

### Added
- **WorkflowOrchestrator** (`production/workflow_orchestrator.py`): Queue manager with per-domain/account concurrency controls, priority ordering, and disk persistence.
- **Scheduled execution**: Recurring workflow support with datetime-based scheduling and interval config.
- **Checkpoint persistence**: Queue state save/load with resume capability on restart.
- **Cross-workflow composition**: `run_workflow` step type with variable passing and cycle detection.
- **Unit tests**: 24 tests for enqueue, domain concurrency, scheduling, persistence, status, backoff.

---

## [1.2.0] — Workflow Intelligence and Authoring Quality (2026-05-25)

### Added
- **Selector auto-heal**: Confidence scoring for CSS selectors, dynamic class detection, auto-generated fallback selectors when primary selectors fail.
- **Rehearsal mode**: `rehearse()` method on WorkflowPlayer — dry-run execution that validates selectors, takes screenshots, logs issues without clicking/submitting.
- **Pre-save validation**: `validate_workflow_steps()` detects anti-patterns (navigate without timeout, fill without verify, fragile selectors, typos in step types).
- **Workflow versioning**: Version field in schema, metadata changelog on save, `workflow_diff()` for comparing versions.
- **Unit tests**: 59 tests across 4 new test files (selector_auto_heal, workflow_orchestrator, rehearsal_validation, workflow_versioning).

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

[unreleased]: https://github.com/shanewas/agentic-stealth-browser/compare/v2.3.0...HEAD
[2.3.0]: https://github.com/shanewas/agentic-stealth-browser/releases/tag/v2.3.0
[2.1.1]: https://github.com/shanewas/agentic-stealth-browser/releases/tag/v2.1.1
[2.1.0]: https://github.com/shanewas/agentic-stealth-browser/releases/tag/v2.1.0
[2.0.0]: https://github.com/shanewas/agentic-stealth-browser/releases/tag/v2.0.0
[0.9.0]: https://github.com/shanewas/agentic-stealth-browser/releases/tag/v0.9.0
[0.2.0]: https://github.com/shanewas/agentic-stealth-browser/releases/tag/v0.2.0
[0.1.0]: https://github.com/shanewas/agentic-stealth-browser/releases/tag/v0.1.0
