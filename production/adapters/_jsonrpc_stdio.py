"""Minimal JSON-RPC over stdio client for MCP-style subprocess servers.

M2 (Playwright-MCP) and M3 (Agentic-Stealth-MCP) both use this client
to talk to their respective stdio servers. Newline-delimited JSON.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional


class JsonRpcStdioClient:
    """Minimal JSON-RPC client speaking newline-delimited JSON over async streams.

    The adapter owns the subprocess; this client wraps its stdin/stdout.
    """

    def __init__(self, stdin, stdout) -> None:
        self._stdin = stdin
        self._stdout = stdout
        self._next_id = 1
        self._lock = asyncio.Lock()

    async def request(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for the response (matching id)."""
        request_id = self._next_id
        self._next_id += 1
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params

        async with self._lock:
            payload = (json.dumps(message) + "\n").encode()
            self._stdin.write(payload)
            await self._stdin.drain()

            # Read lines until we see a response with our id
            while True:
                line = await asyncio.wait_for(self._stdout.readline(), timeout=timeout)
                if not line:
                    raise ConnectionError("Subprocess closed stdout before responding")
                try:
                    response = json.loads(line.decode())
                except json.JSONDecodeError:
                    continue  # skip non-JSON lines (logs etc.)
                if response.get("id") == request_id:
                    if "error" in response:
                        err = response["error"]
                        raise RuntimeError(
                            f"JSON-RPC error: {err.get('code')} {err.get('message')}"
                        )
                    return response

    async def notify(
        self, method: str, params: Optional[dict[str, Any]] = None
    ) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        payload = (json.dumps(message) + "\n").encode()
        self._stdin.write(payload)
        await self._stdin.drain()
