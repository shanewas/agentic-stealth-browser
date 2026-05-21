#!/usr/bin/env python3
"""Lightweight healthcheck script for the production Docker image.
Runs as non-root. Checks imports and basic AgentBrowser instantiation.
Addresses production health/readiness (#221, #96).
"""
import sys
try:
    from core.agent_browser import AgentBrowser
    b = AgentBrowser(anonymous=True)
    print("HEALTHY: core imports and instantiation succeeded")
    sys.exit(0)
except Exception as exc:
    print(f"UNHEALTHY: {exc}", file=sys.stderr)
    sys.exit(1)
