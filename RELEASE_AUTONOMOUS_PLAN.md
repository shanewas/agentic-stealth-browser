# v0.9.0 Autonomous Release Execution Plan
**Owner**: Grok 4.3 (autonomous mode)  
**Goal**: Drive the repository to a truly polished, release-ready v0.9.0 state while user is AFK.  
**Started**: 2026-05-23 (post v0.9.0 tag)  
**Current Master State**: v0.9.0 tag pushed, MCP runtime + observability + guide merged, basic #380 markers/strict in place, version bumped.

## Core Principles (Self-Check Rules)
1. **Never break master** — All risky changes happen in `git worktree` (isolation: "worktree") or feature branches. Only fast-forward or clean merges to master.
2. **Verification Gate** — After every non-trivial edit batch:
   - `python3 -m pytest ... --collectonly -q --tb=no -m "not e2e and not live_network"`
   - `python3 -m production.mcp_server --list-tools`
   - Relevant unit tests in background.
   - Use the "check" skill subagent when possible.
3. **Error Recovery**:
   - 3 consecutive failures on a task → log in this file + create a `BLOCKED_<task>.md`, skip to next task, schedule retry in 30m.
   - Git conflicts → abort, use `--theirs` or manual 3-way only after reading both sides, never force without review.
   - CI red → use `gh run view --log-failed`, diagnose, fix in worktree, push only after local green.
4. **Parallelism** — Use `spawn_subagent` (general-purpose or "plan") + worktree isolation for independent features (#377, #381, #378 polishing).
5. **Self-Monitoring Loop** — Scheduler every 15-20 min runs health checks (git status, gh run list, pytest collection, mcp smoke).
6. **Progress Transparency** — Update this file + todos after every major step. Leave clear "last successful state".
7. **AFK Safety** — If a step would require user input (e.g., secret, ambiguous design), document the question in `BLOCKED_*.md` and continue with next highest-value item.

## Detailed Task Breakdown & Dependencies
1. **#380 Complete (Foundation - High Priority)**
   - Full audit of all `tests/*.py` for missing markers.
   - Update both `.github/workflows/*.yml` to rely primarily on `-m` filters + `--strict-markers`.
   - Add "Collect only (artifact)" step in CI for auditability.
   - Update `tests/README.md` + any other docs.
   - Verification: clean collection + strict run.

2. **#381 Pagination & Limits (Observability Hardening)**
   - Extend the 4 observability tools with `limit`, `cursor`, `since_ts` (where applicable).
   - Return `next_cursor`, `has_more`, `truncated` metadata.
   - Strengthen `_guard_observability_payload`.
   - Update input schemas + deterministic tests.
   - Docs update in the new guide.

3. **#377 Optional CDP Attach**
   - Add `debug_cdp_port` / `enable_cdp` to launch.
   - New MCP tool `stealth_get_cdp_endpoint` (returns ws://localhost:... when enabled).
   - Security: only localhost, explicit opt-in, warning in response + docs.
   - Tests + guide update.

4. **#378 Compat & Deprecation Policy**
   - Simple alias map in `StealthMCPServer` (e.g., old tool names -> current).
   - Deprecation warning helper that still works but logs.
   - Migration section in README + new guide.
   - Contract tests that exercise aliases.

5. **Final Polish & Release Artifacts**
   - Update `OPEN_SOURCE_READINESS.md` (bump score, note v0.9.0 items).
   - Full local verification script (collection + mcp smoke + import + version check).
   - Create `RELEASE_NOTES_v0.9.0.md` or prepare GitHub release body.
   - (Optional) Re-tag v0.9.0 if we need to move the tag forward after fixes.
   - Clean any leftover "dev" strings.

6. **Ongoing Self-Check Loop (runs autonomously)**
   - Scheduler task: health check every 15 min.
   - Monitor long CI runs.
   - On any red: create diagnostic note + attempt auto-fix (up to 2 retries).

## Current Status Snapshot (2026-05-23)
- Merged: #383/384/385 + #375 guide.
- Partial: #380 (markers registered, strict in pyproject, some CI updated, collection verified clean).
- v0.9.0 tag exists on GitHub.
- Stash exists: `temp-stash-secure-login-changes` (google_login + recovery work — defer unless it blocks release).
- No blocking errors right now.

## Autonomous Execution Rules for This Session
- I will work in cycles: Plan → Spawn parallel safe work → Sequential verified edits in worktrees → Health check → Update this file + todos.
- If user returns, they can read this file + todo list for exact state.
- Prioritize: unblock CI/test cleanliness first, then feature completeness, then polish.
- Use `run_terminal_command` with `background:true` + `get_command_or_subagent_output` for long ops.
- Use `spawn_subagent` with `isolation:"worktree"` for independent feature impl.
- Use `scheduler_create` for the recurring health loop.

**Execution Log (Autonomous Loop)**

- 2026-05-23 ~07:30 : Health scheduler created (every 15m, writes RELEASE_HEALTH.log, detects blockers).
- 2026-05-23 ~07:32 : #380 advanced (collection audit artifact added to ci.yml, strict-markers explicit in e2e workflow, policy docs started).
- 2026-05-23 ~07:35 : Spawned subagent 019e53c2-a43e... for #381 (pagination) in /tmp/wt-381 — actively editing (32+ tool calls, no errors).
- 2026-05-23 ~07:40 : Spawned parallel subagent 019e53c4-cbd5... for #377 (CDP attach) in /tmp/wt-377.
- 2026-05-23 ~07:42 : Safe doc push for #378 migration policy into the observability guide.
- Two feature implementations now running fully autonomously in isolated worktrees with built-in verification gates.
- Health loop + plan file will keep everything auditable while user is AFK.

**Current Focus**: Let the two subagents complete their features with verification. On their return, integrate, run full health + CI watch, then tackle remaining polish (#380 full audit + final artifacts).

**Latest Update (post-#381 merge)**:
- #381 (pagination) fully completed by autonomous subagent, verified, merged to master, and pushed.
- Pagination support (`cursor`, `since_ts`, `next_cursor`, `has_more`) is now live on master for `stealth_session_timeline` and `stealth_debug_report`.
- This significantly strengthens the v0.9.0 observability contract.

**#377 CDP Attach — Also Completed**
- Second subagent delivered full optional CDP support (`debug_cdp` launch flag + `stealth_get_cdp_endpoint` tool + localhost-only security + clear disabled path).
- Merged to master after resolving one test fake conflict.
- Both #381 and #377 (the two main new MCP capabilities for v0.9.0) are now on master.

**#380 Progress (May 23, late)**
- Committed organized set of changes against #380:
  - ci: marker-based filtering + collection audit artifact in main CI workflow
  - ci: --strict-markers enforcement in fast unit workflow
  - docs: full Marker Taxonomy section added to tests/README.md
  - test: added pytestmark = pytest.mark.contract to test_mcp_contract.py
  - docs: OPEN_SOURCE_READINESS.md updated to 0.9.0
- All commits pushed with clear references to #380.

The loop is healthy and self-documenting. No human input required until the user returns.

This plan will be updated after every cycle. The version will be driven to release-ready without further human input until the user returns.