# MCP Browser Observability Guide

**How do I see what the running MCP browser is doing?**

This guide covers the supported workflows for observing live browser sessions driven by the Agentic Stealth Browser MCP server. It prioritizes MCP-native tools (no external CDP required) and documents constraints, security, and fallbacks.

## Primary Path: MCP-Native Observability Tools

Once a session is launched via `stealth_launch`, use these tools for live observation. All respect the guardrails and env-configurable limits from the runtime.

### 1. List Active Tabs / Pages

```json
{
  "jsonrpc": "2.0",
  "id": 10,
  "method": "tools/call",
  "params": {
    "name": "stealth_tabs_list",
    "arguments": { "session_name": "my-session" }
  }
}
```

Returns tab IDs (e.g., `tab-0`, `tab-1`) and basic metadata. Use the returned `tab_id` for targeted snapshot/debug calls.

### 2. Capture Tab Snapshot

```json
{
  "name": "stealth_tab_snapshot",
  "arguments": {
    "session_name": "my-session",
    "tab_id": "tab-0",
    "full_page": false,
    "format": "png"
  }
}
```

- Saves PNG (or JPEG) under `STEALTH_MCP_SNAPSHOT_DIR` (default `~/.agentic-browser/mcp_snapshots/<session>/<ts>.png`).
- Enforces per-session retention: `STEALTH_MCP_SNAPSHOT_MAX_PER_SESSION` (default 20). Oldest pruned automatically.
- Returns path + lightweight `dom_summary` (headings, link counts, etc.) for quick LLM consumption.
- Path traversal blocked by `MCPSecurityContext`.

### 3. Session Timeline / Replay

```json
{
  "name": "stealth_session_timeline",
  "arguments": {
    "session_name": "my-session",
    "limit": 50
  }
}
```

- Wraps `browser.get_replay_sequence(limit)` (audit log actions like click/type/goto).
- `limit` clamped: default `STEALTH_MCP_TIMELINE_DEFAULT_LIMIT=30`, hard max `STEALTH_MCP_TIMELINE_MAX_LIMIT=200`.
- Ideal for "what did the agent actually do?" traces.

### 4. Full Debug Report

```json
{
  "name": "stealth_debug_report",
  "arguments": {
    "session_name": "my-session",
    "print_report": true
  }
}
```

- Bundles TLS fingerprint, applied headers/patches, recent audit events.
- `print_report=true` also prints human-readable to server stdout (for local debugging).
- Payloads are truncated at `STEALTH_MCP_OBSERVABILITY_MAX_CHARS` (default 50000) with safe truncation marker.

**All observability responses** are processed through `_guard_observability_payload` (truncation + redaction of secrets).

## Environment Variables (Observability & Guardrails)

See also the table in README.md. Key ones:

- `STEALTH_MCP_SNAPSHOT_DIR`
- `STEALTH_MCP_SNAPSHOT_MAX_PER_SESSION=20`
- `STEALTH_MCP_TIMELINE_DEFAULT_LIMIT=30`
- `STEALTH_MCP_TIMELINE_MAX_LIMIT=200`
- `STEALTH_MCP_OBSERVABILITY_MAX_CHARS=50000`
- `STEALTH_MCP_ALLOWED_DIRS` (for file policy, including snapshot root)

Set these in your MCP client config or shell before launching the server.

## Fallback Path: Headed Mode + Manual Debugging

If MCP-native tools are insufficient (e.g., visual DOM inspection needed beyond `dom_summary`):

1. Launch with `headless: false` + `debug: true`.
2. Use `stealth_debug_report` (with `print_report`) for fingerprints/patches.
3. Screenshots via `stealth_tab_snapshot` or the built-in `VISUAL_DEBUGGING.md` flows.
4. Local `~/.agentic-browser/.../debug/` artifacts.

## Optional / Advanced: CDP Attach (Deeper Live Observation) — v0.9.0 #377

For clients/backends that support direct Chrome DevTools Protocol attach (e.g., some desktop agents or custom setups):

- **Opt-in only**: Launch with `stealth_launch(..., debug_cdp=True)` (flag defaults to false for security; `debug=True` alone does **not** enable the port).
- Then call the dedicated MCP tool: `stealth_get_cdp_endpoint` (optionally with `session_name`).
  - When enabled: returns `{"status": "enabled", "ws_endpoint": "ws://127.0.0.1:<port>/...", "port": <n>, "browser": "...", "warning": "SECURITY: ... localhost (127.0.0.1) ONLY ...", ...}` + attach instructions.
  - When disabled (default): returns clear `{"status": "disabled", "message": "CDP attach is disabled (default). ... explicit security boundary ...", "security_note": "..."}`.
