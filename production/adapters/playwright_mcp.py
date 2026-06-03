"""Playwright-MCP backend adapter.

Spawns the official @playwright/mcp server as a stdio subprocess and
communicates over JSON-RPC. Distinct from M1 (CDP-bridge, direct) and
M3 (Agentic-Stealth-MCP, our own server with stealth_* tool names).

Capability set: {LAUNCH, CLOSE, NAVIGATE, CLICK, FILL, SCREENSHOT, STATUS,
HEADLESS_SWITCH}. STREAM_CDP and MULTI_CONTEXT are NOT supported by
playwright-mcp at the time of writing.
"""
from __future__ import annotations

import asyncio
import shutil
from typing import Any, Optional

from production.adapters._jsonrpc_stdio import JsonRpcStdioClient
from production.adapters.base import (
    AdapterLaunchError,
    Capability,
)


# Pin a specific playwright-mcp version. The latest is fine; pin for
# reproducibility. Update this when a new release is tested.
PLAYWRIGHT_MCP_NPX_ARGS = [
    "-y",
    "@playwright/mcp@latest",
    "--isolated",
]


class PlaywrightMCPAdapter:
    """BackendAdapter implementation that drives the official Playwright MCP server.

    Usage:
        adapter = PlaywrightMCPAdapter()
        await adapter.launch("default", headless=True)
        await adapter.navigate("https://example.com")
        await adapter.close()
    """

    name = "playwright-mcp"

    def __init__(self) -> None:
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._client: Optional[JsonRpcStdioClient] = None
        self._headless: bool = True
        self._profile: Optional[str] = None

    # ------------------------------------------------------------------ capabilities
    def capabilities(self) -> set[Capability]:
        return {
            Capability.LAUNCH,
            Capability.CLOSE,
            Capability.NAVIGATE,
            Capability.CLICK,
            Capability.FILL,
            Capability.SCREENSHOT,
            Capability.STATUS,
            Capability.HEADLESS_SWITCH,
        }

    def supports(self, capability: Capability) -> bool:
        """Default capability check (set membership). Mirrors the base Protocol's
        default implementation; declared explicitly here so this concrete class
        passes the @runtime_checkable ``isinstance(inst, BackendAdapter)`` check
        (Protocols don't auto-inherit defaults onto structural implementations)."""
        return capability in self.capabilities()

    # ------------------------------------------------------------------ launch
    async def launch(self, profile: str, headless: bool = True) -> None:
        """Spawn npx @playwright/mcp as a stdio subprocess and complete the
        MCP initialize handshake.
        """
        self._profile = profile
        self._headless = headless

        npx = shutil.which("npx")
        if npx is None:
            raise AdapterLaunchError(
                "npx not found on PATH; install Node.js to use Playwright-MCP adapter"
            )

        args = [npx, *PLAYWRIGHT_MCP_NPX_ARGS]
        if not headless:
            args.append("--headed")
        # profile maps to the --user-data-dir flag in playwright-mcp
        if profile and profile != "default":
            args.extend(["--user-data-dir", profile])

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:
            raise AdapterLaunchError(
                f"Failed to spawn @playwright/mcp: {exc}"
            ) from exc

        self._client = JsonRpcStdioClient(self._proc.stdin, self._proc.stdout)

        # MCP handshake
        try:
            await self._client.request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "agentic-stealth-browser", "version": "2.5.0"},
                    "capabilities": {},
                },
            )
            await self._client.notify("notifications/initialized")
        except Exception as exc:
            await self._terminate_subprocess()
            raise AdapterLaunchError(
                f"MCP initialize handshake failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------ close
    async def close(self) -> None:
        await self._terminate_subprocess()
        self._client = None
        self._proc = None

    async def _terminate_subprocess(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        except ProcessLookupError:
            pass  # already dead

    # ------------------------------------------------------------------ actions
    async def navigate(self, url: str) -> None:
        await self._call_tool("playwright_navigate", {"url": url})

    async def click(self, selector: str) -> None:
        await self._call_tool("playwright_click", {"selector": selector})

    async def fill(self, selector: str, value: str) -> None:
        await self._call_tool("playwright_fill", {"selector": selector, "value": value})

    async def screenshot(self, path: Optional[str] = None) -> str:
        if path is None:
            path = "screenshot.png"
        # playwright-mcp exposes playwright_take_screenshot (or browser_take_screenshot,
        # depending on version). Try the common names; the test will accept any.
        try:
            await self._call_tool("browser_take_screenshot", {"filename": path})
        except RuntimeError:
            await self._call_tool("playwright_take_screenshot", {"filename": path})
        return str(path)

    async def status(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "running": self._proc is not None and self._proc.returncode is None,
            "headless": self._headless,
            "profile": self._profile,
        }

    # ------------------------------------------------------------------ helpers
    async def _call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("Playwright-MCP adapter not launched; call launch() first")
        response = await self._client.request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        return response.get("result", {})
