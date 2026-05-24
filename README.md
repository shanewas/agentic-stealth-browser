# Agentic Stealth Browser

[![CI](https://github.com/shanewas/agentic-stealth-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/shanewas/agentic-stealth-browser/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)](https://pypi.org/project/agentic-stealth-browser/)
[![Tests](https://img.shields.io/badge/tests-880%2B%20passing-brightgreen)](tests/)

A Python framework that makes browser automation look human. Built for autonomous agents that need to navigate websites protected by Cloudflare, LinkedIn, Amazon, and other anti-bot systems. **v2.0.0 GA** — Workflow Platform with SDK, orchestration, security governance, adaptive stealth, plugin system, and full browser capability map.

## Why This Exists

Standard browser automation (`page.goto()`, `page.click()`) gets detected instantly. This framework solves that by combining:

- **TLS fingerprint spoofing** — matches real browser TLS handshakes
- **Human behavior simulation** — natural mouse, typing, scrolling with realistic imperfections
- **Automatic recovery** — detects blocks (CAPTCHAs, rate limits) and recovers without crashing
- **Account lifecycle management** — warming, health scoring, cooling off
- **Workflow Teach/Replay** — record real user actions via CDP, save as YAML, replay with fallbacks

## Installation

```bash
pip install agentic-stealth-browser
playwright install --with-deps chromium
```

## Quick Start

```python
from core.agent_browser import AgentBrowser
import asyncio

async def main():
    browser = AgentBrowser(session_name="demo")
    await browser.launch(headless=True)

    # This handles stealth, human behavior, and recovery automatically
    await browser.safe_goto("https://example.com")

    # Add human-like actions
    await browser.human.scroll_naturally(400)
    await browser.human.think(1500, 2800)

    await browser.close()

asyncio.run(main())
```

## Real-World Example

For protected sites, load real cookies and use a platform preset:

```python
browser = AgentBrowser(session_name="linkedin")
await browser.launch(preset="linkedin_2026")
await browser.load_cookies_from_file("cookies.json")
await browser.warm_up_before_work(intensity="heavy")
await browser.safe_goto("https://www.linkedin.com/feed/", platform="linkedin")
```

The flow: **cookies → warm-up → navigate → recover if blocked → act human**.

## Workflow System (v1.0.0)

Record real user interactions and replay them autonomously — the "teach mode" for browser automation.

### Teach — Record a Workflow

```python
from workflows.recorder import WorkflowRecorder

recorder = WorkflowRecorder(cdp_url="http://localhost:9222")
async with recorder:
    await recorder.start_capture()
    # User performs actions in their real browser...
    workflow = await recorder.stop_and_save("upwork_edit_title.yaml")
```

### Replay — Execute a Saved Workflow

```python
from workflows.player import WorkflowPlayer
from workflows.schema import load_workflow

workflow = load_workflow("workflows/library/upwork/edit-title.yaml")
player = WorkflowPlayer(browser, workflow)
result = await player.execute()
print(f"Done: {result.success} — {result.steps_passed}/{result.steps_total}")
```

### Workflow Library

Pre-built, production-tested workflows included out of the box:

| Workflow | Platform | What It Does |
|---|---|---|
| `edit-title` | Upwork | Updates profile title |
| `update-rate` | Upwork | Changes hourly rate |
| `add-portfolio` | Upwork | Adds portfolio item |
| `submit-proposal` | Upwork | Submits a proposal |
| `send-connection-request` | LinkedIn | Sends connection request |

### From MCP (AI Agent)

```json
{
  "tool": "stealth_teach",
  "args": { "session_name": "my-flow", "cdp_url": "http://localhost:9222" }
}
```

```json
{
  "tool": "stealth_replay",
  "args": { "workflow_path": "upwork/edit-title.yaml" }
}
```

### Workflow Schema

Each workflow is a YAML file with typed steps. 13 step types supported:

`navigate` · `click` · `fill` · `type` · `select` · `verify` · `wait` · `wait_for_element` · `scroll` · `screenshot` · `execute_js` · `conditional` · `run_workflow`

Variables (`{{variable}}`) resolve at runtime with built-in support for `timestamp`, `date`, `random_name`, `last_url`.

## Workflow Orchestrator (v1.3.0)

Schedule, queue, and chain workflow execution with domain-aware concurrency control:

```python
from production.workflow_orchestrator import WorkflowOrchestrator

orchestrator = WorkflowOrchestrator(
    max_concurrent_total=5,
    domain_concurrency={"linkedin.com": 1, "default": 3},
)

# Enqueue a single job
job = await orchestrator.enqueue(
    workflow_path="workflows/upwork/edit-title.yaml",
    domain="upwork.com",
    account="my_account",
    priority=10,
)

# Schedule recurring execution
await orchestrator.schedule_recurring(
    workflow_path="workflows/linkedin/check-notifications.yaml",
    interval_seconds=3600,  # every hour
    domain="linkedin.com",
)

# Start the event loop
await orchestrator.run()
```

Features:
- **Priority queue** — high-priority jobs execute first
- **Domain concurrency limits** — avoid rate-limiting (e.g., max 1 concurrent LinkedIn job)
- **Automatic retries** — exponential backoff (configurable max retries and backoff base)
- **Checkpoint persistence** — queue state survives restarts via JSON checkpoints
- **Batch enqueue** — submit multiple jobs atomically
- **Recurring jobs** — periodic execution with enable/disable toggles

## Python SDK (v1.6.0)

Use the stealth framework programmatically without MCP. The `StealthClient` provides a clean async API:

```python
from production.sdk import StealthClient

# Simple session
async with StealthClient(session_name="mybot") as client:
    res = await client.navigate("https://example.com")
    data = await client.scrape("https://example.com/items")

# Workflow execution
client = StealthClient()
result = await client.execute_workflow(
    "linkedin/send-connection-request",
    variables={"name": "Jane Doe"},
)
print(f"Done: {result['success']} — {result['steps_executed']}/{result['total_steps']}")
```

The SDK also includes `WorkflowContext` for scoped sessions and `list_workflows()` for library discovery.

## Plugin System (v2.0.0)

Extend the framework with custom hooks. Plugins receive a `PluginContext` with access to the browser session and logger:

```python
from plugins.template import ExamplePlugin

class MyPlugin(ExamplePlugin):
    name = "my-plugin"
    version = "0.1.0"

    async def on_navigate(self, ctx, url):
        ctx.logger.info(f"[{self.name}] Navigating to {url}")
```

Available hooks: `on_launch`, `on_navigate`, `on_page_loaded`, `on_scraped`, `on_close`.

## Security & Governance (v1.4.0)

### Input Validation

All MCP tool inputs are validated against declarative schemas — type checks, length constraints, allowed values, URL patterns:

```python
from production.mcp_input_validator import validate_tool_input

validate_tool_input("stealth_navigate", {"url": "https://example.com"})
# Raises InputValidationError if invalid
```

### Session Isolation

Each MCP client context is bound to exactly one session. Cross-session access is blocked:

```python
from production.mcp_session_isolation import SessionEnforcer

enforcer = SessionEnforcer()
binding = await enforcer.bind_session("my-session", context_token)
await enforcer.check_access("my-session", context_token)  # passes
await enforcer.check_access("other-session", context_token)  # raises SessionIsolationError
```

### Policy Engine

YAML-based access control for workflow execution. Define which sites, step types, and actions are allowed per policy:

```bash
# ~/.agentic-browser/policies/example.yaml
name: "example"
default_allow: false
allowed_step_types: [navigate, click, fill, verify]
blocked_step_types: [execute_js]
domain_rules:
  - domain: linkedin.com
    allow: true
    paths: ["/feed", "/jobs"]
```

### Approval Gates

Sensitive actions (navigate to unknown domain, execute_js, launch) can require explicit approval:

```python
from production.approval_gate import ApprovalGate, ApprovalDecision

gate = ApprovalGate(auto_approve_known_domains=True)
result = gate.check_sensitive("stealth_navigate", {"url": "https://unknown-site.com"})
if result.decision == ApprovalDecision.PENDING:
    print("Awaiting interactive approval...")
```

## Adaptive Stealth & FeedbackStore (v1.8.0)

The framework learns from its own execution. `FeedbackStore` persists telemetry from replay and recovery events, allowing domain-specific tuning:

```python
from behavior.adaptive_tuner import AdaptiveTuner

tuner = AdaptiveTuner()
profile = tuner.get_profile("linkedin.com")
# Returns tuned values for typing speed, mouse variance, scroll behavior, etc.
```

Key features:
- **Per-domain behavior profiles** — LinkedIn, Upwork, and generic profiles with bounded adaptation
- **Selector success tracking** — identifies which selectors fail per domain and auto-adjusts
- **Detection event logging** — captures block types per domain for continuous improvement
- **Stealth evaluation harness** (`scripts/evaluate_stealth.py`) — comparative patched vs. baseline testing with reproducibility gates

## Feature Flags & Browser Capabilities (v1.7.0)

Runtime feature discovery. Use `get_client_capabilities()` to check what's available for the current backend:

```python
from core.feature_flags import get_client_capabilities, is_firefox_supported

caps = get_client_capabilities()
# {
#   "browser_backend": "chromium",
#   "stealth_injection": True,
#   "tls_spoofing": True,
#   "human_behavior": True,
#   "firefox_support": False,
#   ...
# }
```

Environment-flag controlled: `STEALTH_FIREFOX_SUPPORT=true`, `STEALTH_EDGE_SUPPORT=true`, `STEALTH_ADAPTIVE_TUNING=false`, etc.

Full capability matrix available at [`docs/CAPABILITY_MAP.md`](docs/CAPABILITY_MAP.md).

## Profiling & Benchmarking (v1.5.0)

Low-overhead timing decorators for hot-path analysis:

```python
from production.profiler import Profiler

profiler = Profiler()

# Context manager
with profiler.measure("safe_goto"):
    await browser.safe_goto("https://example.com")

# Async decorator
@timing_decorator(profiler)
async def my_function():
    ...

print(profiler.get_summary())
# {"safe_goto": {"count": 1, "avg": 1.234, "p95": 1.567, ...}}
```

Run the built-in benchmark:
```bash
python scripts/perf_benchmark.py --iterations 10 --warmup 3
```

## Migration from v1.x (v1.9.0)

v2.0.0 includes backward-compatibility shims and a migration script:

```bash
# Convert a v1 workflow to v2 format
python scripts/migrate_v1_to_v2.py \
    --input workflows/library/my-workflow.yaml \
    --output workflows/library/my-workflow-v2.yaml

# Validate compatibility
python scripts/migrate_v1_to_v2.py \
    --validate --input workflows/library/my-workflow.yaml
```

### Breaking Changes in v2.0.0

| Change | Deprecated | Replacement | Removal |
|---|---|---|---|
| `AgentBrowser.context` | v2.0.0 | `AgentBrowser.browser_context` | v2.1.0 |
| `ConnectionPool` | v2.0.0 | `NavigationHistory` | v2.1.0 |
| Ad-hoc MCP response shapes | v2.0.0 | `unified_result_envelope` | v2.1.0 |
| Naive datetime in rate_limiter/metrics | v2.0.0 | timezone-aware UTC / `time.monotonic()` | v2.1.0 |

See [`docs/rfc/v2-migration.md`](docs/rfc/v2-migration.md) for the full migration guide and [`production/deprecations.py`](production/deprecations.py) for deprecation shims.

## Remote Bridge

Connect the stealth framework to a browser running on another machine — ideal for keeping cookies/sessions on your local Windows PC while the agent runs on a VPS.

```
Windows (Edge + CDP)  ←ngrok→  VPS (Agentic Stealth Browser)
```

Setup scripts included for both Linux (`scripts/setup_rbb.sh`) and Windows (`scripts/setup_rbb.ps1`). Requires Edge/Chrome launched with `--remote-debugging-port=9222`.

See [docs/OPERATOR_SETUP.md](docs/OPERATOR_SETUP.md) for full setup guide, failure modes, and backend selection.

## How It Works

```
AgentBrowser
├── Stealth      → TLS profiles, canvas/WebGL spoofing, WebRTC isolation
├── Behavior     → Bézier mouse, natural typing, distraction simulation
├── Recovery     → Detects blocks → rotates proxy/session → retries
├── Accounts     → Health scoring, 14-day warming, session checkpointing
├── Proxy        → Residential proxy with rotation and health tracking
├── Workflows    → Record, replay, library, orchestration, scheduling
├── SDK          → Programmatic async client (no MCP dependency)
├── Security     → Input validation, session isolation, policy engine, approval gates
├── Plugins      → Custom lifecycle hooks (launch, navigate, close)
└── Profiling    → Timing instrumentation and performance benchmarking

Remote Bridge (optional)
└── CDP Proxy    → Connect to local browser from VPS via ngrok
```

## Key Features

| Feature | What It Does | Added |
|---|---|---|
| **TLS Fingerprinting** | Region-specific profiles (US, Japan, EU, Korea) with JA3/JA4 support | v0.8 |
| **Human Behavior** | Mouse with wobble, typing with mistakes, variable scrolling, fatigue | v0.8 |
| **Auto Recovery** | Detects CAPTCHAs, rate limits, blocks — recovers automatically | v0.8 |
| **Account Warming** | 14-day gradual ramp-up so new accounts don't get flagged | v0.8 |
| **Session Checkpoints** | Export/import browser state for cross-host migration | v0.8 |
| **Platform Presets** | Pre-configured profiles for LinkedIn, Amazon, Cloudflare | v0.8 |
| **Workflow Recorder** | Capture real user actions via CDP → reproducible YAML workflows | v1.0 |
| **Workflow Player** | Execute workflows with fallback selectors, retries, checkpoint resumption | v1.0 |
| **Workflow Library** | Pre-built workflows for Upwork, LinkedIn — usable immediately | v1.0 |
| **Remote Bridge** | Drive a local Windows browser from a VPS via CDP + ngrok | v1.0 |
| **Selector Auto-Heal** | When a CSS selector fails, automatically generates working alternatives | v1.2 |
| **Rehearsal Mode** | Dry-run workflows without side effects — validates selectors, logs issues | v1.2 |
| **Workflow Versioning** | Semantic versioning for workflow definitions with change tracking | v1.2 |
| **Workflow Orchestrator** | Queue/schedule/chaining with domain concurrency limits, retries, persistence | v1.3 |
| **MCP Input Validation** | Type, length, pattern checks on all MCP tool parameters | v1.4 |
| **Session Isolation** | One context cannot access another's browser instances | v1.4 |
| **Policy Engine** | YAML-based access control for sites, step types, and actions | v1.4 |
| **Approval Gates** | Sensitive actions (navigate, execute_js) require explicit approval | v1.4 |
| **Audit Enrichment** | Actor/session/workflow correlation in structured audit logs | v1.4 |
| **Performance Profiling** | Timing decorators and context managers for hot-path measurement | v1.5 |
| **Python SDK** | `StealthClient` — programmatic API without MCP dependency | v1.6 |
| **Plugin System** | Custom lifecycle hooks via BasePlugin (launch, navigate, scrape, close) | v2.0* |
| **Browser Capability Map** | Feature matrix across Chromium/Edge/Firefox backends | v1.7 |
| **Feature Flags** | Runtime toggles for browser-specific capability gating | v1.7 |
| **Firefox Adapter** | Feature-flagged Firefox support with basic stealth injection | v1.7 |
| **FeedbackStore** | Telemetry for selector success rates, detection events per domain | v1.8 |
| **Adaptive Tuning** | Per-domain behavior profiles with bounded adaptation | v1.8 |
| **Stealth Evaluation** | Script for comparative patched vs. baseline testing | v1.8 |
| **Migration Tools** | v1→v2 migration script, deprecation shims, migration guide | v1.9 |

\* Plugin system was finalized as part of the v2 GA release.

## MCP Setup

Use this framework with AI agents (Claude Desktop, Cursor, Windsurf, etc.) via MCP.

### 1. Install the MCP Server

```bash
pip install agentic-stealth-browser
```

### 2. Configure Your MCP Client

**Claude Desktop** — Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "stealth-browser": {
      "command": "python",
      "args": ["-m", "production.mcp_server"],
      "env": {}
    }
  }
}
```

**Cursor / Windsurf** — Add to `.cursorrules` or MCP settings:

```json
{
  "mcpServers": {
    "stealth-browser": {
      "command": "python",
      "args": ["-m", "production.mcp_server"]
    }
  }
}
```

### 3. Available MCP Tools

| Tool | Description | Added |
|---|---|---|
| `stealth_launch` | Launch browser with stealth + region preset | v0.8 |
| `stealth_navigate` | Navigate with full recovery and human behavior | v0.8 |
| `stealth_load_cookies` | Load cookies from real browser | v0.8 |
| `stealth_set_region` | Switch TLS fingerprint region (US, Japan, EU, Korea) | v0.8 |
| `stealth_scrape` | Navigate and extract page content | v0.8 |
| `stealth_status` | Check browser health and session state | v0.8 |
| `stealth_capabilities` | Show MCP server/runtime version and available tools | v0.9 |
| `stealth_tabs_list` | List open tabs/pages and active tab metadata | v0.9 |
| `stealth_tab_snapshot` | Capture screenshot + metadata for a specific tab/page | v0.9 |
| `stealth_session_timeline` | Fetch replay/timeline events for debugging and recovery analysis | v0.9 |
| `stealth_debug_report` | Return full debug report payload for current session | v0.9 |
| `stealth_close` | Close browser and cleanup | v0.8 |
| `stealth_teach` | Start recording a workflow session (CDP capture → YAML) | v1.0 |
| `stealth_replay` | Execute a saved workflow by name or path | v1.0 |
| `stealth_workflow_list` | List available workflows in the library | v1.0 |
| `stealth_workflow_delete` | Delete a workflow from the library | v1.0 |

> **Operator Guide**: For detailed workflows on observing what the MCP-driven browser is actually doing (tabs, snapshots, timelines, debug reports, security notes, CDP fallbacks), see [docs/MCP_BROWSER_OBSERVABILITY.md](docs/MCP_BROWSER_OBSERVABILITY.md).

### 4. MCP Server Environment Variables

| Variable | Description | Default |
|---|---|---|
| `STEALTH_MCP_ALLOWED_DIRS` | Extra allowed directories for MCP file-access policy (comma/semicolon separated) | _(empty)_ |
| `STEALTH_MCP_SNAPSHOT_DIR` | Snapshot output root for `stealth_tab_snapshot` | `~/.agentic-browser/mcp_snapshots` |
| `STEALTH_MCP_SNAPSHOT_MAX_PER_SESSION` | Max screenshots retained per session directory (older files are pruned) | `20` |
| `STEALTH_MCP_TIMELINE_DEFAULT_LIMIT` | Default event limit when `stealth_session_timeline` is called without `limit` | `30` |
| `STEALTH_MCP_TIMELINE_MAX_LIMIT` | Hard upper bound for `stealth_session_timeline.limit` | `200` |
| `STEALTH_MCP_OBSERVABILITY_MAX_CHARS` | Max serialized response size for observability payloads before truncation | `50000` |

## Configuration

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `STEALTH_REGION` | TLS fingerprint region | `japan` |
| `STEALTH_HEADLESS` | Run browser headless | `true` |
| `STEALTH_PROXY` | Use residential proxy | `false` |
| `STEALTH_FIREFOX_SUPPORT` | Enable Firefox backend (experimental) | `false` |
| `STEALTH_EDGE_SUPPORT` | Enable Edge backend | `true` |
| `STEALTH_ADAPTIVE_TUNING` | Enable per-domain adaptive behavior tuning | `true` |
| `STEALTH_PLUGIN_SYSTEM` | Enable the plugin hook system | `true` |
| `STEALTH_LEARNING_LOOP` | Enable feedback-based learning (experimental) | `false` |

### Platform Presets

```python
await browser.launch(preset="linkedin_2026")   # LinkedIn
await browser.launch(preset="amazon_2026")     # Amazon
await browser.launch(preset="cloudflare")      # Cloudflare-protected sites
```

## Project Structure

```
agentic-stealth-browser/
├── core/             # AgentBrowser main class, session checkpoint, connection pool
├── stealth/          # TLS fingerprinting, script injection, Firefox adapter, caching
├── behavior/         # Human-like mouse, typing, scrolling, personas, adaptive tuning
├── recovery/         # Block detection, anti-block orchestrator
├── proxy/            # Proxy management and rotation
├── sessions/         # Session and cookie management
├── workflows/        # Teach/Replay workflow system
│   ├── recorder.py, player.py, schema.py, recovery.py
│   ├── variable_resolver.py, selector_generator.py, action_interpreter.py
│   └── library/      # Pre-built workflows (Upwork, LinkedIn)
├── production/       # CLI, Docker, MCP server, security, orchestration, SDK
│   ├── mcp_server.py         # MCP server (stdio-based)
│   ├── mcp_input_validator.py # Param type/length/pattern validation
│   ├── mcp_session_isolation.py # Cross-session data isolation
│   ├── workflow_orchestrator.py # Queue, schedule, chaining
│   ├── policy_engine.py       # YAML-based access control
│   ├── approval_gate.py       # Sensitive action approval hooks
│   ├── audit_enrichment.py    # Actor/session/workflow correlation
│   ├── profiler.py            # Timing instrumentation
│   ├── deprecations.py        # v1→v2 backward-compat shims
│   ├── rate_limiter.py        # Domain-aware rate limiting
│   ├── metrics.py             # Metrics collector
│   ├── cli.py                 # CLI entry points
│   ├── sdk/                   # Python SDK (StealthClient)
│   └── otel_export.py         # OpenTelemetry export
├── plugins/          # Plugin system
│   └── template/     # BasePlugin example with lifecycle hooks
├── ai/               # AI hooks and content analysis
├── audit/            # Structured logging and audit trails
├── linkedin/         # LinkedIn-specific actions
├── scraping/         # Safe page scraping utilities
├── scripts/          # Deployment, migration, benchmarking, evaluation
│   ├── migrate_v1_to_v2.py   # Workflow migration script
│   ├── evaluate_stealth.py   # Patched vs baseline testing
│   └── perf_benchmark.py     # Performance benchmark
├── docs/             # Architecture Decision Records, RFCs, and guides
│   ├── adr/                  # Architecture Decision Records
│   ├── rfc/                  # RFCs (v2-migration, etc.)
│   └── CAPABILITY_MAP.md     # Feature matrix across backends
├── tests/            # 880+ tests across 50+ files
│   ├── test_workflow_orchestrator.py
│   ├── test_mcp_server_runtime.py
│   ├── test_mcp_stealth_workflows.py
│   └── ...
└── mcp_security.py   # MCP security utilities
```

## Documentation

- [Architecture Decision Records](docs/adr/)
- [Operator Setup Guide](docs/OPERATOR_SETUP.md)
- [MCP Browser Observability](docs/MCP_BROWSER_OBSERVABILITY.md)
- [Visual Debugging Guide](docs/VISUAL_DEBUGGING.md)
- [Stealth Limitations](docs/STEALTH_LIMITATIONS.md)
- [Threat Model](docs/THREAT_MODEL.md)
- [Common Pitfalls](docs/COMMON_PITFALLS.md)
- [Rate Limiting & Backoff](docs/RATE_LIMITING_BACKOFF.md)
- [Cookie & Session Resilience](docs/COOKIE_SESSION_RESILIENCE.md)
- [Browser Capability Map](docs/CAPABILITY_MAP.md)
- [v2 Migration RFC](docs/rfc/v2-migration.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License. See [LICENSE](LICENSE) for details.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full release history.
