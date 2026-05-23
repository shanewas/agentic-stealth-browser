# Operator Setup Guide — Agentic Stealth Browser

This guide covers deploying and operating the Agentic Stealth Browser with MCP tools, workflow execution, and the Remote Browser Bridge (RBB).

## Prerequisites

| Requirement | Version | Install |
|---|---|---|
| Python | 3.11+ | [python.org](https://python.org) |
| Playwright | Latest | `pip install playwright && playwright install --with-deps chromium` |
| cloudflared | Latest | `curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared` |
| Git | Any | `apt install git` / `brew install git` |

Optional but recommended: `nssm` (Windows service manager), `jq` (JSON processing).

## Quick Start

```bash
# Clone and install
git clone https://github.com/shanewas/agentic-stealth-browser.git
cd agentic-stealth-browser
pip install -e .

# Run the MCP server
python -m production.mcp_server
```

The MCP server accepts JSON-RPC 2.0 over stdio. Connect your MCP client (Claude Desktop, Cursor, etc.) with the following config:

```json
{
  "mcpServers": {
    "stealth-browser": {
      "command": "python",
      "args": ["-m", "production.mcp_server"],
      "cwd": "/path/to/agentic-stealth-browser"
    }
  }
}
```

## MCP Tools Reference

The server exposes 17 tools. Key workflow-related tools:

| Tool | Description | Primary Args |
|---|---|---|
| `stealth_launch` | Launch browser with stealth + persona | `session_name`, `preset`, `region` |
| `stealth_navigate` | Navigate with recovery | `url`, `session_name` |
| `stealth_replay` | Execute a saved workflow | `workflow_path`, `session_name`, `variables` |
| `stealth_teach` | Record browser actions into a workflow | `session_name`, `workflow_name` |
| `stealth_workflow_list` | List available workflow files | `platform`, `pattern` |
| `stealth_workflow_delete` | Delete a workflow file | `workflow_path` |
| `stealth_status` | Health/status snapshot | `session_name` |
| `stealth_capabilities` | Server/runtime capabilities | _(none)_ |
| `stealth_close` | Close active session | `session_name` |

**Example: Replay a workflow**

```json
{
  "method": "tools/call",
  "params": {
    "name": "stealth_replay",
    "arguments": {
      "workflow_path": "upwork/edit-title.yaml",
      "session_name": "my-session",
      "variables": {
        "title": "Senior ML Engineer | LLMs & Infrastructure"
      }
    }
  }
}
```

**Example: Record a new workflow**

```json
{
  "method": "tools/call",
  "params": {
    "name": "stealth_teach",
    "arguments": {
      "session_name": "teaching-session",
      "workflow_name": "my-custom-workflow"
    }
  }
}
```

## Bridge Setup (RBB — Remote Browser Bridge)

The Remote Browser Bridge exposes the MCP server and browser over a cloudflared tunnel for remote access.

### Automated Setup (Linux)

```bash
chmod +x scripts/setup_rbb.sh
sudo STEALTH_RBB_TUNNEL_TOKEN="your-token" ./scripts/setup_rbb.sh
```

This will:
- Check Python, Playwright, and cloudflared prerequisites
- Install the bridge to `/opt/stealth-rbb`
- Create a systemd service `stealth-rbb`
- Configure a cloudflared tunnel
- Enable and start the service

### Automated Setup (Windows)

```powershell
# Run as Administrator
$env:STEALTH_RBB_TUNNEL_TOKEN = "your-token"
.\scripts\setup_rbb.ps1
```

### Manual Bridge Setup

1. **Create the cloudflared tunnel** at [Cloudflare Zero Trust](https://one.dash.cloudflare.com/)
2. **Install cloudflared** on the host
3. **Create `/etc/systemd/system/stealth-rbb.service`** (see template below)
4. **Enable and start**: `systemctl enable --now stealth-rbb`

### Systemd Service Template

```ini
[Unit]
Description=Stealth Browser Remote Bridge
After=network-online.target

[Service]
Type=simple
Environment=STEALTH_RBB_PORT=9222
Environment=STEALTH_MCP_SNAPSHOT_DIR=/var/log/stealth-rbb
ExecStart=/opt/stealth-rbb/run_bridge.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

### cloudflared Config Template

```yaml
tunnel: stealth-browser
credentials-file: /root/.cloudflared/stealth-browser.json

ingress:
  - hostname: stealth-bridge.yourdomain.com
    service: http://localhost:9222
  - service: http_status:404
```

## Workflow Library Overview

All workflows live under `workflows/library/`. Variables use `{{variable_name}}` syntax and support runtime overrides.

### Upwork Workflows

| File | Name | Purpose | Variables |
|---|---|---|---|
| `upwork/edit-title.yaml` | upwork-edit-title | Edit freelancer profile title | `title` (default: "Senior Backend Engineer \| Python, AI & Automation") |
| `upwork/update-rate.yaml` | upwork-update-rate | Update hourly rate | `rate` (default: "34.00") |
| `upwork/add-portfolio-item.yaml` | upwork-add-portfolio | Add portfolio item | `portfolio_title`, `portfolio_description` |
| `upwork/submit-proposal.yaml` | upwork-submit-proposal | Submit proposal to job | `job_url` **(required)**, `cover_letter`, `hourly_rate` |
| `upwork/apply.yaml` | apply | Placeholder for apply flow | _(none)_ |

### LinkedIn Workflows

| File | Name | Purpose | Variables |
|---|---|---|---|
| `linkedin/send-connection-request.yaml` | linkedin-send-connection | Send connection request with optional note | `profile_url` **(required)**, `note` (default: generic intro) |

### Common Workflows

| File | Name | Purpose |
|---|---|---|
| `common/login.yaml` | login | Placeholder for login flow |
| `common/verify-email.yaml` | verify-email | Placeholder for email verification |

### Creating Custom Workflows

Workflows are YAML files. Supported step types: `navigate`, `click`, `fill`, `type`, `select`, `verify`, `wait`, `wait_for_element`, `scroll`, `screenshot`, `execute_js`, `conditional`, `run_workflow`.

Minimal example:

```yaml
name: my-workflow
description: What this workflow does
variables:
  target_url:
    type: string
    required: true
    description: Where to navigate
steps:
  - type: navigate
    url: "{{target_url}}"
    timeout: 30000
  - type: wait_for_element
    selector: main
    timeout: 15000
    state: visible
  - type: click
    selector: ".cta-button"
    timeout: 10000
    wait_after: 1500
```

Validate your workflow:

```bash
python -c "from workflows.schema import load_workflow, validate_workflow; w = load_workflow('path/to/workflow.yaml'); r = validate_workflow(w); assert r.valid, r.errors"
```

## Health Monitoring

Run the health check script:

```bash
python scripts/health_check.py
```

Example output:

```json
{
  "status": "healthy",
  "checks": {
    "mcp_server": {"running": true, "details": "MCP stdio server available"},
    "workflow_library": {"accessible": true, "workflow_count": 8},
    "bridge": {"status": "connected", "port": 9222},
    "disk": {"total_gb": 50, "free_gb": 25, "used_percent": 50},
    "memory": {"total_gb": 8, "available_gb": 4, "used_percent": 50}
  },
  "timestamp": "2026-05-24T00:00:00Z"
}
```

## Troubleshooting

### Common Issues

| Symptom | Likely Cause | Action |
|---|---|---|
| MCP server won't start | Missing Python / Playwright | `pip install -e . && playwright install chromium` |
| Workflow replay fails: "element not found" | Selector doesn't match page | Check the page DOM; update selectors in the workflow YAML |
| `stealth_replay` returns "workflow not found" | Wrong path | Use `stealth_workflow_list` to see available files |
| Bridge logs show connection refused | Service not running | `systemctl --user status stealth-rbb` |
| Tunnel returns 502 | Bridge port mismatch | Check `BRIDGE_PORT` in service file matches cloudflared ingress |
| "Block detected" during workflow | Anti-bot trigger | Recovery layer handles this automatically; check `recovery_used: true` in result |
| Disk full | Screenshot/snapshot accumulation | Clear old snapshots from `~/.agentic-browser/mcp_snapshots/` |
| cloudflared certificate errors | Expired or missing cert | `cloudflared tunnel delete stealth-browser && cloudflared tunnel create stealth-browser` |

### Log Locations

| Component | Log Path | Content |
|---|---|---|
| MCP Server | stdout (stdio mode) | JSON-RPC requests/responses |
| RBB Service (Linux) | `/var/log/stealth-rbb/bridge.log` | Bridge stdout |
| RBB Service (Linux) | `/var/log/stealth-rbb/bridge-error.log` | Bridge stderr |
| RBB Service (Windows) | `%ProgramData%\StealthRBB\logs\` | Bridge logs |
| Cloudflared | systemd journal / event log | Tunnel connectivity |
| Playwright | `~/.cache/ms-playwright/` | Browser binary, profiles |
| Snapshots | `~/.agentic-browser/mcp_snapshots/` | Per-tab screenshots |
| Checkpoints | `checkpoints/` (project root) | Workflow resume state |

### Recovery Flow

When a step fails, the system applies recovery in this order:

1. **Element Not Found** — retries with selector, tries `selector_fallbacks` from the step config
2. **Timeout** — doubles the step timeout and retries; may call `AntiBlockOrchestrator`
3. **Block Detected** (CAPTCHA, rate limit, Cloudflare challenge) — delegates to `AntiBlockOrchestrator` which may rotate proxy, swap session, or cool down

Recovery results are reported in `ExecutionResult.recovery_used` and `recovery_actions`.

## Bridge vs Stealth Backend

| Aspect | Bridge (RBB) | Direct Backend |
|---|---|---|
| Access | Remote (via cloudflared tunnel) | Local (same machine) |
| Setup | Service + tunnel configuration | `pip install -e .` |
| Use case | Remote agents, distributed workflows, team access | Local development, single-machine automation |
| Security | Cloudflare Zero Trust, token auth | Local process only |
| Latency | ~50-200ms (tunnel overhead) | <5ms |
| Resilience | Auto-restart via systemd | Manual restart |
| When to use | Production deployments, shared browser pools, CI/CD | Development, testing, personal scripts |

## Expected Failure Modes

1. **Network blips** — Workflows with `timeout` values will retry; `verify` steps confirm state before proceeding.
2. **DOM changes** — Selectors may break when sites update their HTML. Use `selector_fallbacks` for resilience. Update workflow YAMLs and re-teach as needed.
3. **Session expiration** — Cookies expire after ~14 days without warming. Use `stealth_load_cookies` to restore or re-login manually.
4. **Rate limiting** — Sites may throttle after rapid actions. The `wait` step type adds delays; behavior layer adds natural jitter.
5. **CAPTCHA challenges** — The `AntiBlockOrchestrator` detects these and rotates session/proxy.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `STEALTH_HEADLESS` | `true` | Run browser in headless mode |
| `STEALTH_REGION` | `global` | TLS fingerprint region |
| `STEALTH_RBB_PORT` | `9222` | Bridge CDP port |
| `STEALTH_RBB_NAMESPACE` | `stealth-browser` | Cloudflare tunnel namespace |
| `STEALTH_RBB_TUNNEL_TOKEN` | _(none)_ | Cloudflare tunnel token |
| `STEALTH_RBB_HOSTNAME` | _(none)_ | Public hostname for tunnel ingress |
| `STEALTH_MCP_SNAPSHOT_DIR` | `~/.agentic-browser/mcp_snapshots` | Snapshot storage |
| `STEALTH_MCP_ALLOWED_DIRS` | _(none)_ | Extra dirs allowed for file access |
| `DATA_DIR` | _(none)_ | Root for sessions, logs, cookies |
