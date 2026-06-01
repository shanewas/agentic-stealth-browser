"""Tests for MCP URL safety helpers — link-local IPv6 + loopback gate.

These tests cover ``is_loopback_host`` added in M1.1 of the v2.4.0
attach-mode hardening plan. The helper is used for CDP attach gates where
the operator might be on a remote host (WSL→Windows, container→host) but
must never be allowed to attach to a host on an attacker's network.
"""

from __future__ import annotations

import os
import sys

# Make ``production`` importable as a top-level package.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROD = os.path.join(_ROOT, "production")
if _PROD not in sys.path:
    sys.path.insert(0, _PROD)

import mcp_server  # noqa: E402


def test_link_local_ipv6_blocked() -> None:
    """fe80::/10 (IPv6 link-local) is not loopback — must be rejected."""
    assert mcp_server.is_loopback_host("http://[fe80::1]:9222") is False


def test_loopback_literal_allowed() -> None:
    """127.0.0.1 is loopback — must be allowed for local CDP attach."""
    assert mcp_server.is_loopback_host("http://127.0.0.1:9222") is True


def test_loopback_localhost_allowed() -> None:
    """localhost (DNS → 127.0.0.1) must be allowed for local CDP attach."""
    assert mcp_server.is_loopback_host("http://localhost:9222") is True


def test_bare_host_port_normalised() -> None:
    """A bare host:port (no scheme) must still be normalised to http://."""
    assert mcp_server.is_loopback_host("127.0.0.1:9222") is True


def test_rfc1918_blocked() -> None:
    """RFC-1918 10.0.0.5 is not loopback — must be rejected for attach."""
    assert mcp_server.is_loopback_host("http://10.0.0.5:9222") is False


def test_rfc1918_blocked_even_for_allow_remote_helper() -> None:
    """is_url_safe must still reject RFC-1918 hosts (second-layer block).

    This confirms the second-layer block works for ``allow_remote=true``
    attach paths: even if a future change to ``is_loopback_host`` were
    permissive, ``is_url_safe`` would still keep the operator off
    private-network CDP endpoints.
    """
    assert mcp_server.is_url_safe("http://10.0.0.5:9222") is False
