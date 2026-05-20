# Phase 8 — Mass Issue Resolution Campaign

**Goal:** Systematically fix the 300+ practical GitHub issues created during the review and generation phase.

**Started:** 2026-05-20 (after reaching 300 issues)

**Strategy:** Parallel specialized sub-agents + careful, incremental, tested fixes + PRs per coherent batch.

**Status:** All 9 specialized fix agents launched and running in parallel (2026-05-20)

## Prioritization Rules (Enforced)
1. **P1 + clear bugs** first (reliability, crashes, major stealth holes, broken recovery).
2. **Technical debt** that causes real pain (sync I/O, missing context managers, brittle parsing, dead code).
3. **High-impact DX / Testing / Production** improvements.
4. **Enhancements & Future (P3)** — only after the above are in good shape. Many will be batched or deferred with comments.
5. **Never over-engineer**: Prefer minimal, correct, well-tested changes over grand rewrites unless the issue explicitly calls for architecture change.

## Workstreams & Responsible Agents

| Workstream                    | Focus Areas                                      | Approx Issues | Lead Agent Type       | Status     |
|-------------------------------|--------------------------------------------------|---------------|-----------------------|------------|
| Stealth & Fingerprinting      | Canvas/WebGL/TLS/Fonts/headers/patches/Offscreen | ~55           | Stealth Fix Agent     | In flight  |
| Recovery & Resilience         | Detection, rotation, escalation, persistence, cost | ~45         | Recovery Fix Agent    | In flight  |
| Core / AgentBrowser / Reliability | Context manager, page_getter, ephemeral, clone, cookies, launch | ~50 | Core Reliability Agent | In flight |
| Human Behavior                | Mouse, typing, scroll, idle, shortcuts, realism  | ~40           | Behavior Fix Agent    | In flight  |
| Testing, CI & Quality         | E2E, chaos, contract, benchmarks, detection      | ~35           | Testing Fix Agent     | In flight  |
| Production / Docker / Ops     | Dockerfile, images, CLI, packaging, health       | ~25           | Production Fix Agent  | In flight  |
| DX / Docs / Presets / Debug   | Presets, debug mode, explain-blocked, notebooks, docs | ~30     | DX & Docs Agent       | In flight  |
| Performance & Observability   | CDP reduction, metrics, warm-up, pooling, overhead | ~25        | Perf Agent            | In flight  |
| MCP / Proxy / Integration     | MCP tools, session persistence, proxy manager    | ~20           | MCP & Proxy Agent     | In flight  |

## Execution Rules for All Agents
- Read the full issue body + linked REVIEW files.
- Read the relevant source files (use tools).
- Make **small, safe, well-tested** changes.
- Add or improve tests for the fixed behavior.
- Run `pytest` (or specific test files) before committing.
- Use feature branches named `fix/<area>-<issue-range>` or similar.
- Commit with messages that reference the GitHub issue numbers.
- Open one high-quality PR per logical group of fixes (or per major issue when big).
- Link PRs back to the original issues (use "Closes #NNN").
- If an issue is too large or requires design, create a comment on the issue + a small spike PR, then ask for direction.

## Current High-Priority P1 Targets (Start Here)
- #292 Core context manager for reliable cleanup
- #288 DX LinkedIn 2026 recommended presets
- #273 DX "explain why blocked" helper
- #265 DX Debug mode / fingerprint dump
- #256 Testing E2E recovery test against real protected site
- Several stealth patch gaps (#262 OffscreenCanvas, #286 prototype checks, etc.)

**We are now executing in parallel using specialized sub-agents.**

---

*This file is the single source of truth for the Phase 8 fix effort.*

## Recovery & Resilience Agent Progress (this sub-agent)

**Started:** 2026-05-20

**Focus:** P1 bugs that crash or noop the recovery layer (#99, #10, #16, #17, #38, #112, #120, #130, #163, #171, #179, #252 etc.)

**Fixes delivered in batch 1:**
- Fixed UnboundLocalError in `AntiBlockOrchestrator.detect_block` content analysis path (when page_getter returns falsy page) — #17, #120. Strengthened test coverage.
- Added `_safe_extract_base_user()` helper + replaced all brittle `.split('-')[1]` parsing in proxy rotation — prevents recovery crash on bad username format. Also ensures `proxy_manager.current_config` is updated post-rotation. #99, #10.
- Wired `proxy_manager` into `AgentBrowser.launch()` via `launch_kwargs` so proxies are actually passed to persistent_context (was completely ignored before). Foundation for rotation. Progress on #38, #16, #105 indirectly.
- Added unit tests exercising the new safe paths and helper.
- All changes are small, syntax-verified, and test-passing.

**Status:** First PR prepared. More batches for circuit-breaker, error taxonomy, cost awareness, persistence, escalation, scraper integration, and actual rotation relaunch logic (careful design needed) to follow.

**Issues targeted for close by this batch PR:** #99, #10, #17, #120 (core), plus partial #38, #16.

**Next:** Deeper rotation application (relaunch hook), #130 circuit breaker, #179 classification, add e2e chaos test.

See also: `tests/test_phase7_fixes.py`, `recovery/anti_block_orchestrator.py`, `core/agent_browser.py`

