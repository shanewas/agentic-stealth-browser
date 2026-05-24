# Upgrade Notes: v1.0.x → v1.1.0

## Breaking Changes

None. v1.1.0 is fully backward-compatible with v1.0.x.

## Key Changes

### Rate Limiting Now Default (Task #20)
`safe_goto()` now defaults to `rate_limit=True`. If you were relying on unlimited
calls, pass `rate_limit=False` explicitly. This change prevents accidental overuse
that triggers anti-bot blocks.

### Dockerfile Hardening (#13, #15)
- Container now runs as non-root `appuser` (uid 1000)
- HEALTHCHECK added with `docker-healthcheck.py`
- Entrypoint changed to `python -m production.mcp_server` (MCP stdio server)
- Volume mounts for sessions, logs, screenshots, cookies, warming data
- `workflows/` directory now included in the image
- `.dockerignore` excludes tests, `.clawpatch`, and review files

### CI Pipeline (#21)
- `ruff check` and `ruff format --check` are now **blocking** (previously non-blocking)
- `mypy` type checking added (informative, non-blocking)
- Docker build smoke test added to CI
- Previously: flake8-based linting with non-blocking ruff

### MCP Server Health Endpoint
New JSON-RPC `health` method returns server status, version, and active sessions.
Docker healthcheck script also supports optional HTTP health check via
`STEALTH_MCP_HEALTH_PORT` env var.

### Test Coverage Expansion (#6)
New unit test files added:
- `tests/test_recovery_state_machine.py` — Recovery orchestrator, backoff, circuit breaker
- `tests/test_rate_limiter_unit.py` — Domain/account/tool rate limiters
- `tests/test_metrics_collector_unit.py` — Counters, timers, Prometheus export
- `tests/test_cookie_manager_unit.py` — Expiry, encryption, domain filtering, HMAC
- `tests/test_proxy_config_unit.py` — Config validation, site sensitivity, health tracking
- `tests/test_workflow_schema_unit.py` — Schema validation, missing fields, unknown types

### Bug Fixes
- `tests/detection_runner.py`: Fixed `browser.browser.content()` → `browser.page.content()` (already resolved in v1.0.x)

## Migration Steps

1. Rebuild your Docker image: `docker build -t agentic-stealth-browser:v1.1.0 -f production/Dockerfile .`
2. If using `safe_goto()` without rate limiting, add `rate_limit=False` where needed
3. Update any orchestration scripts that relied on the old `ENTRYPOINT ["python"]` to use the new entrypoint
4. Verify volume mounts are configured for `/data/sessions`, `/data/logs`, `/data/screenshots`, `/data/cookies`, `/data/warming`
5. Run `ruff check .` locally to catch any lint issues before CI

## Deprecation Notices

None in this release.
