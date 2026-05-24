# Hermes Browser Dashboard - Codex Goal Mode

## Mission
Improve this repo: https://github.com/shanewas/agentic-stealth-browser.git

Build an internal single-user VPS dashboard where a human and Nova/Hermes share one live Chromium session. Nova controls the browser through MCP; the human can watch, click, type, solve CAPTCHA/login/edge cases, then hand control back. Human demos become reusable YAML workflows.

## Success
1. Edge opens the dashboard with a live interactive browser.
2. Human and agent actions appear in the same session in real time.
3. Human override works without resetting the browser.
4. A 5+ step demo records to YAML and replays successfully.
5. One UI control switches between `playwright-mcp`, `agentic-stealth-mcp`, and `cdp-bridge`.

## Scope
Build: single-session dual control, dashboard UI, MCP orchestration, recorder/player, pause/resume, named isolated profiles, activity timeline, and log export.

Do not build: multi-user support, SaaS tenancy, VNC/RDP/video streaming, mobile browsers, billing, or monetization.

## Architecture
- Dashboard: FastAPI + Jinja2 + HTMX.
- Browser control: CDP gateway over one managed Chromium runtime.
- Runtime manager: start, stop, health, restart, best-effort restore.
- Backends: one normalized adapter over `playwright-mcp`, `agentic-stealth-mcp`, and `cdp-bridge`.
- Workflow engine: recorder, player, validator.
- Storage: Git-friendly YAML workflows plus metadata JSON.
- Events: structured `human`, `agent`, `system`, and `error` timeline entries.

## Required Behavior
- Live panel shows URL/tab/load state; both actors use the same viewport.
- Modes: `agent`, `human`, `shared`; human override is immediate.
- Recorder captures `navigate`, `click`, `type/fill`, `wait`, `scroll`, `screenshot`, selector fallbacks, and variables.
- Player supports variables, retries, timeouts, pause-on-failure, and step logs.
- Backend switching checks compatibility and warns before relaunch/migration.
- Human-in-loop supports pause, intervention reason, checkpoint resume, and status/chat.
- Sessions support named profiles, isolation, keep-alive, terminate, and refresh recovery.

## Security + Quality
- p95 action acknowledgement under 250ms.
- >=95% replay success on stable non-adversarial workflows.
- Password login with secure session cookie; no URL token auth.
- CSRF on state-changing routes, restricted CORS, and auditable control logs.
- Keep dependencies minimal for one VPS.

## Defaults
1. Browser persists across dashboard refresh.
2. Idle timeout is 30 minutes.
3. Workflow storage is Git-backed filesystem YAML.
4. Build live dashboard before recorder/player.

## Phase Gates
Phase 1: live browser, runtime manager, shared MCP control, switcher for `playwright-mcp` + `cdp-bridge`.
Gate: human click/type works, agent actions show live, switching needs no shell step.

Phase 2: YAML record/replay with selector fallback, variables, retries, and timeouts.
Gate: one 5+ step workflow replays end-to-end.

Phase 3: pause/resume, intervention queue, checkpoint resume, dashboard status/chat.
Gate: CAPTCHA interruption is resolved manually and execution continues.

Phase 4: named profiles, workflow library/tagging, scheduled runs, hardened `agentic-stealth-mcp`.
Gate: scheduled run executes on a named profile with an auditable log.

## Risk Controls
- CDP desync -> session broker + heartbeat reconciliation.
- Selector fragility -> multi-selector fallback + variable resolver.
- Security drift -> strict origin policy + audit logs.
- Backend mismatch -> adapter contract tests + capability matrix.

## Execution Directive
Implement in phase order. Do not skip gates. Preserve scope, anti-goals, and security rules. If blocked by invariant conflict, emit: blocker summary, smallest viable design change, and timeline/metric impact.