- Attach external tools (Chrome DevTools, Playwright `connect_over_cdp(ws_endpoint)`, Puppeteer, etc.) using the WS endpoint.
- **Caveat**: Not available (or firewalled) in all MCP client sandboxes (e.g., containerized or restricted Claude Desktop). The MCP-native tools (`stealth_*` observability) are the portable default and recommended.
- **Security (critical)**: The endpoint is **always bound exclusively to 127.0.0.1** (never 0.0.0.0). Explicit warnings are surfaced in tool descriptions, launch schema, responses, and this guide. CDP grants low-level control that bypasses some MCP guards/stealth — use **only** in trusted local development environments. Never expose, port-forward, or enable in production/shared hosts.

This implements GitHub #377 (optional CDP attach for v0.9.0) with minimal surface, localhost-only, and disabled-by-default posture.

## Security & Redaction Notes

- **Automatic redaction**: Responses and audit logs redact passwords, tokens, API keys, emails, session secrets (see `AuditLogger._redact_sensitive` and `mcp_security.py`).
- `session_name` and tab identifiers are **never redacted** (they are user-controlled labels, not secrets).
- File access for snapshots/cookies is bounded by `FileAccessPolicy` + `MCPSecurityContext` (no `..` traversal, explicit allowed dirs).
- Payload size caps prevent runaway responses from DoS'ing the MCP client.
- For production: run the MCP server with least-privilege (no unnecessary env vars, restricted `ALLOWED_DIRS`).

## Troubleshooting "Cannot Observe / Attach"

- **No tabs listed?** Ensure you called `stealth_launch` successfully first; check `stealth_status`.
- **Snapshots empty / pruned?** Check retention limit and `STEALTH_MCP_SNAPSHOT_DIR` writability.
- **Timeline empty?** Only navigation/click/type actions are captured; pure waits may not appear.
- **CDP attach fails or "disabled"?** You must explicitly pass `debug_cdp: true` to `stealth_launch`. The port is localhost-only (127.0.0.1) and only discoverable via `stealth_get_cdp_endpoint`. Most hosted/remote MCP clients cannot surface local TCP ports anyway — use native MCP observability tools or run the server in a local trusted dev environment with `headless=false` + `debug_cdp=true`.
- **Large responses truncated?** Increase `STEALTH_MCP_OBSERVABILITY_MAX_CHARS` (or reduce `limit`).
- **Permission errors on files?** Add dirs via `STEALTH_MCP_ALLOWED_DIRS` or adjust `mcp_security.py` policy.

## Supported Workflows Summary

| Goal                        | Recommended Tool(s)              | Requires CDP? | Notes |
|-----------------------------|----------------------------------|---------------|-------|
| "What tabs are open?"       | `stealth_tabs_list`              | No            | Stable `tab-*` IDs |
| "Show me the page"          | `stealth_tab_snapshot`           | No            | + `dom_summary` |
| "What actions happened?"    | `stealth_session_timeline`       | No            | Audit replay |
| "Full stealth config?"      | `stealth_debug_report`           | No            | TLS + patches + logs |
| Visual deep inspect         | Headed + snapshot / `stealth_get_cdp_endpoint` + external CDP | Optional (opt-in via `debug_cdp=True` on launch) | Localhost-only binding; explicit disabled status + warnings when off |
| Programmatic control        | All `stealth_*` + your agent loop| No            | Full MCP contract |

This guide directly addresses the need to "see what the MCP browser is doing" without requiring privileged browser backends.

## References

- `production/mcp_server.py` (StealthMCPServer implementation + guards)
- `tests/test_mcp_server_runtime.py` (deterministic examples)
- `docs/adr/007-mcp-security-model.md`
- `README.md` (MCP Setup + full tool/env table)
- Issues #369, #370, #379 (runtime, observability, hardening)

For contributions or questions on observability, open an issue with example JSON-RPC traces.

## v0.9.0 Migration & Backward Compatibility Policy (#378)

The v0.9.0 release introduces the official in-tree MCP runtime. We are committed to a smooth transition for existing automations.

**Current Compatibility Stance (v0.9.0)**:
- All tool names and response shapes introduced in the initial 0.9.0 runtime are considered **stable**.
- If a tool name or major field is ever renamed in a future minor release, the old name will continue to work for at least two minor versions (with a clear deprecation warning in the response and server logs).
- Use `stealth_capabilities` to discover the exact supported surface and any deprecation notices at runtime.

**Recommended Migration Path**:
1. Point your MCP client at the new `python -m production.mcp_server` entrypoint.
2. Replace any old external bridge calls with the native `stealth_*` tools.
3. Add defensive handling for the new `truncated` / `next_cursor` fields in observability responses (they are additive).

We will publish a full deprecation matrix in future patch releases. All breaking changes will be announced with a clear removal timeline.

If you hit a compatibility issue, open an issue with:
- The exact tool name + arguments you sent
- The response you received
- Your MCP client (Claude Desktop, Cursor, etc.)

We treat compatibility as a first-class release criterion.
