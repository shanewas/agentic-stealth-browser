# Hermes Browser Dashboard

The Hermes Browser Dashboard is a single-user operator console for sharing one
live Chromium session between a human operator and Nova/Hermes.

## What It Provides

- FastAPI dashboard with a live browser panel, status bar, controls, and event timeline.
- One managed Chromium runtime with start, stop, restart, health, and best-effort restore hooks.
- Backend adapter contract for `playwright-mcp`, `agentic-stealth-mcp`, and `cdp-bridge`.
- YAML workflow recording/replay through the existing workflow engine.
- Human-in-the-loop pause, intervention reason, checkpoint resume, and timeline logging.
- Password login, secure session cookie, CSRF checks, restricted CORS, and control-plane audit events.

## Start

```bash
export HERMES_DASHBOARD_PASSWORD='replace-me'
agentic-stealth-browser dashboard --host 127.0.0.1 --port 8443
```

Open `http://127.0.0.1:8443` in Edge and log in with the configured password.

## Live Browser Strategy

The first implementation uses Chromium CDP remote debugging when the active
backend is `cdp-bridge`. The dashboard derives a Chrome DevTools frontend URL
from the CDP WebSocket endpoint and embeds it as the live control surface.

This keeps the design aligned with the anti-goal of no VNC/RDP/video streaming.
If a deployment cannot embed the DevTools frontend due to browser security
policy or proxy layout, keep the runtime/adapters/workflow layers and replace
only the live-view transport.

## Operator Flow

1. Start the dashboard.
2. Start or restart the managed browser.
3. Use shared mode while Nova automates and the operator watches.
4. Switch to human mode or pause when CAPTCHA/login/DOM uncertainty appears.
5. Resolve the page manually, mark the intervention resolved, then resume.
6. Record a demonstrated workflow and save it as YAML.
7. Replay the workflow against the active profile/backend.

## Storage

Dashboard state is filesystem-first under `~/.agentic-browser/hermes_dashboard`:

- `workflows/` stores Git-friendly YAML workflows.
- `profiles/` stores named profile directories.
- `runs/` is reserved for run outputs and exported logs.

## Release Gate

Before considering this feature release-ready, verify:

- Dashboard auth and CSRF tests pass.
- Runtime manager contract tests pass with fake browser adapters.
- Workflow record/replay passes without live protected sites.
- MCP tools still list and existing workflow tests still pass.
