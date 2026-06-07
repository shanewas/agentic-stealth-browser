"""Agentic-Stealth-MCP backend adapter.

Spawns this project's OWN MCP server (`python -m production.mcp_server`) as
a stdio subprocess and communicates over JSON-RPC. Distinct from M1
(CDP-bridge, direct) and M2 (Playwright-MCP, official @playwright/mcp with
playwright_* tool names).

Key distinguishing feature: this adapter calls `stealth_navigate`,
`stealth_click`, etc. — the tool names defined by our own MCP server.

Capability set: {LAUNCH, CLOSE, NAVIGATE, CLICK, FILL, SCREENSHOT, STATUS,
HEADLESS_SWITCH, MULTI_CONTEXT}. STREAM_CDP is NOT supported (the MCP
server doesn't expose raw CDP).
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Optional

from production.adapters._jsonrpc_stdio import JsonRpcStdioClient
from production.adapters.base import (
    AdapterCapabilityError,
    AdapterLaunchError,
    Capability,
)


# Minimal env allowlist for the mcp_server subprocess. Same rationale as
# playwright_mcp: don't leak the operator's API keys / DB URLs to a child
# that has no business reading them. PATH is required for the python
# interpreter to resolve stdlib; the child inherits nothing else.
def _subprocess_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
    }


class AgenticStealthMCPAdapter:
    """BackendAdapter implementation that drives our own MCP server.

    Usage:
        adapter = AgenticStealthMCPAdapter()
        await adapter.launch("default", headless=True)
        await adapter.navigate("https://example.com")
        await adapter.close()
    """

    name = "agentic-stealth-mcp"

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
            Capability.MULTI_CONTEXT,  # ASB-specific feature
        }

    def supports(self, capability: Capability) -> bool:
        """Default capability check (set membership). Mirrors the base Protocol's
        default implementation; declared explicitly here so this concrete class
        passes the @runtime_checkable ``isinstance(inst, BackendAdapter)`` check
        (Protocols don't auto-inherit defaults onto structural implementations)."""
        return capability in self.capabilities()

    # ------------------------------------------------------------------ launch
    async def launch(self, profile: str, headless: bool = True) -> None:
        """Spawn the project's own MCP server and complete the initialize handshake."""
        self._profile = profile
        self._headless = headless

        # Spawn python -m production.mcp_server
        args = [sys.executable, "-m", "production.mcp_server"]
        if profile and profile != "default":
            args.extend(["--session", profile])
        if not headless:
            args.append("--no-headless")

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_subprocess_env(),
            )
        except Exception as exc:
            raise AdapterLaunchError(
                f"Failed to spawn production.mcp_server: {exc}"
            ) from exc

        # Drain stderr in the background; see playwright_mcp.py for the
        # rationale (kernel pipe buffer deadlocks without this).
        self._stderr_task = asyncio.create_task(self._drain_stderr(self._proc.stderr))

        self._client = JsonRpcStdioClient(self._proc.stdin, self._proc.stdout)

        # MCP handshake
        try:
            response = await self._client.request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {
                        "name": "agentic-stealth-browser-dashboard",
                        "version": "2.5.0",
                    },
                    "capabilities": {},
                },
            )
            # Defensive: confirm the server is actually our MCP server
            server_info = response.get("result", {}).get("serverInfo", {})
            server_name = server_info.get("name", "")
            if (
                "agentic-stealth" not in server_name
                and "agentic_stealth" not in server_name
            ):
                await self._terminate_subprocess()
                raise AdapterLaunchError(
                    f"Unexpected MCP server: {server_name!r}; expected agentic-stealth-browser"
                )
            await self._client.notify("notifications/initialized")
        except Exception as exc:
            await self._terminate_subprocess()
            # Reset state so a caller that catches AdapterLaunchError and
            # then calls close() doesn't operate on a dead Process handle.
            self._client = None
            self._proc = None
            raise AdapterLaunchError(f"MCP initialize handshake failed: {exc}") from exc

    # ------------------------------------------------------------------ close
    async def close(self) -> None:
        await self._terminate_subprocess()
        # Cancel the stderr drain task after the child is gone; see
        # playwright_mcp.py for the lifecycle reasoning.
        stderr_task = getattr(self, "_stderr_task", None)
        if stderr_task is not None and not stderr_task.done():
            stderr_task.cancel()
            try:
                await stderr_task
            except (asyncio.CancelledError, Exception):
                pass
        self._stderr_task = None
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
        self._require_capability(Capability.NAVIGATE)
        await self._call_tool("stealth_navigate", {"url": url})

    async def click(self, selector: str) -> None:
        self._require_capability(Capability.CLICK)
        await self._call_tool("stealth_click", {"selector": selector})

    async def fill(self, selector: str, value: str) -> None:
        self._require_capability(Capability.FILL)
        await self._call_tool("stealth_fill", {"selector": selector, "value": value})

    async def screenshot(self, path: Optional[str] = None) -> str:
        self._require_capability(Capability.SCREENSHOT)
        if path is None:
            path = "screenshot.png"
        # The ASB MCP server exposes stealth_take_screenshot or similar.
        # Read production/mcp_server.py to confirm the actual name; the spec
        # pattern in the test accepts any "screenshot" suffix.
        try:
            await self._call_tool("stealth_take_screenshot", {"filename": path})
        except RuntimeError:
            await self._call_tool("stealth_screenshot", {"filename": path})
        return str(path)

    async def status(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "running": self._proc is not None and self._proc.returncode is None,
            "headless": self._headless,
            "profile": self._profile,
        }

    # ------------------------------------------------------------------ helpers
    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError(
                "Agentic-Stealth-MCP adapter not launched; call launch() first"
            )
        response = await self._client.request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        return response.get("result", {})

    def _require_capability(self, cap: Capability) -> None:
        """Raise AdapterCapabilityError when the active adapter does not
        declare ``cap``. See playwright_mcp.py for the contract rationale.
        """
        if not self.supports(cap):
            raise AdapterCapabilityError(
                f"Agentic-Stealth-MCP adapter does not declare {cap.value!r}"
            )

    @staticmethod
    async def _drain_stderr(stream) -> None:
        """Background stderr drain; see playwright_mcp.py for rationale."""
        try:
            while True:
                line = await stream.readline()
                if not line:
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            return
