"""CDP-bridge backend adapter.

Connects to a user-supplied Chrome DevTools Protocol endpoint and attaches
to the existing browser session. Distinct from M2 (Playwright-MCP) and M3
(Agentic-Stealth-MCP) which spawn stdio subprocesses.

This adapter honors the v2.4.1 attach contract (PR #451): adopted pages
are not closed on close(). Owned pages are closed.

Capability set: {NAVIGATE, CLICK, FILL, SCREENSHOT, STATUS, STREAM_CDP}.
LAUNCH is deliberately excluded — the user must already have a browser
running and reachable at the CDP endpoint.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)

from production.adapters.base import (
    AdapterLaunchError,
    Capability,
)


class CDPBridgeAdapter:
    """BackendAdapter implementation that bridges to an existing CDP endpoint.

    Usage:
        adapter = CDPBridgeAdapter()
        await adapter.launch("ws://localhost:9222", headless=True)
        await adapter.navigate("https://example.com")
        await adapter.close()
    """

    name = "cdp-bridge"

    def __init__(self) -> None:
        self._playwright: Optional[Any] = None  # async_playwright handle
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._owns_page: bool = False
        self._endpoint: Optional[str] = None

    # ------------------------------------------------------------------ capabilities
    def capabilities(self) -> set[Capability]:
        """Adapters that take over an existing browser do NOT support LAUNCH.

        STREAM_CDP is included because we have direct access to the CDP
        transport via the underlying Playwright session.
        """
        return {
            Capability.NAVIGATE,
            Capability.CLICK,
            Capability.FILL,
            Capability.SCREENSHOT,
            Capability.STATUS,
            Capability.STREAM_CDP,
        }

    def supports(self, capability: Capability) -> bool:
        """Default capability check (set membership). Mirrors the base Protocol's
        default implementation; declared explicitly here so this concrete class
        passes the @runtime_checkable ``isinstance(inst, BackendAdapter)`` check
        (Protocols don't auto-inherit defaults onto structural implementations)."""
        return capability in self.capabilities()

    # ------------------------------------------------------------------ launch
    async def launch(self, profile: str, headless: bool = True) -> None:
        """Connect to an existing CDP endpoint. Does NOT spawn a new browser.

        Args:
            profile: either a raw ws:// / wss:// / http(s):// CDP endpoint URL
                (back-compat with direct callers of this adapter), or a
                profile name — consistent with the base.py contract and the
                M2/M3 adapters — resolved to an endpoint via the
                ``CDP_ENDPOINT_<PROFILE>`` (or generic ``CDP_ENDPOINT``)
                environment variable.
            headless: cosmetic flag, passed to spec but the remote browser's
                      display state is determined by its own launch args.

        Raises:
            AdapterLaunchError: if the connection cannot be established, or
                (for a profile name) if no endpoint is configured for it.
        """
        endpoint = self._resolve_endpoint(profile)
        self._endpoint = endpoint
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(endpoint)
        except Exception as exc:
            # Best-effort cleanup: stop the playwright handle we just started
            try:
                if self._playwright is not None:
                    await self._playwright.stop()
            finally:
                self._playwright = None
                self._browser = None
            raise AdapterLaunchError(
                f"Failed to connect to CDP endpoint {endpoint!r}: {exc}"
            ) from exc

        # Create a fresh context for this adapter's use. Adopt vs. own is tracked.
        self._context = await self._browser.new_context()
        self._owns_page = True

    # ponytail: profile -> endpoint resolution is a flat env-var lookup, not
    # a real profile registry. Fine while operators set one CDP target per
    # profile by hand; upgrade to a config-file-backed mapping if/when the
    # dashboard needs to drive many named CDP profiles at once.
    @staticmethod
    def _resolve_endpoint(profile: str) -> str:
        if profile.startswith(("ws://", "wss://", "http://", "https://")):
            return profile
        env_key = f"CDP_ENDPOINT_{profile.upper().replace('-', '_')}"
        endpoint = os.environ.get(env_key) or os.environ.get("CDP_ENDPOINT")
        if not endpoint:
            raise AdapterLaunchError(
                f"No CDP endpoint configured for profile {profile!r}; "
                f"set {env_key} or CDP_ENDPOINT to a ws:// CDP URL"
            )
        return endpoint

    # ------------------------------------------------------------------ close
    async def close(self) -> None:
        """Tear down. Honors the v2.4.1 attach contract: only closes owned pages.

        If _owns_page is False (adopted), the underlying pages and context are
        preserved and we only stop the playwright handle.

        Idempotency: ``close()`` may be called multiple times. A second call
        after a successful teardown is a no-op — we re-stop the playwright
        handle (cheap if already stopped by the framework) but never re-close
        pages. This matches the v2.4.1 contract semantics.
        """
        try:
            if self._owns_page and self._context is not None:
                # Close each page we own individually (v2.4.1 #451: never
                # close adopted pages). Best-effort: a single failed page
                # must not prevent the rest from being torn down.
                for page in list(self._context.pages):
                    try:
                        await page.close()
                    except Exception:
                        pass
        finally:
            # Drop our references to the browser/context so the underlying
            # CDP server can be GC'd if the user holds no other handles.
            self._browser = None
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                finally:
                    self._playwright = None
            self._owns_page = False

    # ------------------------------------------------------------------ actions
    async def navigate(self, url: str) -> None:
        page = self._require_page()
        await page.goto(url)

    async def click(self, selector: str) -> None:
        page = self._require_page()
        await page.click(selector)

    async def fill(self, selector: str, value: str) -> None:
        page = self._require_page()
        await page.fill(selector, value)

    async def screenshot(self, path: Optional[str] = None) -> str:
        """Per the M0 contract, returns the path it saved to (-> str).

        Raises:
            AdapterCapabilityError: only if a future cdp-bridge variant
                drops SCREENSHOT from its declared capabilities; today
                SCREENSHOT is always present and this branch is dead.
                The M0 contract is the source of truth — capability
                checks live there, not in each adapter. Capability
                gating is enforced by the M2/M3 _require_capability()
                helpers; M1 doesn't need its own.
            RuntimeError: if launched without a context.
        """
        page = self._require_page()
        if path is None:
            path = "screenshot.png"
        await page.screenshot(path=path)
        return str(path)

    async def status(self) -> dict[str, Any]:
        """Return backend-specific health. Distinct from the dashboard's
        overall status payload (which adds active_adapter, capabilities,
        backend_relaunch_required in M4)."""
        connected = (
            self._browser is not None
            and hasattr(self._browser, "is_connected")
            and self._browser.is_connected()
        )
        return {
            "backend": self.name,
            "connected": connected,
            "running": connected,  # back-compat alias; "connected" is canonical
            "endpoint": self._endpoint,
            "owns_page": self._owns_page,
        }

    # ------------------------------------------------------------------ helpers
    def _require_page(self) -> Page:
        """Return the single page owned by this adapter's context, or raise."""
        if self._context is None:
            raise RuntimeError("CDP-bridge adapter not launched; call launch() first")
        # Single-page model for the dashboard adapter. If multiple pages exist,
        # take the first one. Multi-context capability is not declared by this
        # adapter; use Agentic-Stealth-MCP for that.
        if not self._context.pages:
            raise RuntimeError("No pages available in the CDP-bridge context")
        return self._context.pages[0]
