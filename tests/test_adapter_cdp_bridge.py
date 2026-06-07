"""Tests for the CDP-bridge backend adapter.

The CDP-bridge adapter is distinct from the local launch path:
- It connects to an existing CDP endpoint (no process spawn).
- It does NOT support `Capability.LAUNCH` (it takes over, doesn't create).
- It tracks page ownership to honor the v2.4.1 attach contract
  (never close adopted pages).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from production.adapters import (
    BACKEND_REGISTRY,
    AdapterLaunchError,
    BackendAdapter,
    Capability,
    get_adapter,
)
from production.adapters.cdp_bridge import CDPBridgeAdapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeCDP:
    """Minimal stand-in for a playwright Browser returned by connect_over_cdp.

    Lets us assert which Playwright methods the adapter calls without
    spinning up a real browser. The M0 protocol test that verifies
    isinstance(_GoodAdapter(), BackendAdapter) lives in
    tests/test_backend_adapter_contract.py; this file focuses on
    *behavior* of the CDP-bridge adapter.
    """

    def __init__(self):
        self.contexts: list[MagicMock] = []
        self.closed = False
        self.is_connected_return = True

    def is_connected(self) -> bool:
        return self.is_connected_return

    async def close(self):
        self.closed = True

    async def new_context(self) -> MagicMock:
        # The real Playwright API exposes `new_context` as an async coroutine
        # that returns a BrowserContext. The adapter does
        # ``await self._browser.new_context()`` and then indexes
        # ``self._context.pages[0]`` in the action tests, so the fake must
        # both be awaitable AND record the new context in ``self.contexts``.
        ctx = MagicMock(name="BrowserContext")
        ctx.pages = []
        ctx.closed = False

        async def _close():
            ctx.closed = True

        ctx.close = _close
        self.contexts.append(ctx)
        return ctx

    def existing_contexts(self) -> list[MagicMock]:
        return list(self.contexts)


@pytest.fixture
def fake_playwright():
    """Patches async_playwright so the adapter can use it without a real browser.

    Returns a MagicMock with a `chromium` attribute that returns a fake CDP server.
    """
    fake_cdp = _FakeCDP()

    pw = MagicMock(name="async_playwright")
    pw.chromium = MagicMock()
    pw.chromium.connect_over_cdp = AsyncMock(return_value=fake_cdp)
    pw.stop = AsyncMock()

    with patch("production.adapters.cdp_bridge.async_playwright") as patched:
        patched.return_value.start = AsyncMock(return_value=pw)
        patched.return_value.stop = AsyncMock()
        yield {"pw": pw, "cdp": fake_cdp, "patched": patched}


# ---------------------------------------------------------------------------
# Registration / lookup
# ---------------------------------------------------------------------------


def test_cdp_bridge_is_registered():
    """The adapter must be in BACKEND_REGISTRY by name 'cdp-bridge'."""
    assert "cdp-bridge" in BACKEND_REGISTRY
    assert BACKEND_REGISTRY["cdp-bridge"] is CDPBridgeAdapter


def test_cdp_bridge_is_in_backend_registry_with_unique_name():
    """The M0 register_adapter helper enforces unique names. Verify the
    adapter satisfies the contract (non-empty name)."""
    assert CDPBridgeAdapter.name
    assert isinstance(CDPBridgeAdapter.name, str)


def test_cdp_bridge_lookup_via_get_adapter():
    """get_adapter('cdp-bridge') returns the class."""
    assert get_adapter("cdp-bridge") is CDPBridgeAdapter


def test_cdp_bridge_satisfies_runtime_checkable_protocol():
    """@runtime_checkable Protocol — instances must pass isinstance."""
    instance = CDPBridgeAdapter()
    assert isinstance(instance, BackendAdapter)


# ---------------------------------------------------------------------------
# Capability contract
# ---------------------------------------------------------------------------


def test_cdp_bridge_capabilities_excludes_launch():
    """CDP-bridge takes over an existing browser, does NOT support LAUNCH."""
    caps = CDPBridgeAdapter().capabilities()
    assert Capability.LAUNCH not in caps
    # And the user-visible support check agrees
    assert CDPBridgeAdapter().supports(Capability.LAUNCH) is False


def test_cdp_bridge_capabilities_includes_action_set():
    """Must support navigate/click/fill/screenshot/status/stream_cdp."""
    caps = CDPBridgeAdapter().capabilities()
    expected = {
        Capability.NAVIGATE,
        Capability.CLICK,
        Capability.FILL,
        Capability.SCREENSHOT,
        Capability.STATUS,
        Capability.STREAM_CDP,
    }
    missing = expected - caps
    assert not missing, f"CDP-bridge missing capabilities: {missing}"


# ---------------------------------------------------------------------------
# Launch behavior
# ---------------------------------------------------------------------------


async def test_launch_connects_to_endpoint_via_connect_over_cdp(fake_playwright):
    """launch() must call connect_over_cdp — not spawn a new browser process."""
    adapter = CDPBridgeAdapter()
    await adapter.launch("ws://localhost:9222", headless=True)
    fake_playwright["pw"].chromium.connect_over_cdp.assert_called_once_with(
        "ws://localhost:9222"
    )


async def test_launch_raises_adapter_launch_error_on_connect_failure(fake_playwright):
    """If connect_over_cdp raises, the adapter must surface AdapterLaunchError."""
    fake_playwright["pw"].chromium.connect_over_cdp.side_effect = ConnectionError(
        "boom"
    )
    adapter = CDPBridgeAdapter()
    with pytest.raises(AdapterLaunchError) as exc_info:
        await adapter.launch("ws://localhost:9222", headless=True)
    assert "boom" in str(exc_info.value)


async def test_launch_creates_new_context_when_requested(fake_playwright):
    """launch(..., headless=True) creates a fresh context (this adapter's
    default behavior; attach to existing contexts is supported via a
    separate path in production via the M1.5 attach flow)."""
    adapter = CDPBridgeAdapter()
    await adapter.launch("ws://localhost:9222", headless=True)
    cdp = fake_playwright["cdp"]
    assert len(cdp.contexts) == 1
    assert adapter._owns_page is True


# ---------------------------------------------------------------------------
# Action behavior (mocked)
# ---------------------------------------------------------------------------


async def test_navigate_calls_page_goto(fake_playwright):
    adapter = CDPBridgeAdapter()
    await adapter.launch("ws://localhost:9222", headless=True)
    ctx = fake_playwright["cdp"].contexts[0]
    page = MagicMock(name="Page")
    page.goto = AsyncMock()
    ctx.pages = [page]

    await adapter.navigate("https://example.com")
    page.goto.assert_called_once_with("https://example.com")


async def test_click_calls_page_click(fake_playwright):
    adapter = CDPBridgeAdapter()
    await adapter.launch("ws://localhost:9222", headless=True)
    ctx = fake_playwright["cdp"].contexts[0]
    page = MagicMock(name="Page")
    page.click = AsyncMock()
    ctx.pages = [page]

    await adapter.click("#submit")
    page.click.assert_called_once_with("#submit")


async def test_fill_calls_page_fill(fake_playwright):
    adapter = CDPBridgeAdapter()
    await adapter.launch("ws://localhost:9222", headless=True)
    ctx = fake_playwright["cdp"].contexts[0]
    page = MagicMock(name="Page")
    page.fill = AsyncMock()
    ctx.pages = [page]

    await adapter.fill("#email", "x@y.com")
    page.fill.assert_called_once_with("#email", "x@y.com")


async def test_screenshot_returns_saved_path(fake_playwright, tmp_path):
    """Per the M0 contract, screenshot returns the path it saved to (-> str)."""
    adapter = CDPBridgeAdapter()
    await adapter.launch("ws://localhost:9222", headless=True)
    ctx = fake_playwright["cdp"].contexts[0]
    page = MagicMock(name="Page")
    page.screenshot = AsyncMock()
    ctx.pages = [page]

    out = tmp_path / "shot.png"
    returned = await adapter.screenshot(str(out))
    assert returned == str(out)
    page.screenshot.assert_called_once_with(path=str(out))


# ---------------------------------------------------------------------------
# Close behavior (the v2.4.1 attach contract)
# ---------------------------------------------------------------------------


async def test_close_closes_owned_pages_only(fake_playwright):
    """close() must close owned pages, never adopted ones.

    The v2.4.1 contract (#451) is: adopted pages survive close().
    The adapter tracks this via `_owns_page`. When False, close() is a
    no-op for the underlying context.
    """
    adapter = CDPBridgeAdapter()
    await adapter.launch("ws://localhost:9222", headless=True)
    ctx = fake_playwright["cdp"].contexts[0]
    page = MagicMock(name="Page")
    page.close = AsyncMock()
    ctx.pages = [page]

    # Adopted page path
    adapter._owns_page = False
    await adapter.close()
    page.close.assert_not_called()

    # Owned page path
    adapter._owns_page = True
    page2 = MagicMock(name="Page")
    page2.close = AsyncMock()
    ctx.pages = [page2]
    await adapter.close()
    page2.close.assert_called_once()


async def test_close_stops_playwright(fake_playwright):
    adapter = CDPBridgeAdapter()
    await adapter.launch("ws://localhost:9222", headless=True)
    await adapter.close()
    # The adapter calls ``self._playwright.stop()`` where ``self._playwright``
    # is the result of ``async_playwright().start()`` — i.e. the ``pw`` mock.
    fake_playwright["pw"].stop.assert_called_once()


# ---------------------------------------------------------------------------
# Status behavior
# ---------------------------------------------------------------------------


async def test_status_returns_dict_with_cdp_metadata(fake_playwright):
    adapter = CDPBridgeAdapter()
    await adapter.launch("ws://localhost:9222", headless=True)
    status = await adapter.status()
    assert isinstance(status, dict)
    # Minimum contract: backend name, connected state
    assert status.get("backend") == "cdp-bridge"
    assert status.get("connected") is True
