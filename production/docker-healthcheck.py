#!/usr/bin/env python3
"""Lightweight healthcheck script for the production Docker image.
Runs as non-root. Checks core imports and MCP server availability.
If STEALTH_MCP_HEALTH_PORT env var is set, also performs HTTP health check
against the local MCP server's health endpoint (for orchestrators).
Addresses production health/readiness (#221, #96, v1.1.0 health endpoint).
"""
import sys
import os

try:
    from core.agent_browser import AgentBrowser
    b = AgentBrowser(anonymous=True)
    print("HEALTHY: core imports and instantiation succeeded")
except Exception as exc:
    print(f"UNHEALTHY: {exc}", file=sys.stderr)
    sys.exit(1)

health_port = os.getenv("STEALTH_MCP_HEALTH_PORT")
if health_port:
    try:
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", int(health_port), timeout=5)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        if resp.status == 200:
            print(f"HEALTHY: MCP server responding on port {health_port}")
        else:
            print(f"UNHEALTHY: MCP server returned {resp.status}", file=sys.stderr)
            sys.exit(1)
    except Exception as exc:
        print(f"UNHEALTHY: MCP server health check failed: {exc}", file=sys.stderr)
        sys.exit(1)

sys.exit(0)
