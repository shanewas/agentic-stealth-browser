"""
MCP stdio server runtime for Agentic Stealth Browser.

This module intentionally implements a minimal MCP JSON-RPC surface directly
so the repository can run an MCP server without extra runtime dependencies.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from audit.logger import AuditLogger
from mcp_security import (
    FileAccessPolicy,
    LLMAuthorizationPolicy,
    MCPSecurityContext,
    sanitize_tool_description,
)


JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "agentic-stealth-browser"
SERVER_TITLE = "Agentic Stealth Browser MCP Server"
SERVER_VERSION = "0.9.0-dev"


class ToolError(Exception):
    """Tool-level execution error returned inside CallToolResult."""

    def __init__(self, error_code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details or {}


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]

    def as_mcp_tool(self) -> Dict[str, Any]:
        sanitized_description, _ = sanitize_tool_description(self.description)
        return {
            "name": self.name,
            "description": sanitized_description,
            "inputSchema": self.input_schema,
        }


def _build_security_context() -> MCPSecurityContext:
    """Construct security context with optional extra allowed directories."""
    file_policy = FileAccessPolicy()
    extra = os.getenv("STEALTH_MCP_ALLOWED_DIRS", "")
    if extra.strip():
        for raw in extra.replace(";", ",").split(","):
            d = raw.strip()
            if d:
                file_policy.add_allowed_dir(d)
    return MCPSecurityContext(
        file_policy=file_policy,
        llm_policy=LLMAuthorizationPolicy(),
        strict_mode=True,
    )


class StealthMCPServer:
    """Minimal MCP server implementation using JSON-RPC 2.0 over stdio."""

    def __init__(self, agent_browser_cls: Optional[type] = None):
        self.security = _build_security_context()
        self._agent_browser_cls = agent_browser_cls
        self._sessions: Dict[str, Any] = {}
        self._active_session: Optional[str] = None
        self._shutdown_requested = False
        self._tools: Dict[str, ToolSpec] = self._build_tools()

    def _get_agent_browser_cls(self):
        if self._agent_browser_cls is not None:
            return self._agent_browser_cls
        from core.agent_browser import AgentBrowser

        self._agent_browser_cls = AgentBrowser
        return self._agent_browser_cls

    def _jsonrpc_result(self, request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}

    def _jsonrpc_error(self, request_id: Any, code: int, message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": code, "message": message, "data": data or {}},
        }

    def _tool_error_payload(self, error_code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "status": "error",
            "error_code": error_code,
            "message": message,
            "details": details or {},
        }

    def _tool_ok_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if "status" not in payload:
            payload["status"] = "success"
        return payload

    def _tool_result(self, payload: Dict[str, Any], is_error: bool = False) -> Dict[str, Any]:
        redacted = AuditLogger._redact_sensitive(payload)
        text = json.dumps(redacted, indent=2, default=str)
        result: Dict[str, Any] = {
            "content": [{"type": "text", "text": text}],
            "structuredContent": redacted,
        }
        if is_error:
            result["isError"] = True
        return result

    def _build_tools(self) -> Dict[str, ToolSpec]:
        tools = [
            ToolSpec(
                name="stealth_launch",
                description="Launch browser session with stealth settings and optional preset/region.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string", "description": "Session identifier."},
                        "headless": {"type": "boolean", "default": True},
                        "debug": {"type": "boolean", "default": False},
                        "preset": {"type": "string"},
                        "region": {"type": "string"},
                        "anonymous": {"type": "boolean", "default": True},
                        "ephemeral": {"type": "boolean", "default": False},
                        "light_mode": {"type": "boolean", "default": False},
                        "use_pooled_context": {"type": "boolean", "default": False},
                    },
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_launch,
            ),
            ToolSpec(
                name="stealth_navigate",
                description="Navigate URL with recovery and human-like behavior.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string"},
                        "url": {"type": "string"},
                        "platform": {"type": "string", "default": "unknown"},
                        "warm_up": {"type": "boolean", "default": True},
                        "rate_limit": {"type": "boolean", "default": True},
                        "domain": {"type": "string"},
                        "account": {"type": "string"},
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_navigate,
            ),
            ToolSpec(
                name="stealth_load_cookies",
                description="Load cookies from file into current browser session.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string"},
                        "cookies_path": {"type": "string"},
                        "encryption_key": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}},
                            ]
                        },
                    },
                    "required": ["cookies_path"],
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_load_cookies,
            ),
            ToolSpec(
                name="stealth_set_region",
                description="Switch TLS/region profile for a running session.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string"},
                        "region": {"type": "string"},
                        "relaunch": {"type": "boolean", "default": False},
                    },
                    "required": ["region"],
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_set_region,
            ),
            ToolSpec(
                name="stealth_scrape",
                description="Navigate URL and extract structured page content.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string"},
                        "url": {"type": "string"},
                        "extract_images": {"type": "boolean", "default": False},
                        "platform": {"type": "string", "default": "unknown"},
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_scrape,
            ),
            ToolSpec(
                name="stealth_status",
                description="Return health/status snapshot for active session.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string"},
                        "include_debug": {"type": "boolean", "default": False},
                    },
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_status,
            ),
            ToolSpec(
                name="stealth_close",
                description="Close active session or all running sessions.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string"},
                        "close_all": {"type": "boolean", "default": False},
                    },
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_close,
            ),
            ToolSpec(
                name="stealth_capabilities",
                description="Return server/runtime capabilities and available tools.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                handler=self._tool_stealth_capabilities,
            ),
        ]
        return {t.name: t for t in tools}

    def list_tools(self) -> Dict[str, Any]:
        return {"tools": [tool.as_mcp_tool() for tool in self._tools.values()]}

    async def _resolve_browser(self, session_name: Optional[str]) -> tuple[str, Any]:
        chosen = session_name or self._active_session
        if not chosen:
            if len(self._sessions) == 1:
                chosen = next(iter(self._sessions.keys()))
            else:
                raise ToolError(
                    "MCP_SESSION_REQUIRED",
                    "No active session selected. Provide session_name or call stealth_launch first.",
                )
        browser = self._sessions.get(chosen)
        if not browser:
            raise ToolError("MCP_SESSION_NOT_FOUND", f"Session '{chosen}' not found.")
        self._active_session = chosen
        return chosen, browser

    async def _close_all_sessions(self) -> None:
        for name, browser in list(self._sessions.items()):
            try:
                await browser.close()
            except Exception:
                pass
            finally:
                self._sessions.pop(name, None)
        self._active_session = None

    async def _tool_stealth_launch(self, args: Dict[str, Any]) -> Dict[str, Any]:
        session_name = str(args.get("session_name") or "default")
        headless = bool(args.get("headless", True))
        debug = bool(args.get("debug", False))
        preset = args.get("preset")
        region = args.get("region")
        anonymous = bool(args.get("anonymous", True))
        ephemeral = bool(args.get("ephemeral", False))
        light_mode = bool(args.get("light_mode", False))
        use_pooled_context = bool(args.get("use_pooled_context", False))

        if session_name in self._sessions:
            try:
                await self._sessions[session_name].close()
            except Exception:
                pass
            finally:
                self._sessions.pop(session_name, None)

        AgentBrowser = self._get_agent_browser_cls()
        browser = AgentBrowser(
            session_name=session_name,
            anonymous=anonymous,
            ephemeral=ephemeral,
            light_mode=light_mode,
            use_pooled_context=use_pooled_context,
        )
        await browser.launch(headless=headless, debug=debug, preset=preset, region=region)

        self._sessions[session_name] = browser
        self._active_session = session_name

        health = await browser.get_health_status()
        return self._tool_ok_payload(
            {
                "session_name": session_name,
                "launched": True,
                "preset": browser.current_preset,
                "region": browser.current_region,
                "health": health,
            }
        )

    async def _tool_stealth_navigate(self, args: Dict[str, Any]) -> Dict[str, Any]:
        url = args.get("url")
        if not url:
            raise ToolError("MCP_VALIDATION_ERROR", "url is required")
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        platform = str(args.get("platform") or "unknown")
        warm_up = bool(args.get("warm_up", True))
        rate_limit = bool(args.get("rate_limit", True))
        domain = args.get("domain")
        account = args.get("account")

        ok = await browser.safe_goto(
            str(url),
            warm_up=warm_up,
            platform=platform,
            rate_limit=rate_limit,
            domain=domain,
            account=account,
        )
        if not ok:
            raise ToolError("MCP_NAVIGATION_FAILED", "Navigation failed or blocked.", {"url": url, "platform": platform})

        current_url = None
        try:
            p = browser.page_getter()
            current_url = getattr(p, "url", None) if p else None
        except Exception:
            current_url = None

        return self._tool_ok_payload(
            {
                "session_name": session_name,
                "url": str(url),
                "current_url": current_url,
                "platform": platform,
                "navigated": True,
            }
        )

    async def _tool_stealth_load_cookies(self, args: Dict[str, Any]) -> Dict[str, Any]:
        cookies_path = args.get("cookies_path")
        if not cookies_path:
            raise ToolError("MCP_VALIDATION_ERROR", "cookies_path is required")

        allowed, reason = self.security.check_file_access(str(cookies_path))
        if not allowed:
            raise ToolError(
                "MCP_SECURITY_PATH_DENIED",
                "cookies_path is not allowed by MCP security policy",
                {"path": str(cookies_path), "reason": reason},
            )

        session_name, browser = await self._resolve_browser(args.get("session_name"))
        result = await browser.load_cookies_from_file(
            str(cookies_path),
            encryption_key=args.get("encryption_key"),
        )

        if result.get("status") != "success":
            raise ToolError("MCP_COOKIE_LOAD_FAILED", result.get("message", "Failed to load cookies"), result)

        return self._tool_ok_payload({"session_name": session_name, "result": result})

    async def _tool_stealth_set_region(self, args: Dict[str, Any]) -> Dict[str, Any]:
        region = args.get("region")
        if not region:
            raise ToolError("MCP_VALIDATION_ERROR", "region is required")
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        relaunch = bool(args.get("relaunch", False))
        result = await browser.switch_region(str(region), relaunch=relaunch)
        if result.get("status") != "success":
            raise ToolError("MCP_REGION_SWITCH_FAILED", result.get("message", "Failed to switch region"), result)
        return self._tool_ok_payload({"session_name": session_name, "result": result})

    async def _tool_stealth_scrape(self, args: Dict[str, Any]) -> Dict[str, Any]:
        url = args.get("url")
        if not url:
            raise ToolError("MCP_VALIDATION_ERROR", "url is required")
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        extract_images = bool(args.get("extract_images", False))
        platform = str(args.get("platform") or "unknown")

        if not getattr(browser, "scraper", None):
            raise ToolError("MCP_SCRAPER_UNAVAILABLE", "Scraper is not initialized. Relaunch the session.")

        result = await browser.scraper.scrape_page(str(url), extract_images=extract_images, platform=platform)
        return self._tool_ok_payload({"session_name": session_name, "scrape": result})

    async def _tool_stealth_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        include_debug = bool(args.get("include_debug", False))
        health = await browser.get_health_status()
        payload: Dict[str, Any] = {"session_name": session_name, "health": health}
        if include_debug:
            payload["debug"] = await browser.debug_report(print_report=False)
        return self._tool_ok_payload(payload)

    async def _tool_stealth_close(self, args: Dict[str, Any]) -> Dict[str, Any]:
        close_all = bool(args.get("close_all", False))
        if close_all:
            count = len(self._sessions)
            await self._close_all_sessions()
            return self._tool_ok_payload({"closed_all": True, "closed_sessions": count})

        session_name, browser = await self._resolve_browser(args.get("session_name"))
        await browser.close()
        self._sessions.pop(session_name, None)
        if self._active_session == session_name:
            self._active_session = next(iter(self._sessions.keys()), None)
        return self._tool_ok_payload({"session_name": session_name, "closed": True})

    async def _tool_stealth_capabilities(self, args: Dict[str, Any]) -> Dict[str, Any]:
        _ = args
        return self._tool_ok_payload(
            {
                "server_name": SERVER_NAME,
                "server_title": SERVER_TITLE,
                "server_version": SERVER_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "tool_count": len(self._tools),
                "tools": [t.name for t in self._tools.values()],
                "active_session": self._active_session,
                "sessions": list(self._sessions.keys()),
            }
        )

    async def handle_jsonrpc(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        msg_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}

        if not isinstance(message, dict) or message.get("jsonrpc") != JSONRPC_VERSION or not method:
            return self._jsonrpc_error(msg_id, -32600, "Invalid Request")

        # Notifications: no response body.
        is_notification = "id" not in message

        if method in ("notifications/initialized", "initialized"):
            return None

        if method == "exit":
            await self._close_all_sessions()
            self._shutdown_requested = True
            return None

        if method == "initialize":
            client_protocol = (params or {}).get("protocolVersion") or PROTOCOL_VERSION
            result = {
                "protocolVersion": str(client_protocol),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "title": SERVER_TITLE,
                    "version": SERVER_VERSION,
                },
                "instructions": (
                    "Use stealth_launch to start a session, then stealth_navigate / stealth_scrape "
                    "and stealth_status to inspect state."
                ),
            }
            return self._jsonrpc_result(msg_id, result)

        if method == "shutdown":
            await self._close_all_sessions()
            self._shutdown_requested = True
            return self._jsonrpc_result(msg_id, {})

        if method == "ping":
            return self._jsonrpc_result(msg_id, {"ok": True})

        if method == "tools/list":
            return self._jsonrpc_result(msg_id, self.list_tools())

        if method == "tools/call":
            if not isinstance(params, dict):
                return self._jsonrpc_error(msg_id, -32602, "Invalid params")
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(tool_name, str) or not tool_name:
                return self._jsonrpc_error(msg_id, -32602, "Invalid params: tool name required")
            if not isinstance(arguments, dict):
                return self._jsonrpc_error(msg_id, -32602, "Invalid params: arguments must be object")

            tool = self._tools.get(tool_name)
            if not tool:
                payload = self._tool_error_payload(
                    "MCP_TOOL_NOT_FOUND",
                    f"Unknown tool '{tool_name}'",
                    {"available_tools": list(self._tools.keys())},
                )
                return self._jsonrpc_result(msg_id, self._tool_result(payload, is_error=True))

            try:
                payload = await tool.handler(arguments)
                return self._jsonrpc_result(msg_id, self._tool_result(payload, is_error=False))
            except ToolError as te:
                payload = self._tool_error_payload(te.error_code, te.message, te.details)
                return self._jsonrpc_result(msg_id, self._tool_result(payload, is_error=True))
            except Exception as exc:
                payload = self._tool_error_payload("MCP_INTERNAL_ERROR", str(exc))
                return self._jsonrpc_result(msg_id, self._tool_result(payload, is_error=True))

        if is_notification:
            return None
        return self._jsonrpc_error(msg_id, -32601, "Method not found")

    async def run_stdio(self) -> None:
        """Serve JSON-RPC messages over stdio."""
        while True:
            line = await asyncio.to_thread(sys.stdin.buffer.readline)
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError as exc:
                err = self._jsonrpc_error(None, -32700, "Parse error", {"error": str(exc)})
                sys.stdout.write(json.dumps(err) + "\n")
                sys.stdout.flush()
                continue

            response = await self.handle_jsonrpc(message)
            if response is not None:
                sys.stdout.write(json.dumps(response, default=str) + "\n")
                sys.stdout.flush()

            if self._shutdown_requested:
                break


def _run_list_tools(server: StealthMCPServer) -> int:
    print(json.dumps(server.list_tools(), indent=2))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Agentic Stealth Browser MCP server (stdio)")
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="Print available MCP tools and exit.",
    )
    args = parser.parse_args(argv)

    server = StealthMCPServer()
    if args.list_tools:
        return _run_list_tools(server)

    try:
        asyncio.run(server.run_stdio())
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

