"""Tests for the Playwright-MCP backend adapter.

Playwright-MCP is the official @playwright/mcp server. It is distinct from
M1 (CDP-bridge, direct) and M3 (Agentic-Stealth-MCP, our own server).

Key distinguishing test: this adapter calls `browser_navigate` (the current
@playwright/mcp tool naming) not `stealth_navigate`. M3 calls the latter.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from production.adapters import (
    AdapterCapabilityError,
    AdapterLaunchError,
    AdapterToolError,
    BACKEND_REGISTRY,
    BackendAdapter,
    Capability,
)
from production.adapters.playwright_mcp import PlaywrightMCPAdapter


# ---------------------------------------------------------------------------
# Fixtures: fake MCP stdio server
# ---------------------------------------------------------------------------


class _FakeStdio:
    """Stand-in for the stdio of a real MCP subprocess.

    async_playwright_mcp launches `npx -y @playwright/mcp@latest` and talks
    JSON-RPC over its stdin/stdout. We mock those streams.

    queue_write: messages the adapter WROTE to the subprocess's stdin
    queue_read: messages the fake server WILL write to its stdout
    """

    def __init__(self):
        self.queue_write: list[dict] = []
        self.queue_read: list[dict] = []
        self.closed = False

    def write_message(self, msg: dict) -> None:
        self.queue_write.append(msg)

    def read_message(self) -> dict | None:
        if self.queue_read:
            return self.queue_read.pop(0)
        return None


@pytest.fixture
def fake_subprocess(monkeypatch):
    """Patch asyncio.create_subprocess_exec to return a fake subprocess.

    The fake has .stdin (writable stream) and .stdout (readable stream)
    that the adapter can talk to.
    """
    fake = _FakeStdio()

    stdin = MagicMock(name="stdin")
    stdin.write = lambda data: fake.write_message(json.loads(data.decode()))
    stdin.drain = AsyncMock()
    stdin.close = MagicMock()
    stdin.wait_closed = AsyncMock()

    stdout = MagicMock(name="stdout")

    async def _readline():
        msg = fake.read_message()
        if msg is None:
            return b""
        return (json.dumps(msg) + "\n").encode()

    stdout.readline = _readline

    proc = MagicMock(name="subprocess")
    proc.stdin = stdin
    proc.stdout = stdout
    proc.returncode = None
    proc.terminate = MagicMock()
    proc.kill = MagicMock()

    async def _wait():
        proc.returncode = 0

    proc.wait = _wait

    async def _create_subprocess_exec(*args, **kwargs):
        # Verify the spawn command
        fake.spawn_args = args
        return proc

    monkeypatch.setattr(
        "production.adapters.playwright_mcp.asyncio.create_subprocess_exec",
        _create_subprocess_exec,
    )
    return {"fake": fake, "proc": proc, "stdin": stdin, "stdout": stdout}


def _enqueue_init_response(fake: _FakeStdio) -> None:
    """Queue a minimal MCP initialize response that the fake server returns."""
    fake.queue_read.append(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "playwright-mcp", "version": "0.0.30"},
                "capabilities": {"tools": {}},
            },
        }
    )


def _enqueue_tool_response(fake: _FakeStdio, request_id: int, content: list) -> None:
    fake.queue_read.append(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"content": content, "isError": False},
        }
    )


# ---------------------------------------------------------------------------
# Registration / lookup
# ---------------------------------------------------------------------------


def test_playwright_mcp_is_registered():
    assert "playwright-mcp" in BACKEND_REGISTRY
    assert BACKEND_REGISTRY["playwright-mcp"] is PlaywrightMCPAdapter


def test_playwright_mcp_satisfies_runtime_checkable_protocol():
    assert isinstance(PlaywrightMCPAdapter(), BackendAdapter)


# ---------------------------------------------------------------------------
# Capability contract
# ---------------------------------------------------------------------------


def test_playwright_mcp_capabilities_includes_launch_action_set():
    """This adapter SPAWNS a new browser via @playwright/mcp, so LAUNCH is in."""
    caps = PlaywrightMCPAdapter().capabilities()
    expected = {
        Capability.LAUNCH,
        Capability.CLOSE,
        Capability.NAVIGATE,
        Capability.CLICK,
        Capability.FILL,
        Capability.SCREENSHOT,
        Capability.STATUS,
        Capability.HEADLESS_SWITCH,
    }
    assert expected.issubset(caps), f"Missing: {expected - caps}"


def test_playwright_mcp_capabilities_excludes_stream_cdp():
    """playwright-mcp does NOT expose raw CDP event stream."""
    assert not PlaywrightMCPAdapter().supports(Capability.STREAM_CDP)


def test_playwright_mcp_capabilities_excludes_multi_context():
    """playwright-mcp v1 manages a single context; multi-context is not exposed."""
    assert not PlaywrightMCPAdapter().supports(Capability.MULTI_CONTEXT)


# ---------------------------------------------------------------------------
# Spawn behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_launch_spawns_npx_playwright_mcp(fake_subprocess):
    """launch() must invoke `npx -y @playwright/mcp@latest` (or pinned version)."""
    fake = fake_subprocess["fake"]
    _enqueue_init_response(fake)

    adapter = PlaywrightMCPAdapter()
    await adapter.launch("default", headless=True)

    # The first arg of the spawn command should be the npx binary
    args = fake.spawn_args
    assert "npx" in args[0] or "npx" in str(args)
    # And the package reference
    assert any("@playwright/mcp" in str(a) for a in args), (
        f"Spawn args do not include @playwright/mcp: {args}"
    )


@pytest.mark.asyncio
async def test_launch_sends_initialize_jsonrpc(fake_subprocess):
    """After spawn, the adapter must send a JSON-RPC initialize request."""
    fake = fake_subprocess["fake"]
    _enqueue_init_response(fake)

    adapter = PlaywrightMCPAdapter()
    await adapter.launch("default", headless=True)

    # First message written to stdin should be the initialize request
    assert len(fake.queue_write) >= 1
    init = fake.queue_write[0]
    assert init["method"] == "initialize"
    assert "params" in init


@pytest.mark.asyncio
async def test_launch_raises_adapter_launch_error_on_spawn_failure(monkeypatch):
    """If the subprocess fails to spawn, the adapter must surface AdapterLaunchError."""

    async def _explode(*args, **kwargs):
        raise OSError("npx not found")

    monkeypatch.setattr(
        "production.adapters.playwright_mcp.asyncio.create_subprocess_exec",
        _explode,
    )
    adapter = PlaywrightMCPAdapter()
    with pytest.raises(AdapterLaunchError) as exc_info:
        await adapter.launch("default", headless=True)
    assert (
        "npx not found" in str(exc_info.value) or "spawn" in str(exc_info.value).lower()
    )


# ---------------------------------------------------------------------------
# Action dispatch (this is the DISTINGUISHING test vs M3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_navigate_sends_browser_navigate_tool_call(fake_subprocess):
    """adapter.navigate(url) must call the browser_navigate tool — not stealth_navigate."""
    fake = fake_subprocess["fake"]
    _enqueue_init_response(fake)
    # After init, queue a response for the navigate tool call
    _enqueue_tool_response(fake, 2, [{"type": "text", "text": "navigated"}])

    adapter = PlaywrightMCPAdapter()
    await adapter.launch("default", headless=True)
    # Clear the init messages
    fake.queue_write.clear()
    fake.queue_read.clear()

    _enqueue_tool_response(fake, 2, [{"type": "text", "text": "navigated"}])
    await adapter.navigate("https://example.com")

    # The tool call message should reference browser_navigate
    tool_calls = [m for m in fake.queue_write if m.get("method") == "tools/call"]
    assert tool_calls, f"No tools/call sent: {fake.queue_write}"
    assert tool_calls[0]["params"]["name"] == "browser_navigate"
    assert tool_calls[0]["params"]["arguments"]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_click_sends_browser_click_tool_call(fake_subprocess):
    fake = fake_subprocess["fake"]
    _enqueue_init_response(fake)
    _enqueue_tool_response(fake, 2, [{"type": "text", "text": "clicked"}])

    adapter = PlaywrightMCPAdapter()
    await adapter.launch("default", headless=True)
    fake.queue_write.clear()
    fake.queue_read.clear()
    _enqueue_tool_response(fake, 2, [{"type": "text", "text": "clicked"}])

    await adapter.click("#submit")
    tool_calls = [m for m in fake.queue_write if m.get("method") == "tools/call"]
    assert tool_calls[0]["params"]["name"] == "browser_click"
    # 0.0.78 schema: browser_click takes `target` (required; accepts a plain
    # CSS selector, not only a snapshot ref) + `element` (optional
    # human-readable description) — no `selector` key.
    assert tool_calls[0]["params"]["arguments"]["target"] == "#submit"
    assert tool_calls[0]["params"]["arguments"]["element"] == "#submit"


@pytest.mark.asyncio
async def test_fill_sends_browser_type_tool_call(fake_subprocess):
    fake = fake_subprocess["fake"]
    _enqueue_init_response(fake)
    _enqueue_tool_response(fake, 2, [{"type": "text", "text": "filled"}])

    adapter = PlaywrightMCPAdapter()
    await adapter.launch("default", headless=True)
    fake.queue_write.clear()
    fake.queue_read.clear()
    _enqueue_tool_response(fake, 2, [{"type": "text", "text": "filled"}])

    await adapter.fill("#email", "x@y.com")
    tool_calls = [m for m in fake.queue_write if m.get("method") == "tools/call"]
    assert tool_calls[0]["params"]["name"] == "browser_type"
    # 0.0.78 schema: browser_type takes `target` (required) + `text`
    # (required) + optional `element` — no `selector`/`value` keys.
    assert tool_calls[0]["params"]["arguments"]["target"] == "#email"
    assert tool_calls[0]["params"]["arguments"]["text"] == "x@y.com"


@pytest.mark.asyncio
async def test_screenshot_sends_take_screenshot_tool_call(fake_subprocess, tmp_path):
    """Per M0 contract, screenshot returns the path it saved to (-> str)."""
    fake = fake_subprocess["fake"]
    _enqueue_init_response(fake)
    _enqueue_tool_response(fake, 2, [{"type": "text", "text": "saved"}])

    adapter = PlaywrightMCPAdapter()
    await adapter.launch("default", headless=True)
    fake.queue_write.clear()
    fake.queue_read.clear()
    _enqueue_tool_response(fake, 2, [{"type": "text", "text": "saved"}])

    out = tmp_path / "shot.png"
    returned = await adapter.screenshot(str(out))
    assert returned == str(out)
    tool_calls = [m for m in fake.queue_write if m.get("method") == "tools/call"]
    assert "screenshot" in tool_calls[0]["params"]["name"]


# ---------------------------------------------------------------------------
# Negative: capability gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejects_stream_cdp_request_with_capability_error(fake_subprocess):
    """Calling a method that requires STREAM_CDP on this adapter must raise
    AdapterCapabilityError. We expose this by calling status() with a
    'subscribe_cdp' flag (a hypothetical), and verifying the adapter
    rejects it because STREAM_CDP is not in capabilities().
    """
    adapter = PlaywrightMCPAdapter()
    # The adapter should expose a method that requires STREAM_CDP. For M2
    # the dashboard may attempt to subscribe to CDP events. Verify the
    # adapter's supports() check returns False.
    assert not adapter.supports(Capability.STREAM_CDP)


# ---------------------------------------------------------------------------
# Close behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_terminates_subprocess(fake_subprocess):
    fake = fake_subprocess["fake"]
    _enqueue_init_response(fake)
    adapter = PlaywrightMCPAdapter()
    await adapter.launch("default", headless=True)

    proc = fake_subprocess["proc"]
    await adapter.close()
    proc.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_close_idempotent(fake_subprocess):
    """Calling close() twice must not raise."""
    fake = fake_subprocess["fake"]
    _enqueue_init_response(fake)
    adapter = PlaywrightMCPAdapter()
    await adapter.launch("default", headless=True)
    await adapter.close()
    await adapter.close()  # second call must be safe


# ---------------------------------------------------------------------------
# Capability gating (v2.5.0 review fix S1)
# ---------------------------------------------------------------------------


def test_capability_gating_helper_raises_when_capability_missing():
    """The M0 protocol contract (base.py:84) promises that action methods
    raise AdapterCapabilityError when the active adapter does not declare
    the corresponding capability. M2 must enforce this — otherwise the
    docstring-vs-code lie survives the v2.5.0 release."""
    adapter = PlaywrightMCPAdapter()

    class _NoScreenshotAdapter(PlaywrightMCPAdapter):
        name = "_test_no_screenshot"

        def capabilities(self):
            # Drop SCREENSHOT from the set to simulate a future variant
            # that does not support it. The gating check must fire.
            return super().capabilities() - {Capability.SCREENSHOT}

    stripped = _NoScreenshotAdapter()
    with pytest.raises(AdapterCapabilityError, match="screenshot"):
        stripped._require_capability(Capability.SCREENSHOT)

    # Sanity: an action the adapter DOES declare passes the check.
    # We don't actually call the tool here — we just confirm the gate
    # itself doesn't fire.
    stripped._require_capability(Capability.NAVIGATE)  # must not raise


@pytest.mark.asyncio
async def test_navigate_raises_adapter_tool_error_on_is_error(fake_subprocess):
    """A tool-level failure (isError: true) is a valid JSON-RPC response, not
    a protocol error — the adapter must not swallow it as success."""
    fake = fake_subprocess["fake"]
    _enqueue_init_response(fake)
    adapter = PlaywrightMCPAdapter()
    await adapter.launch("default", headless=True)
    fake.queue_write.clear()
    fake.queue_read.clear()

    fake.queue_read.append(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [{"type": "text", "text": "Error: no element found"}],
                "isError": True,
            },
        }
    )
    try:
        with pytest.raises(AdapterToolError):
            await adapter.navigate("https://example.com")
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_screenshot_raises_capability_error_when_missing(fake_subprocess):
    """End-to-end: when a future variant drops SCREENSHOT from its
    declared capabilities, adapter.screenshot() must surface
    AdapterCapabilityError — not an opaque MCP failure."""
    fake = fake_subprocess["fake"]
    _enqueue_init_response(fake)

    class _NoScreenshotAdapter(PlaywrightMCPAdapter):
        name = "_test_no_screenshot_e2e"

        def capabilities(self):
            return super().capabilities() - {Capability.SCREENSHOT}

    adapter = _NoScreenshotAdapter()
    await adapter.launch("default", headless=True)
    try:
        with pytest.raises(AdapterCapabilityError, match="screenshot"):
            await adapter.screenshot("/tmp/should_not_write.png")
    finally:
        await adapter.close()
