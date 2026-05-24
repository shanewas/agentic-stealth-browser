# Agentic Stealth Browser — Capability Map

## Browser / Backend Support Matrix

| Feature                    | Chromium (Playwright) | Edge (CDP)            | Firefox (feature-flagged) |
|----------------------------|------------------------|------------------------|----------------------------|
| Stealth fingerprint injection | Full                  | Full (same CDP)        | Partial (Gecko patches)   |
| TLS fingerprint spoofing   | Full (Chromium args)   | Full (Chromium args)   | Stub (Gecko constraints)  |
| Human-like typing / mouse  | Full                  | Full                   | Partial                   |
| Anti-block recovery        | Full                  | Full                   | Stub                      |
| Workflow record / replay   | Full                  | Full                   | Future                    |
| Cookie persistence         | Full                  | Full                   | Full                      |
| Proxy rotation             | Full                  | Full                   | Full                      |
| Pooled contexts            | Full                  | Full                   | Future                    |
| CDP remote debugging       | Full                  | Full                   | N/A (Firefox CDP)         |
| Session checkpoints        | Full                  | Full                   | Stub                      |
| MCP server (all tools)     | Full                  | Full                   | Partial (10/17 tools)     |
| SDK (client.py)            | Full                  | Full                   | Future                    |
| LinkedIn platform presets  | Full                  | Full                   | Stub                      |
| Upwork platform presets    | Full                  | Full                   | Stub                      |
| Rate limiter               | Full                  | Full                   | Full                      |
| Audit logging              | Full                  | Full                   | Full                      |
| Docker deployment          | Full                  | Full                   | Future                    |

**Legend**:
- **Full**: Tested and supported. All stealth/behavior/recovery features operational.
- **Partial**: Core functionality works; some advanced features may be degraded or untested.
- **Stub**: Adapter exists but is not yet production-ready.
- **Future**: Planned but not yet implemented.
- **N/A**: Feature does not apply to this backend.

## Feature Flags

| Flag                        | Default | Description                                      |
|-----------------------------|---------|--------------------------------------------------|
| `FIREFOX_SUPPORT`           | `false` | Enable experimental Firefox adapter              |
| `EDGE_SUPPORT`              | `true`  | Enable Microsoft Edge CDP support                |
| `ADAPTIVE_TUNING`           | `true`  | Enable ML-driven behavior parameter tuning       |
| `PLUGIN_SYSTEM`             | `true`  | Enable plugin loading/hooks                      |
| `POOLED_CONTEXTS`           | `true`  | Enable _BrowserPool for lightweight contexts     |
| `WORKFLOW_REPLAY`           | `true`  | Enable workflow replay engine                    |
| `LEARNING_LOOP`             | `false` | Enable feedback store / telemetry persistence    |

## Dynamic Capability Detection

Use `get_client_capabilities()` to query what features are supported for the current browser/backend:

```python
from core.feature_flags import get_client_capabilities

caps = get_client_capabilities()
# {
#   "browser_backend": "chromium",
#   "stealth_injection": True,
#   "tls_spoofing": True,
#   "human_behavior": True,
#   "anti_block_recovery": True,
#   "workflow_support": True,
#   "cookie_persistence": True,
#   "proxy_rotation": True,
#   "pooled_contexts": True,
#   "cdp_debug": True,
#   "firefox_support": False,
# }
```

Unsupported features return actionable error messages when used.
