"""Tests for AgentBrowser.attach_over_cdp + stealth_attach_over_cdp MCP tool.

These tests verify the public contract of the attach-over-CDP feature:
  * input validation (bad URLs, empty arg, double attach)
  * MCP loopback safety gate (allow_remote requirement for non-loopback hosts)
  * end-to-end attach against a real Chromium with --remote-debugging-port (live)
  * teardown leaves the externally-launched browser process alive

The live e2e test is skipped automatically when Playwright's bundled Chromium
isn't installed (CI without `playwright install chromium`).
"""

from __future__ import annotations

import asyncio
import json
import socket
import urllib.request

import pytest

pytestmark = pytest.mark.asyncio

from core.agent_browser import AgentBrowser
from production.mcp_server import StealthMCPServer, ToolError


# ---------------------------------------------------------------------------
# Unit-level: validation + safety gate (no real browser)
# ---------------------------------------------------------------------------


async def test_attach_over_cdp_rejects_empty_url():
    ab = AgentBrowser(session_name="t-empty", anonymous=True, ephemeral=True)
    with pytest.raises(ValueError):
        await ab.attach_over_cdp("")
    await ab.close()


async def test_attach_over_cdp_rejects_when_already_attached(monkeypatch):
    ab = AgentBrowser(session_name="t-double", anonymous=True, ephemeral=True)
    ab.browser = object()  # simulate an already-active context
    with pytest.raises(RuntimeError, match="already has an active browser"):
        await ab.attach_over_cdp("http://127.0.0.1:9222")
    ab.browser = None
    await ab.close()


async def test_mcp_attach_blocks_remote_without_allow_remote():
    server = StealthMCPServer()
    with pytest.raises(ToolError) as ei:
        await server._tool_stealth_attach_over_cdp(
            {"cdp_url": "http://192.168.1.50:9222"}
        )
    assert ei.value.error_code == "MCP_REMOTE_CDP_BLOCKED"


async def test_mcp_attach_requires_cdp_url():
    server = StealthMCPServer()
    with pytest.raises(ToolError) as ei:
        await server._tool_stealth_attach_over_cdp({})
    assert ei.value.error_code == "MCP_VALIDATION_ERROR"


async def test_mcp_attach_rejects_url_without_host():
    server = StealthMCPServer()
    with pytest.raises(ToolError) as ei:
        await server._tool_stealth_attach_over_cdp({"cdp_url": "http://"})
    assert ei.value.error_code in ("MCP_VALIDATION_ERROR",)


# ---------------------------------------------------------------------------
# Two-layer safety gate (#438, #441): loopback helper + is_url_safe helper
# ---------------------------------------------------------------------------


async def test_mcp_attach_blocks_rfc1918_even_with_allow_remote():
    """Even with allow_remote=true, RFC-1918 hosts are rejected by is_url_safe."""
    server = StealthMCPServer()
    with pytest.raises(ToolError) as ei:
        await server._tool_stealth_attach_over_cdp(
            {"cdp_url": "http://10.0.0.5:9222", "allow_remote": True}
        )
    assert ei.value.error_code == "MCP_REMOTE_CDP_BLOCKED"


async def test_mcp_attach_blocks_link_local_ipv6():
    """Link-local IPv6 is rejected by is_loopback_host."""
    server = StealthMCPServer()
    with pytest.raises(ToolError) as ei:
        await server._tool_stealth_attach_over_cdp(
            {"cdp_url": "http://[fe80::1]:9222"}
        )
    assert ei.value.error_code == "MCP_REMOTE_CDP_BLOCKED"


async def test_mcp_attach_blocks_link_local_ipv6_even_with_allow_remote():
    """Link-local IPv6 is also rejected by is_url_safe's fe80::/10 block."""
    server = StealthMCPServer()
    with pytest.raises(ToolError) as ei:
        await server._tool_stealth_attach_over_cdp(
            {"cdp_url": "http://[fe80::1]:9222", "allow_remote": True}
        )
    assert ei.value.error_code == "MCP_REMOTE_CDP_BLOCKED"


