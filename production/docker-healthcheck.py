#!/usr/bin/env python3
"""Lightweight healthcheck script for the production Docker image.
Runs as non-root. Verifies core imports are functional.
Addresses production health/readiness (#221, #96, v1.1.0 health endpoint).

Note: The MCP server is a stdio JSON-RPC server, not HTTP-based.
Health checks verify Python import and instantiation only.
"""

import sys

try:
    from core.agent_browser import AgentBrowser

    b = AgentBrowser(anonymous=True)
    print("HEALTHY: core imports and instantiation succeeded")
except Exception as exc:
    print(f"UNHEALTHY: {exc}", file=sys.stderr)
    sys.exit(1)

sys.exit(0)
