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
import os
import shutil
from typing import Any, Optional

from production.adapters._jsonrpc_stdio import JsonRpcStdioClient
from production.adapters.base import (
    AdapterCapabilityError,
    AdapterLaunchError,
    Capability,
)


# Minimal env allowlist for the npx subprocess. The child does not need
# OPENAI_API_KEY / AWS_* / etc. — those belong to the operator, not to a
# browser automation tool. PATH is required for npx/node resolution;
# HOME is required by npm for cache directories on some installs.
def _subprocess_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
    }


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
                env=_subprocess_env(),
            )
        except Exception as exc:
            raise AdapterLaunchError(f"Failed to spawn @playwright/mcp: {exc}") from exc

        # Drain stderr in a background task. The pipe buffer is ~64KB;
        # without this drain, a noisy child (one stack trace from a
        # misconfigured Playwright install) blocks on its next stderr
        # write, hangs the handshake, and triggers a slow SIGKILL on close.
        self._stderr_task = asyncio.create_task(self._drain_stderr(self._proc.stderr))

        self._client = JsonRpcStdioClient(self._proc.stdin, self._proc.stdout)

        # MCP handshake
        try:
            await self._client.request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {
                        "name": "agentic-stealth-browser",
                        "version": "2.5.0",
                    },
                    "capabilities": {},
                },
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
        # Cancel the stderr drain task only after the child is gone,
        # so it can't raise mid-drain. Guarded by getattr for instances
        # that never reached the launch-success path.
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
        await self._call_tool("playwright_navigate", {"url": url})

    async def click(self, selector: str) -> None:
        self._require_capability(Capability.CLICK)
        await self._call_tool("playwright_click", {"selector": selector})

    async def fill(self, selector: str, value: str) -> None:
        self._require_capability(Capability.FILL)
        await self._call_tool("playwright_fill", {"selector": selector, "value": value})

    async def screenshot(self, path: Optional[str] = None) -> str:
        self._require_capability(Capability.SCREENSHOT)
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
    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError(
                "Playwright-MCP adapter not launched; call launch() first"
            )
        response = await self._client.request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        return response.get("result", {})

    def _require_capability(self, cap: Capability) -> None:
        """Raise AdapterCapabilityError when the active adapter does not
        declare ``cap``. Honors the M0 protocol contract at base.py:84 —
        callers get a clean, distinct error type instead of an opaque
        MCP failure. Mirrors cdp_bridge.py's defensive pattern, but here
        the check is NOT tautological because each action maps to a
        capability that *could* be absent on a future adapter variant.
        """
        if not self.supports(cap):
            raise AdapterCapabilityError(
                f"Playwright-MCP adapter does not declare {cap.value!r}"
            )

    @staticmethod
    async def _drain_stderr(stream) -> None:
        """Background task: read the child's stderr until EOF so the
        kernel pipe never fills. Lines are discarded — stderr from a
        child MCP server is debug noise, not data we consume. If the
        child closes the stream cleanly, this returns; on read error
        it logs and returns. Never raises into the parent task.
        """
        try:
            while True:
                line = await stream.readline()
                if not line:
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            # Stream closed or read failed — nothing actionable.
            return