async def test_mcp_attach_allows_loopback_literal():
    """127.0.0.1 with allow_remote unset passes the gate (no real connection test).

    We can't actually connect to a real Chromium, so the call raises
    RuntimeError from inside attach_over_cdp AFTER the gate passes.
    Crucially, it does NOT raise ToolError(MCP_REMOTE_CDP_BLOCKED) — the
    gate is the only thing this test is verifying.
    """
    server = StealthMCPServer()
    with pytest.raises(Exception) as ei:
        await server._tool_stealth_attach_over_cdp(
            {"cdp_url": "http://127.0.0.1:1"}  # port 1: nothing listening
        )
    # Gate passed → no MCP_REMOTE_CDP_BLOCKED ToolError
    if isinstance(ei.value, ToolError):
        assert ei.value.error_code != "MCP_REMOTE_CDP_BLOCKED", (
            f"Gate should have passed for loopback literal, got {ei.value.error_code}"
        )
    # Otherwise it's a RuntimeError from connect_over_cdp — also expected


# ---------------------------------------------------------------------------
# Integration: attach to a real Chromium and verify teardown does not kill it
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_cdp(port: int, timeout: float = 10.0) -> str:
    """Poll /json/version until Chrome is ready; return webSocketDebuggerUrl."""
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = asyncio.get_event_loop().time() + timeout
    last_err: Exception | None = None
    while asyncio.get_event_loop().time() < deadline:
        try:
            data = await asyncio.to_thread(
                lambda: urllib.request.urlopen(url, timeout=1.0).read()
            )
            return json.loads(data)["webSocketDebuggerUrl"]
        except Exception as e:  # noqa: BLE001
            last_err = e
            await asyncio.sleep(0.2)
    raise RuntimeError(f"CDP did not come up on :{port} ({last_err})")


@pytest.fixture
async def remote_chromium(tmp_path):
    """Launch a real Chromium with remote debugging; yield (port, process).

    Skips when Playwright's bundled Chromium isn't installed.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        pytest.skip("playwright not installed")

    port = _free_port()
    user_data = tmp_path / "remote-chrome-profile"
    user_data.mkdir()

    pw = await async_playwright().start()
    try:
        executable = pw.chromium.executable_path
        if not executable:
            await pw.stop()
            pytest.skip("playwright chromium binary not available")
    finally:
        await pw.stop()

    proc = await asyncio.create_subprocess_exec(
        executable,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data}",
        "--headless=new",
        "--no-sandbox",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _kill_if_alive():
        if proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                return
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()

    try:
        await _wait_for_cdp(port)
    except Exception as e:
        # Common in containers without system libs (nss, atk, libgbm, ...).
        # Drain stderr to surface the real reason in the skip message.
        err_tail = ""
        if proc.returncode is None:
            await _kill_if_alive()
        try:
            err = await proc.stderr.read() if proc.stderr else b""
            err_tail = err.decode("utf-8", errors="replace").strip().splitlines()[-3:]
            err_tail = " | ".join(err_tail)
        except Exception:
            pass
        pytest.skip(
            f"could not start Chromium with --remote-debugging-port "
            f"(exit={proc.returncode}, {e}); stderr: {err_tail or '<empty>'}"
        )

    try:
        yield port, proc
    finally:
        await _kill_if_alive()


async def test_attach_over_cdp_live_new_context(remote_chromium):
    port, proc = remote_chromium
    ab = AgentBrowser(session_name="t-attach", anonymous=True, ephemeral=True)
    info = await ab.attach_over_cdp(f"http://127.0.0.1:{port}", new_context=True)

    assert info["stealth_applied"] is True
    assert info["adopted_context_index"] == "new"
    assert "degradation" in info and isinstance(info["degradation"], list)
    assert ab.browser is not None and ab.page is not None

    # Stealth init script ran: webdriver flag is gone on a fresh page navigation.
    await ab.page.goto("about:blank")
    has_webdriver = await ab.page.evaluate("() => navigator.webdriver")
    assert has_webdriver in (False, None, 0, "")

    # Teardown must NOT kill the external browser process.
    await ab.close()
    await asyncio.sleep(0.3)
    assert proc.returncode is None, (
        "attach_over_cdp.close() must leave the externally-launched browser alive"
    )

    # Re-attach after close works (proves _pw was cleanly reset).
    ab2 = AgentBrowser(session_name="t-reattach", anonymous=True, ephemeral=True)
    info2 = await ab2.attach_over_cdp(f"127.0.0.1:{port}", new_context=True)
    assert info2["cdp_url"].startswith("http://")
    await ab2.close()
    assert proc.returncode is None
