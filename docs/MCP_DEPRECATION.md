# MCP & CLI Deprecation Policy

## Policy

Tool and command names follow a **1-minor-version deprecation window**:

| Window | Behavior |
|--------|----------|
| v0.9.x | Old name registered as alias — works but returns `_deprecation_warning` in response payload |
| v0.10.0 | Alias removed — old name returns `MCP_TOOL_NOT_FOUND` |

This gives consumers one full release cycle to migrate.

## Migration Table (v0.8.x → v0.9.x)

### MCP Tools

| Old Name | New Name | Deprecation Window |
|----------|----------|-------------------|
| `launch` | `stealth_launch` | v0.9.x → removed in v0.10.0 |
| `navigate` | `stealth_navigate` | v0.9.x → removed in v0.10.0 |

### CLI Commands

| Old Command | New Command | Deprecation Window |
|-------------|-------------|-------------------|
| `status` | `health` | v0.9.x → removed in v0.10.0 |

## How Deprecation Warnings Appear

### MCP Tools

When calling an alias (e.g., `launch`), the response includes a `_deprecation_warning` key:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [...],
    "_deprecation_warning": "Tool 'launch' has been renamed to 'stealth_launch'. The alias will be removed in v0.10.0. Update your calls to use 'stealth_launch'."
  }
}
```

### CLI Commands

When using a deprecated command, a warning prints to stderr:

```
[agentic-stealth-browser] Warning: 'status' command is deprecated and has been renamed to 'health'.
The alias will be removed in v0.10.0. Please use 'health' instead.
```

## Writing Deprecation-Tolerant Clients

1. **Ignore `_deprecation_warning`** — it is informational only, never critical
2. **Watch stderr** for CLI deprecation notices
3. **Canonical names** do NOT produce deprecation warnings — only aliases do
