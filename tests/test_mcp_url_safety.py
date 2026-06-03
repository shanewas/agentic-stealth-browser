"""Tests for MCP URL safety helpers — link-local IPv6 + loopback gate.

These tests cover ``is_loopback_host`` added in M1.1 of the v2.4.0
attach-mode hardening plan. The helper is used for CDP attach gates where
the operator might be on a remote host (WSL→Windows, container→host) but
must never be allowed to attach to a host on an attacker's network.
"""

from __future__ import annotations

import os
import sys

import pytest

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
    """is_url_safe still rejects RFC-1918 (used by nav/scrape guards).

    Note: for CDP attach with allow_remote, RFC1918 is intentionally permitted
    (#448) to support WSL/private-host workflows; nav remains protected.
    """
    assert mcp_server.is_url_safe("http://10.0.0.5:9222") is False


# --- #454: fail-closed matrix for schemes, parse, and resolver failures ---


@pytest.mark.parametrize(
    "bad_url,reason",
    [
        ("file:///etc/passwd", "file scheme"),
        ("javascript:alert(1)", "javascript scheme"),
        ("data:text/plain,secret", "data scheme"),
        ("ftp://example.com/file", "ftp scheme"),
        ("ws://example.com", "ws scheme not allowed for nav"),
        ("http://", "no host"),
        ("https:///path", "no host after scheme"),
        ("not-a-url-at-all", "no scheme no host fallback"),
    ],
)
def test_is_url_safe_rejects_unsafe_schemes_and_bad_hosts(bad_url, reason):
    """#454: unsupported schemes and missing-host cases must fail closed."""
    assert mcp_server.is_url_safe(bad_url) is False, reason


def test_is_url_safe_rejects_on_dns_failure(monkeypatch):
    """#454: DNS errors (gaierror or any) must fail closed, never leak to browser."""
    import socket

    def _raise_gai(*a, **k):
        raise socket.gaierror("temporary failure in name resolution")

    monkeypatch.setattr(socket, "getaddrinfo", _raise_gai)
    assert mcp_server.is_url_safe("https://definitely-does-not-exist.invalid/") is False


def test_is_url_safe_rejects_on_empty_addrinfo(monkeypatch):
    """#454: empty resolver results must fail closed."""
    monkeypatch.setattr("socket.getaddrinfo", lambda h, p: [])
    assert mcp_server.is_url_safe("https://empty-resolver.example/") is False


def test_is_url_safe_accepts_public_https():
    """Sanity: real public hosts still pass (DNS + public IP)."""
    # This may do real DNS; acceptable for positive control in unit matrix.
    assert mcp_server.is_url_safe("https://example.com") is True
