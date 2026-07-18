#!/usr/bin/env python3
"""Lightweight healthcheck script for the production Docker image.
Runs as non-root. Verifies core imports are functional.
Addresses production health/readiness (#221, #96, v1.1.0 health endpoint).

Note: The MCP server is a stdio JSON-RPC server, not HTTP-based.
Health checks verify Python import and dashboard port liveness only.
"""

import os
import sys
import urllib.error
import urllib.request

# ponytail: cheap recurring probe (import + port liveness); full Chromium launch verification belongs in Docker --start-period, not every interval.

if __name__ == "__main__":
    try:
        from core.agent_browser import AgentBrowser  # noqa: F401

        port = os.environ.get("HERMES_DASHBOARD_PORT", "8443")
        if port:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5)
            except urllib.error.HTTPError:
                pass  # any HTTP response (even 401/404) means the service is listening

        print("HEALTHY: package import + dashboard port reachable")
        sys.exit(0)
    except Exception as exc:
        print(f"UNHEALTHY: {exc}", file=sys.stderr)
        sys.exit(1)
