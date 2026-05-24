# Agentic Stealth Browser v1.1.0 — Operator Deployment Guide

## Overview

This guide covers production deployment of the Agentic Stealth Browser MCP server
via Docker. The v1.1.0 release adds Docker health checks, non-root execution, proper
volume mounts, and rate-limiting defaults for safer multi-account operations.

## Prerequisites

- Docker Engine 24+ with BuildKit
- At least 2 GB RAM per container (Chromium + Playwright)
- Internet access for Playwright browser download during build

## Building the Image

```bash
docker build -t agentic-stealth-browser:v1.1.0 -f production/Dockerfile .
```

The build uses multi-stage Docker with a non-root `appuser` (uid 1000).

## Running

### Minimal (stdio MCP server)
```bash
docker run --rm -i agentic-stealth-browser:v1.1.0
```

### With persistent data volumes
```bash
docker run --rm -i \
  -v /host/data/sessions:/data/sessions \
  -v /host/data/logs:/data/logs \
  -v /host/data/screenshots:/data/screenshots \
  -v /host/data/cookies:/data/cookies \
  -v /host/data/warming:/data/warming \
  agentic-stealth-browser:v1.1.0
```

### Docker Compose
```yaml
services:
  stealth-browser:
    image: agentic-stealth-browser:v1.1.0
    stdin_open: true
    volumes:
      - ./data/sessions:/data/sessions
      - ./data/logs:/data/logs
      - ./data/screenshots:/data/screenshots
      - ./data/cookies:/data/cookies
      - ./data/warming:/data/warming
    healthcheck:
      interval: 30s
      timeout: 10s
      start_period: 60s
      retries: 3
```

## Health Checking

The container includes a built-in HEALTHCHECK that runs
`python /app/production/docker-healthcheck.py` every 30 seconds.

The MCP server now supports a `health` JSON-RPC method returning server status,
version, and active session count.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `STEALTH_HEADLESS` | `true` | Run Chromium in headless mode |
| `STEALTH_REGION` | `global` | Default TLS fingerprint region |
| `DATA_DIR` | `/data` | Root data directory |
| `STEALTH_MCP_SNAPSHOT_DIR` | `~/.agentic-browser/mcp_snapshots` | Snapshot storage |
| `STEALTH_MCP_ALLOWED_DIRS` | (none) | Extra allowed directories for file access |
| `STEALTH_MCP_SNAPSHOT_MAX_PER_SESSION` | `20` | Max screenshots per session |

## Rate Limiting

Rate limiting is **enabled by default** on `safe_goto` (via `rate_limit=True`).
To disable for specific calls, pass `rate_limit=False`.

Default limits:
- 8 requests/minute per domain
- 40 requests/hour per domain
- 60-second cooldown between requests to the same domain
- Per-account isolation ensures separate accounts have independent limits

## Multi-Instance Considerations

The rate limiter is per-process. For multi-container deployments, partition accounts
across containers or use an external shared store (Redis). See the module docstring
in `production/rate_limiter.py` for details.

## Security

- Container runs as non-root `appuser` (uid 1000)
- HMAC integrity verification on cookie files
- Optional Fernet encryption for cookie storage
- Path traversal protection on all file operations
- Credentials redacted in audit logs and health reports
