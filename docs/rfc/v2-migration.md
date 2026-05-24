# v2.0.0 Migration RFC

## Status: Accepted
## Date: 2026-05-24
## Author: Agentic Stealth Browser Team

---

## Summary

This RFC describes all planned breaking changes between v1.x and v2.0.0. The goal is a cleaner,
more consistent API surface with explicit contracts, unified execution envelopes, and removal of
deprecated compatibility shims accumulated during the v1.x lifecycle.

---

## Motivation

v1.x grew organically from 0.1.0 through 1.9.0, accumulating:

- **Backward-compat aliases** (e.g., `self.context` alias in `AgentBrowser`)
- **Ad-hoc response shapes** across MCP tools lacking a unified envelope
- **Legacy naming** (e.g., `ConnectionPool` was renamed to `NavigationHistory` in v1.0.0)
- **Inconsistent error contracts** between CLI, SDK, and MCP surfaces

v2.0.0 consolidates these into a strict, typed, unified contract.

---

## Breaking Changes

### 1. `AgentBrowser` Class

| v1.x API | v2.0.0 Replacement | Notes |
|---|---|---|
| `browser.context` (alias) | `browser.browser_context` | `#93` deprecated alias removed |
| `browser.page_getter()` | `browser.page` (property) | Getter pattern consolidated |
| `ConnectionPool` import | `NavigationHistory` | Rename finalized |

**Removed:**
- `self.context` deprecated alias in `agent_browser.py` (line 207)
- `ConnectionPool` backward-compat re-export

### 2. MCP Response Envelope

**v1.x:** Ad-hoc payload shapes per tool.

**v2.0.0:** All MCP tool results wrapped in a unified envelope:

```json
{
  "status": "success",
  "data": { ... tool-specific payload ... },
  "meta": {
    "tool": "stealth_launch",
    "server_version": "2.0.0"
  }
}
```

Error responses:

```json
{
  "status": "error",
  "data": {
    "error_code": "MCP_SESSION_REQUIRED",
    "message": "No active session selected.",
    "details": {}
  },
  "meta": {
    "tool": "stealth_navigate",
    "server_version": "2.0.0"
  }
}
```

### 3. SDK Client

v2.0.0 introduces the `production.sdk.StealthClient` as the canonical programmatic API.
Direct `AgentBrowser` usage is still supported but the SDK wraps it with:
- Unified result types (`ClientScrapeResult`, `ClientStatusResult`)
- Context-managed sessions
- Workflow execution API

### 4. Workflow Schema v2

| v1.x | v2.0.0 |
|---|---|
| YAML workflows with loose typing | Stricter typing, explicit variable contracts |
| `workflow_to_yaml_str()` | `workflow_to_yaml_v2()` |
| Optional platform metadata | Required `platform` field |

### 5. Plugin System

v2.0.0 formalizes the plugin interface introduced in v1.6.0:
- `BasePlugin` with standardized hooks (`on_launch`, `on_navigate`, `on_page_loaded`, `on_scraped`, `on_close`)
- `PluginContext` injection with session, logger, config
- Plugin loading via `stealth_plugin` entry points

### 6. Removed Deprecated Items

| v1.x Item | Removal Reason |
|---|---|
| `self.context` alias | Superseded by `self.browser_context` (#93) |
| `ConnectionPool` re-export | Renamed to `NavigationHistory` (#374) |
| `_BrowserPool` internal `use_pooled_context` backward-compat flag | Default now `False`, behavior unchanged |
| `rate_limiter.py` naive datetime usage | All datetimes now timezone-aware UTC |
| `metrics.py` naive datetime for uptime | Switched to `time.monotonic` |

---

## Compatibility Shims

During the v1.9.0 → v2.0.0 transition, all deprecated APIs emit `DeprecationWarning`
at the `warn` log level. Shims are provided in `production/deprecations.py` and will
be removed in v2.1.0.

To migrate, use the helper script:
```bash
python scripts/migrate_v1_to_v2.py --input my_workflow.yaml --output my_workflow_v2.yaml
```

---

## Timeline

| Version | Date | Action |
|---|---|---|
| v1.9.0 | 2026-05-24 | Deprecation warnings active; migration scripts available |
| v2.0.0-rc | 2026-05-24 | Release candidate; no more breaking changes |
| v2.0.0 | 2026-05-24 | GA; all deprecated items removed |
| v2.1.0 | TBD | Compatibility shims removed |

---

## CI Migration Check

A CI step in `.github/workflows/ci.yml` validates:
1. All v1 workflow YAMLs load correctly under v2 shims
2. No deprecated imports are used in new code
3. Migration script produces valid v2 output from v1 input
