# Phase 8 — Mass Issue Resolution Campaign

**Goal:** Systematically fix the 300+ practical GitHub issues created during the review and generation phase.

**Started:** 2026-05-20 (after reaching 300 issues)

**Strategy:** Parallel specialized sub-agents + careful, incremental, tested fixes + PRs per coherent batch.

**Status:** Just started (user directive to begin parallel fixing)

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
| Human Behavior                | Mouse, typing, scroll, idle, shortcuts, realism  | ~40           | Behavior Fix Agent    | Planned    |
| Testing, CI & Quality         | E2E, chaos, contract, benchmarks, detection      | ~35           | Testing Fix Agent     | Planned    |
| Production / Docker / Ops     | Dockerfile, images, CLI, packaging, health       | ~25           | Production Fix Agent  | Planned    |
| DX / Docs / Presets / Debug   | Presets, debug mode, explain-blocked, notebooks, docs | ~30     | DX & Docs Agent       | Planned    |
| Performance & Observability   | CDP reduction, metrics, warm-up, pooling, overhead | ~25        | Perf Agent            | Planned    |
| MCP / Proxy / Integration     | MCP tools, session persistence, proxy manager    | ~20           | MCP & Proxy Agent     | Planned    |

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

## Stealth & Fingerprinting Fixes Agent Progress

**Agent:** Stealth & Fingerprinting Fixes Agent  
**Started:** 2026-05-19 (first session)

### Batch 1: Canvas + OffscreenCanvas + WebGL2 improvements (PR in prep)
**Issues addressed:** #94, #262, #210 (core of group), related old #27
**Changes:**
- Removed destructive `fillText` digit mangling in canvas patch (was breaking legitimate site canvas usage like charts, text labels).
- Added `OffscreenCanvas.prototype.getContext` hook (previously unpatched; modern sites, workers, detectors use it).
- Extended WebGL spoofing to `WebGL2RenderingContext` + additional params + small seeded jitter.
- Added `fingerprint_seed` param to `get_stealth_script()` and wired per-session unique seed in `AgentBrowser.launch` (different sessions now produce different canvas/WebGL fingerprints; defeats static detection).
- Captured `devicePixelRatio` in patch for future zoom/DPR-aware noise.
- Added pure regression test `test_stealth_canvas_offscreen_webgl2_fixes_94_262_210`.
- Updated scorecard skeleton (bonus Offscreen check prepared).
- Updated version, comments with issue refs.
**Files:** `stealth/advanced_stealth.py`, `core/agent_browser.py`, `tests/test_phase7_fixes.py`
**Testing:** Python syntax clean, direct invocation tests pass, existing phase7 sync tests unaffected (async test env quirks pre-existing).
**Risk:** Low — additive hooks + seed injection, no behavior change for non-canvas paths. Destructive code removed (improvement).
**Next in stealth:** WebGL extensions (#218), TLS validation (#293 etc), fonts, more APIs.

**Branch:** `fix/stealth-canvas-offscreen-webgl2-94-262-210`
**Status:** Ready for commit + PR (Closes #94, #262, #210)

### Overall Stealth Backlog
52 open stealth-labeled issues. Grouping strategy:
- Canvas/Offscreen/WebGL2/DPR (this batch)
- WebGL depth + extensions + precision
- TLS realism, validation, docs
- Fonts + measurement
- Prototype robustness + missing APIs (battery, speech, webrtc, hardware, audio, mediaqueries, client-hints)
- Self-detection + maintenance

Will open first PR after this update. Will batch 3-5 PRs before reporting final.
