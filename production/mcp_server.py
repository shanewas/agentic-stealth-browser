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
import time
from dataclasses import dataclass
from pathlib import Path
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
SERVER_VERSION = "0.9.0"


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
        self._tab_ids: Dict[str, Dict[int, str]] = {}
        self._next_tab_id = 1
        self._snapshot_root = Path(
            os.getenv(
                "STEALTH_MCP_SNAPSHOT_DIR",
                str(Path.home() / ".agentic-browser" / "mcp_snapshots"),
            )
        )
        self._snapshot_max_per_session = self._env_int(
            "STEALTH_MCP_SNAPSHOT_MAX_PER_SESSION",
            default=20,
            min_value=1,
            max_value=500,
        )
        self._timeline_default_limit = self._env_int(
            "STEALTH_MCP_TIMELINE_DEFAULT_LIMIT",
            default=30,
            min_value=1,
            max_value=200,
        )
        self._timeline_max_limit = self._env_int(
            "STEALTH_MCP_TIMELINE_MAX_LIMIT",
            default=200,
            min_value=1,
            max_value=1000,
        )
        self._observability_max_chars = self._env_int(
            "STEALTH_MCP_OBSERVABILITY_MAX_CHARS",
            default=50000,
            min_value=2000,
            max_value=500000,
        )
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

    def _env_int(self, name: str, default: int, min_value: int, max_value: int) -> int:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            v = int(raw)
        except Exception:
            return default
        return max(min_value, min(v, max_value))

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
                name="stealth_tabs_list",
                description="List known tabs/pages for active session.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_tabs_list,
            ),
            ToolSpec(
                name="stealth_tab_snapshot",
                description="Capture screenshot and metadata for a tab/page.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string"},
                        "tab_id": {"type": "string"},
                        "full_page": {"type": "boolean", "default": False},
                    },
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_tab_snapshot,
            ),
            ToolSpec(
                name="stealth_session_timeline",
                description="Return replay/timeline events for active session. Supports pagination via limit/cursor/since_ts (#381).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string"},
                        "limit": {"type": "integer", "default": 30, "minimum": 1, "maximum": 200},
                        "cursor": {"type": "string", "description": "Opaque cursor for next page (typically previous next_cursor, used as before-ts boundary for older events)"},
                        "since_ts": {"type": "string", "description": "ISO-8601 timestamp; only return events with timestamp >= since_ts (for incremental/polling)"},
                    },
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_session_timeline,
            ),
            ToolSpec(
                name="stealth_debug_report",
                description="Return debug report payload for active session. Supports pagination params to control recent_audit size/filter (#381).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string"},
                        "print_report": {"type": "boolean", "default": False},
                        "limit": {"type": "integer", "default": 15, "minimum": 1, "maximum": 100},
                        "cursor": {"type": "string", "description": "Opaque cursor for next page of recent_audit (typically previous next_cursor)"},
                        "since_ts": {"type": "string", "description": "ISO-8601 timestamp; only recent_audit entries >= since_ts"},
                    },
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_debug_report,
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
                self._tab_ids.pop(name, None)
        self._active_session = None

    def _get_pages(self, browser: Any) -> list:
        pages = []
        if hasattr(browser, "get_pages") and callable(getattr(browser, "get_pages")):
            try:
                pages = browser.get_pages() or []
            except Exception:
                pages = []
        if not pages:
            try:
                p = browser.page_getter()
                if p:
                    pages = [p]
            except Exception:
                pages = []
        return [p for p in pages if p is not None]

    def _get_current_page(self, browser: Any) -> Any:
        try:
            return browser.page_getter()
        except Exception:
            return None

    def _get_tab_id(self, session_name: str, page: Any) -> str:
        session_tabs = self._tab_ids.setdefault(session_name, {})
        key = id(page)
        if key not in session_tabs:
            session_tabs[key] = f"tab-{self._next_tab_id}"
            self._next_tab_id += 1
        return session_tabs[key]

    async def _page_title(self, page: Any) -> str:
        if page is None:
            return ""
        if hasattr(page, "title"):
            title_attr = getattr(page, "title")
            try:
                if callable(title_attr):
                    value = title_attr()
                    if asyncio.iscoroutine(value):
                        value = await value
                    return str(value or "")
                return str(title_attr or "")
            except Exception:
                return ""
        return ""

    def _page_url(self, page: Any) -> str:
        if page is None:
            return ""
        try:
            return str(getattr(page, "url", "") or "")
        except Exception:
            return ""

    def _dom_summary_from_signals(self, title: str, url: str) -> Dict[str, Any]:
        sig = f"{title} {url}".lower()
        return {
            "has_captcha_signal": any(k in sig for k in ("captcha", "verify you are human", "challenge")),
            "has_rate_limit_signal": any(k in sig for k in ("too many requests", "rate limit", "429")),
        }

    def _resolve_snapshot_path(self, session_name: str, tab_id: str) -> Path:
        safe_session = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in session_name) or "default"
        safe_tab = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in tab_id) or "tab"
        folder = self._snapshot_root / safe_session
        folder.mkdir(parents=True, exist_ok=True)
        root = self._snapshot_root.resolve()
        resolved_folder = folder.resolve()
        if root != resolved_folder and root not in resolved_folder.parents:
            raise ToolError(
                "MCP_SECURITY_PATH_DENIED",
                "Snapshot directory resolved outside allowed snapshot root.",
                {"snapshot_root": str(root), "resolved_folder": str(resolved_folder)},
            )
        self._prune_session_snapshots(resolved_folder)
        return resolved_folder / f"{safe_tab}_{int(time.time() * 1000)}.png"

    def _prune_session_snapshots(self, folder: Path) -> None:
        files = sorted(
            [p for p in folder.glob("*.png") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for stale in files[self._snapshot_max_per_session - 1 :]:
            try:
                stale.unlink(missing_ok=True)
            except Exception:
                pass

    def _guard_observability_payload(self, payload: Dict[str, Any], endpoint: str) -> Dict[str, Any]:
        redacted = AuditLogger._redact_sensitive(payload)
        raw = json.dumps(redacted, default=str)
        if len(raw) <= self._observability_max_chars:
            return redacted
        clipped = raw[: self._observability_max_chars]
        return {
            "status": redacted.get("status", "success") if isinstance(redacted, dict) else "success",
            "truncated": True,
            "message": "Observability payload truncated by server size guardrail.",
            "details": {
                "endpoint": endpoint,
                "max_chars": self._observability_max_chars,
                "original_chars": len(raw),
            },
            "preview": clipped,
        }

    async def _resolve_page(self, session_name: str, browser: Any, tab_id: Optional[str]) -> tuple[str, Any]:
        pages = self._get_pages(browser)
        current_page = self._get_current_page(browser)
        if not pages:
            raise ToolError("MCP_PAGE_NOT_FOUND", "No active page found for session.")
        if tab_id:
            for p in pages:
                token = self._get_tab_id(session_name, p)
                if token == tab_id:
                    return token, p
            raise ToolError("MCP_TAB_NOT_FOUND", f"tab_id '{tab_id}' was not found.")
        selected = current_page if current_page in pages else pages[0]
        return self._get_tab_id(session_name, selected), selected

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

    async def _tool_stealth_tabs_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        pages = self._get_pages(browser)
        current_page = self._get_current_page(browser)

        tabs = []
        for idx, page in enumerate(pages, start=1):
            tab_id = self._get_tab_id(session_name, page)
            tabs.append(
                {
                    "tab_id": tab_id,
                    "index": idx,
                    "title": await self._page_title(page),
                    "url": self._page_url(page),
                    "is_current": page is current_page,
                }
            )

        payload = self._tool_ok_payload(
            {
                "session_name": session_name,
                "active_tab_id": self._get_tab_id(session_name, current_page) if current_page else None,
                "tab_count": len(tabs),
                "tabs": tabs,
            }
        )
        return self._guard_observability_payload(payload, "stealth_tabs_list")

    async def _tool_stealth_tab_snapshot(self, args: Dict[str, Any]) -> Dict[str, Any]:
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        full_page = bool(args.get("full_page", False))
        tab_id, page = await self._resolve_page(session_name, browser, args.get("tab_id"))

        snapshot_path = self._resolve_snapshot_path(session_name, tab_id)
        screenshot_call = page.screenshot(path=str(snapshot_path), full_page=full_page)
        if asyncio.iscoroutine(screenshot_call):
            await screenshot_call

        title = await self._page_title(page)
        url = self._page_url(page)
        payload = self._tool_ok_payload(
            {
                "session_name": session_name,
                "tab_id": tab_id,
                "title": title,
                "url": url,
                "screenshot_path": str(snapshot_path.resolve()),
                "full_page": full_page,
                "dom_summary": self._dom_summary_from_signals(title, url),
            }
        )
        return self._guard_observability_payload(payload, "stealth_tab_snapshot")

    async def _tool_stealth_session_timeline(self, args: Dict[str, Any]) -> Dict[str, Any]:
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        limit_raw = args.get("limit", self._timeline_default_limit)
        try:
            limit = int(limit_raw)
        except Exception:
            raise ToolError("MCP_VALIDATION_ERROR", "limit must be an integer")
        limit = max(1, min(limit, self._timeline_max_limit))

        cursor = args.get("cursor")
        since_ts = args.get("since_ts")
        replay = browser.get_replay_sequence(limit, cursor=cursor, since_ts=since_ts) if hasattr(browser, "get_replay_sequence") else {"status": "unsupported", "sequence": []}
        sequence = replay.get("sequence", []) if isinstance(replay, dict) else []
        if not isinstance(sequence, list):
            sequence = []

        # Minimal pagination contract (#381): compute next_cursor/has_more using heuristic (full page => more likely exists)
        next_cursor = None
        has_more = False
        if sequence and len(sequence) == limit:
            has_more = True
            first_evt = sequence[0] if sequence else None
            if isinstance(first_evt, dict):
                next_cursor = first_evt.get("timestamp") or first_evt.get("ts")
        payload = self._tool_ok_payload(
            {
                "session_name": session_name,
                "timeline_status": replay.get("status", "unknown") if isinstance(replay, dict) else "unknown",
                "count": len(sequence),
                "events": sequence,
                "next_cursor": next_cursor,
                "has_more": has_more,
                "truncated": False,
            }
        )
        return self._guard_observability_payload(payload, "stealth_session_timeline")

    async def _tool_stealth_debug_report(self, args: Dict[str, Any]) -> Dict[str, Any]:
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        print_report = bool(args.get("print_report", False))
        # #381 pagination params (applied to recent_audit inside the debug report)
        limit_raw = args.get("limit")
        limit = None
        if limit_raw is not None:
            try:
                limit = int(limit_raw)
                limit = max(1, min(limit, 100))
            except Exception:
                limit = 15
        cursor = args.get("cursor")
        since_ts = args.get("since_ts")
        debug = await browser.debug_report(print_report=print_report, limit=limit, cursor=cursor, since_ts=since_ts)
        if debug.get("status") != "success":
            raise ToolError("MCP_DEBUG_REPORT_FAILED", debug.get("message", "debug_report failed"), debug)
        # Compute consistent pagination fields based on the recent_audit included in report (heuristic)
        report = debug.get("report", {}) if isinstance(debug, dict) else {}
        recent = report.get("recent_audit", []) if isinstance(report, dict) else []
        count = len(recent) if isinstance(recent, list) else 0
        page_limit = limit if limit is not None else 15
        has_more = (count == page_limit)
        next_cursor = None
        if has_more and recent:
            first = recent[0]
            if isinstance(first, dict):
                next_cursor = first.get("timestamp")
        payload = self._tool_ok_payload({
            "session_name": session_name,
            "debug": debug,
            "count": count,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "truncated": False,
        })
        return self._guard_observability_payload(payload, "stealth_debug_report")

    async def _tool_stealth_close(self, args: Dict[str, Any]) -> Dict[str, Any]:
        close_all = bool(args.get("close_all", False))
        if close_all:
            count = len(self._sessions)
            await self._close_all_sessions()
            return self._tool_ok_payload({"closed_all": True, "closed_sessions": count})

        session_name, browser = await self._resolve_browser(args.get("session_name"))
        await browser.close()
        self._sessions.pop(session_name, None)
        self._tab_ids.pop(session_name, None)
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
                    "Use stealth_launch to start a session, then stealth_navigate / stealth_scrape. "
                    "Use stealth_tabs_list, stealth_tab_snapshot, stealth_session_timeline, and stealth_status "
                    "to inspect runtime state."
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
