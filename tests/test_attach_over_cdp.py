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
# Attach safety gate (#438, #441, #448): loopback + allow_remote; rfc1918 permitted
# for documented WSL/private-host use when allow_remote=true (nav remains strict).
# Link-local / cloud-metadata still blocked.
# ---------------------------------------------------------------------------


async def test_mcp_attach_allows_rfc1918_with_explicit_allow_remote():
    """#448: WSL/container host IPs are RFC1918; explicit allow_remote permits attach (nav still blocks via is_url_safe)."""
    from unittest.mock import patch

    server = StealthMCPServer()
    # Patch attach_over_cdp so the test doesn't perform a real (slow + doomed) CDP connect to 10.0.0.5.
    # The only thing we assert is that the safety *gate* did not turn it into MCP_REMOTE_CDP_BLOCKED.
    with patch(
        "core.agent_browser.AgentBrowser.attach_over_cdp",
        side_effect=RuntimeError(
            "attach_over_cdp: failed to connect (simulated for test)"
        ),
    ):
        try:
            await server._tool_stealth_attach_over_cdp(
                {"cdp_url": "http://10.0.0.5:9222", "allow_remote": True}
            )
        except Exception as e:
            if isinstance(e, ToolError) and e.error_code == "MCP_REMOTE_CDP_BLOCKED":
                pytest.fail(
                    "RFC1918 + allow_remote should not be blocked by the CDP safety gate"
                )
            # RuntimeError from patch (or wrapped) or other non-BLOCKED error = gate was passed. Good.
    # link-local still blocked even with allow (auto-config risk)
    with pytest.raises(ToolError) as ei2:
        await server._tool_stealth_attach_over_cdp(
            {"cdp_url": "http://[fe80::1]:9222", "allow_remote": True}
        )
    assert ei2.value.error_code == "MCP_REMOTE_CDP_BLOCKED"


async def test_mcp_attach_blocks_link_local_ipv6():
    """Link-local IPv6 is rejected by is_loopback_host."""
    server = StealthMCPServer()
    with pytest.raises(ToolError) as ei:
        await server._tool_stealth_attach_over_cdp({"cdp_url": "http://[fe80::1]:9222"})
    assert ei.value.error_code == "MCP_REMOTE_CDP_BLOCKED"


async def test_mcp_attach_blocks_link_local_ipv6_even_with_allow_remote():
    """Link-local IPv6 remains blocked even with allow_remote (untrusted auto-config range)."""
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
    assert info["stealth_requested"] is True
    assert info["stealth_error"] is None
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
    assert info2["stealth_requested"] is True
    await ab2.close()
    assert proc.returncode is None


async def test_attach_over_cdp_reports_stealth_install_failure(
    remote_chromium, monkeypatch
):
    """When add_init_script raises, the return payload surfaces the failure.

    We monkeypatch the method on BrowserContext to simulate a Playwright-level
    rejection (e.g. invalid script syntax, large payload, etc.). The attach
    must still succeed — but stealth_applied must be False and stealth_error
    must be populated.
    """
    from playwright.async_api import BrowserContext

    port, proc = remote_chromium

    async def boom(self, script):
        raise RuntimeError("simulated add_init_script rejection")

    monkeypatch.setattr(BrowserContext, "add_init_script", boom)

    ab = AgentBrowser(session_name="t-stealth-fail", anonymous=True, ephemeral=True)
    info = await ab.attach_over_cdp(f"http://127.0.0.1:{port}", new_context=True)

    # Stealth was REQUESTED but the install FAILED
    assert info["stealth_requested"] is True
    assert info["stealth_applied"] is False
    assert info["stealth_error"] is not None
    assert "simulated add_init_script rejection" in info["stealth_error"]

    # The attached context is still usable (we got a page)
    assert ab.browser is not None and ab.page is not None

    await ab.close()
    # The external browser is still alive
    await asyncio.sleep(0.3)
    assert proc.returncode is None


async def test_attach_over_cdp_stealth_not_requested(remote_chromium):
    """When apply_stealth=False, stealth_applied is False but no error is set."""
    port, proc = remote_chromium
    ab = AgentBrowser(session_name="t-no-stealth", anonymous=True, ephemeral=True)
    info = await ab.attach_over_cdp(
        f"http://127.0.0.1:{port}", new_context=True, apply_stealth=False
    )
    assert info["stealth_applied"] is False
    assert info["stealth_requested"] is False
    assert info["stealth_error"] is None
    await ab.close()
    assert proc.returncode is None


# ---------------------------------------------------------------------------
# TeardownMode enum (#439)
# ---------------------------------------------------------------------------


def test_teardown_mode_enum_exists():
    """The TeardownMode enum is exported from core.agent_browser."""
    from core.agent_browser import TeardownMode

    assert TeardownMode.LAUNCHED.value == "launched"
    assert TeardownMode.POOLED.value == "pooled"
    assert TeardownMode.ATTACHED_OWNED_CTX.value == "attached_owned_ctx"
    assert TeardownMode.ATTACHED_ADOPTED_CTX.value == "attached_adopted_ctx"


async def test_teardown_mode_init_is_none():
    """Fresh AgentBrowser has _teardown_mode = None (no browser yet)."""
    ab = AgentBrowser(session_name="t-init", anonymous=True, ephemeral=True)
    assert ab._teardown_mode is None
    await ab.close()  # should be a no-op
    assert ab._teardown_mode is None


async def test_teardown_mode_set_to_attached_owned(remote_chromium):
    """attach_over_cdp(new_context=True) sets ATTACHED_OWNED_CTX."""
    from core.agent_browser import TeardownMode

    port, proc = remote_chromium
    ab = AgentBrowser(session_name="t-owned", anonymous=True, ephemeral=True)
    await ab.attach_over_cdp(f"http://127.0.0.1:{port}", new_context=True)
    assert ab._teardown_mode == TeardownMode.ATTACHED_OWNED_CTX
    await ab.close()
    assert ab._teardown_mode is None  # reset on close
    assert proc.returncode is None


async def test_teardown_mode_set_to_attached_adopted(remote_chromium):
    """attach_over_cdp(adopt existing) sets ATTACHED_ADOPTED_CTX."""
    from core.agent_browser import TeardownMode

    port, proc = remote_chromium
    # First call with new_context=True so the remote has ≥1 context
    ab_setup = AgentBrowser(session_name="t-setup", anonymous=True, ephemeral=True)
    await ab_setup.attach_over_cdp(f"http://127.0.0.1:{port}", new_context=True)
    # Don't close — leave the context alive. Now adopt it from a new instance.
    ab_adopt = AgentBrowser(session_name="t-adopt", anonymous=True, ephemeral=True)
    await ab_adopt.attach_over_cdp(
        f"http://127.0.0.1:{port}", new_context=False, context_index=0
    )
    assert ab_adopt._teardown_mode == TeardownMode.ATTACHED_ADOPTED_CTX
    assert (
        ab_adopt._owns_page is False
    )  # #451: we must not close the adopted user's page/tab
    # Clean up — close should NOT kill the adopted context or its pages
    await ab_adopt.close()
    assert ab_adopt.page is None
    await ab_setup.close()
    assert proc.returncode is None  # external browser still alive
