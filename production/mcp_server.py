"""
MCP stdio server runtime for Agentic Stealth Browser.

This module intentionally implements a minimal MCP JSON-RPC surface directly
so the repository can run an MCP server without extra runtime dependencies.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import logging
import os
import socket
import sys
import time
import urllib.parse
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
from production.approval_gate import ApprovalDecision, ApprovalGate
from production.mcp_input_validator import InputValidationError, validate_tool_input
from production.policy_engine import PolicyEngine


JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "agentic-stealth-browser"
SERVER_TITLE = "Agentic Stealth Browser MCP Server"

try:
    import importlib.metadata

    SERVER_VERSION = importlib.metadata.version("agentic-stealth-browser")
except Exception:
    SERVER_VERSION = (
        "unknown"  # fallback during dev / editable installs before metadata written
    )


class ToolError(Exception):
    """Tool-level execution error returned inside CallToolResult."""

    def __init__(
        self, error_code: str, message: str, details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details or {}


# ----------------------------------------------------------------------------- #
# SSRF protection – reject URLs that resolve to private / loopback addresses.  #
# ----------------------------------------------------------------------------- #

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),  # loopback (includes 127.0.0.1)
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("0.0.0.0/8"),  # current network
    ipaddress.ip_network("10.0.0.0/8"),  # private (RFC 1918)
    ipaddress.ip_network("172.16.0.0/12"),  # private (RFC 1918)
    ipaddress.ip_network("192.168.0.0/16"),  # private (RFC 1918)
    ipaddress.ip_network("169.254.0.0/16"),  # link-local (includes 169.254.169.254)
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


def is_url_safe(url: str) -> bool:
    """
    Return True when the URL is safe to navigate / scrape (MCP outbound guard).

    Fail CLOSED for security:
    - only http/https schemes are permitted (no file:, javascript:, data:, ftp:, etc.)
    - missing host or parse failures
    - DNS resolution errors or empty results (no silent pass on transient failure)
    - resolved IPs inside blocked private/loopback/link-local/cloud-metadata ranges

    Used by stealth_navigate / stealth_scrape (and second-layer for remote CDP attach).
    """

    ALLOWED_SCHEMES = {"http", "https"}

    def _ip_blocked(ip_str: str) -> bool:
        """Return True when the string represents a blocked IP or IP network."""
        try:
            ip = ipaddress.ip_address(ip_str)
            for network in _BLOCKED_NETWORKS:
                if ip in network:
                    return True
        except ValueError:
            logging.getLogger(__name__).debug("suppressed exception", exc_info=True)
        return False

    try:
        parsed = urllib.parse.urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme and scheme not in ALLOWED_SCHEMES:
            return False

        host = parsed.hostname

        # Fallback for URLs that urlparse can't extract a hostname from
        # (e.g. bare IPv6 literals like http://::1/).
        if not host:
            host = url.split("://", 1)[-1].split("/")[0].split("?")[0].rstrip("/")
            if not host:
                return False

        # If the hostname is already a literal IP address, check it directly.
        if _ip_blocked(host):
            return False

        # Resolve hostname via DNS for hostnames that aren't blocked literals.
        # Fail closed on resolution errors (no transient-DNS bypass).
        try:
            addr_info = socket.getaddrinfo(host, None)
        except Exception:
            return False
        if not addr_info:
            return False

        for family, _, _, _, sockaddr in addr_info:
            if family == socket.AF_INET:
                ip = ipaddress.ip_address(sockaddr[0])
            elif family == socket.AF_INET6:
                ip = ipaddress.ip_address(sockaddr[0])
            else:
                continue  # unknown – skip
            for network in _BLOCKED_NETWORKS:
                if ip in network:
                    return False
        return True
    except Exception:
        return False


def is_loopback_host(url: str) -> bool:
    """Return True when the URL's host is a loopback address.

    Use this for the CDP attach gate: we want the operator to be able to
    attach to a browser on the same machine (``localhost`` / ``127.0.0.1`` /
    ``::1``) even when the broader ``is_url_safe`` check rejects those same
    addresses for outbound navigation. The attach gate is followed by a
    second ``is_url_safe`` check so that link-local / RFC-1918 hosts are
    still rejected for ``allow_remote=true`` paths.

    Loopback means:
      * literal "localhost", OR
      * IPv4 in 127.0.0.0/8, OR
      * IPv6 ::1/128, OR
      * a hostname that resolves (via :func:`socket.getaddrinfo`) to any IP
        in the loopback ranges above.

    Anything else — RFC-1918, link-local, public IPs, or unresolvable
    hostnames that are not "localhost" — returns False.
    """
    normalised = url.strip()
    if not normalised.startswith(("http://", "https://", "ws://", "wss://")):
        normalised = f"http://{normalised}"
    try:
        parsed = urllib.parse.urlparse(normalised)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in ("localhost",):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback
    except ValueError:
        logging.getLogger(__name__).debug("suppressed exception", exc_info=True)
    # Hostname — try DNS.
    try:
        for family, _, _, _, sockaddr in socket.getaddrinfo(host, None):
            if family == socket.AF_INET:
                if ipaddress.ip_address(sockaddr[0]).is_loopback:
                    return True
            elif family == socket.AF_INET6:
                if ipaddress.ip_address(sockaddr[0]).is_loopback:
                    return True
    except Exception:
        return False
    return False


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
    output_schema: Optional[Dict[str, Any]] = None

    def as_mcp_tool(self) -> Dict[str, Any]:
        sanitized_description, _ = sanitize_tool_description(self.description)
        result: Dict[str, Any] = {
            "name": self.name,
            "description": sanitized_description,
            "inputSchema": self.input_schema,
        }
        if self.output_schema is not None:
            result["outputSchema"] = self.output_schema
        return result

    def json_schema(self) -> Dict[str, Any]:
        """Return full JSON Schema representation for this tool (input + output)."""
        return {
            "name": self.name,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema or {},
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


# Imported here (not with the top-of-file imports) so that ToolError / SERVER_* /
# is_url_safe / is_loopback_host above are already bound in this module's namespace
# before mcp_handlers.py imports them back — avoids a circular-import NameError.
from production.mcp_handlers import _MCPToolHandlers  # noqa: E402


class StealthMCPServer(_MCPToolHandlers):
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
        # #456: installation-safe workflow library location (user-writable for teach/replay writes;
        # also discover bundled from package data for `stealth_workflow_list` etc even from arbitrary cwd).
        self._workflow_library_root = (
            Path.home() / ".agentic-browser" / "workflows" / "library"
        )
        self._workflow_library_root.mkdir(parents=True, exist_ok=True)
        try:
            import importlib.resources as pkgres

            self._bundled_workflow_root = pkgres.files("workflows") / "library"
        except Exception:
            self._bundled_workflow_root = None
        self._tools: Dict[str, ToolSpec] = self._build_tools()

        # Security gates wired into the dispatch path (see handle_jsonrpc tools/call
        # and _tool_stealth_replay). Posture:
        #   - PolicyEngine: step-type / domain allow-lists. Enforced by default from
        #     policy YAML in ~/.agentic-browser/policies. With no policy files the
        #     default policy allows everything (fail-open), so normal flows are unchanged.
        #     Set STEALTH_MCP_POLICY to activate a named loaded policy.
        #   - ApprovalGate: sensitive-action approval. Fail-closed by default — sensitive
        #     actions on unknown domains return PENDING, surfaced to the caller as
        #     MCP_APPROVAL_REQUIRED, until resolved via resolve_pending(request_id).
        #     Set STEALTH_APPROVAL_MODE=permissive to restore the pre-3.0 auto-approve
        #     (fail-open) behavior for headless/no-human-in-the-loop deployments.
        self._policy_engine = PolicyEngine()
        try:
            self._policy_engine.load_policies()
        except Exception:
            logging.getLogger(__name__).debug("suppressed exception", exc_info=True)
        active_policy = os.getenv("STEALTH_MCP_POLICY")
        if active_policy:
            self._policy_engine.set_active(active_policy)
        approval_mode = os.getenv("STEALTH_APPROVAL_MODE", "enforce").strip().lower()
        self._approval_gate = ApprovalGate(auto_approve_known_domains=True)
        if approval_mode == "permissive":
            # Legacy fail-open posture: auto-approve every sensitive action.
            self._approval_gate.set_allow_callback(lambda req: ApprovalDecision.ALLOWED)

    def _get_agent_browser_cls(self):
        if self._agent_browser_cls is not None:
            return self._agent_browser_cls
        from core.agent_browser import AgentBrowser

        self._agent_browser_cls = AgentBrowser
        return self._agent_browser_cls

    def _jsonrpc_result(
        self, request_id: Any, result: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}

    def _jsonrpc_error(
        self,
        request_id: Any,
        code: int,
        message: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": code, "message": message, "data": data or {}},
        }

    def _tool_error_payload(
        self, error_code: str, message: str, details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
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

    def _tool_result(
        self, payload: Dict[str, Any], is_error: bool = False
    ) -> Dict[str, Any]:
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
                        "session_name": {
                            "type": "string",
                            "description": "Session identifier.",
                        },
                        "headless": {"type": "boolean", "default": True},
                        "debug": {"type": "boolean", "default": False},
                        "debug_cdp": {
                            "type": "boolean",
                            "default": False,
                            "description": "Opt-in CDP remote debugging (localhost-only). Use stealth_get_cdp_endpoint after launch to retrieve WS URL + metadata. Disabled returns explicit status.",
                        },
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
                        "limit": {
                            "type": "integer",
                            "default": 30,
                            "minimum": 1,
                            "maximum": 200,
                        },
                        "cursor": {
                            "type": "string",
                            "description": "Opaque cursor for next page (typically previous next_cursor, used as before-ts boundary for older events)",
                        },
                        "since_ts": {
                            "type": "string",
                            "description": "ISO-8601 timestamp; only return events with timestamp >= since_ts (for incremental/polling)",
                        },
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
                        "limit": {
                            "type": "integer",
                            "default": 15,
                            "minimum": 1,
                            "maximum": 100,
                        },
                        "cursor": {
                            "type": "string",
                            "description": "Opaque cursor for next page of recent_audit (typically previous next_cursor)",
                        },
                        "since_ts": {
                            "type": "string",
                            "description": "ISO-8601 timestamp; only recent_audit entries >= since_ts",
                        },
                    },
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_debug_report,
            ),
            ToolSpec(
                name="stealth_get_cdp_endpoint",
                description="Return the CDP WebSocket endpoint, port, version metadata (and security warnings) for external attach. ONLY works if launched with debug_cdp=True; otherwise returns explicit {'status': 'disabled', 'message': '...'}. Binds to 127.0.0.1 only. See MCP_BROWSER_OBSERVABILITY.md.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_get_cdp_endpoint,
            ),
            ToolSpec(
                name="stealth_attach_over_cdp",
                description=(
                    "Attach a stealth session to an EXISTING browser exposing a CDP endpoint "
                    "(e.g. Chrome launched with --remote-debugging-port=9222). Complements debug_cdp launch. "
                    "Primary use: drive a desktop browser from a different host (e.g. WSL→Windows). "
                    "By default only localhost endpoints are allowed; set allow_remote=true for non-loopback hosts. "
                    "Stealth init scripts (navigator/canvas/WebGL/audio) are injected on the chosen context; "
                    "launch-time stealth (TLS/JA3 profile, regional preset, user-data-dir) is NOT applied — "
                    "those require AgentBrowser to launch the process. close() leaves the external browser alive."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string"},
                        "cdp_url": {
                            "type": "string",
                            "description": "http://host:port, ws://..., or bare host:port. /json/version is auto-resolved.",
                        },
                        "new_context": {
                            "type": "boolean",
                            "default": False,
                            "description": "Create a fresh context instead of adopting context_index. Recommended to avoid disturbing user tabs/cookies.",
                        },
                        "context_index": {"type": "integer", "default": 0},
                        "apply_stealth": {"type": "boolean", "default": True},
                        "allow_remote": {
                            "type": "boolean",
                            "default": False,
                            "description": "Required to allow non-loopback CDP hosts. Off by default for safety.",
                        },
                        "anonymous": {"type": "boolean", "default": True},
                        "ephemeral": {"type": "boolean", "default": False},
                    },
                    "required": ["cdp_url"],
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_attach_over_cdp,
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
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_capabilities,
            ),
            ToolSpec(
                name="stealth_teach",
                description="Record browser actions into a replayable workflow file. Attaches recorder to an active session.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_name": {"type": "string"},
                        "workflow_name": {
                            "type": "string",
                            "description": "The output workflow name.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional workflow description.",
                        },
                        "capture_seconds": {
                            "type": "integer",
                            "default": 60,
                            "minimum": 1,
                            "maximum": 600,
                        },
                    },
                    "required": ["session_name", "workflow_name"],
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_teach,
            ),
            ToolSpec(
                name="stealth_replay",
                description="Load and execute a workflow file against the current session.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Relative to workflow library root.",
                        },
                        "variables": {
                            "type": "object",
                            "description": "Runtime variable overrides.",
                        },
                        "session_name": {"type": "string"},
                    },
                    "required": ["filename"],
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_replay,
            ),
            ToolSpec(
                name="stealth_workflow_list",
                description="List available workflow files, optionally filtered by platform/pattern.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "platform": {
                            "type": "string",
                            "description": "Filter by directory: upwork, linkedin, common.",
                        },
                        "pattern": {
                            "type": "string",
                            "description": "Filename glob filter.",
                        },
                    },
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_workflow_list,
            ),
            ToolSpec(
                name="stealth_workflow_delete",
                description="Delete a workflow file from the library. Path-constrained for safety.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Relative to workflow library root.",
                        },
                        "confirm": {
                            "type": "boolean",
                            "description": "Must be true to confirm deletion.",
                        },
                    },
                    "required": ["filename", "confirm"],
                    "additionalProperties": False,
                },
                handler=self._tool_stealth_workflow_delete,
            ),
        ]
        return {t.name: t for t in tools}

    def list_tools(self) -> Dict[str, Any]:
        return {"tools": [tool.as_mcp_tool() for tool in self._tools.values()]}

    def list_tool_schemas(self) -> Dict[str, Any]:
        """Return complete JSON Schemas (input + output) for all tools."""
        schemas = {}
        for name, tool in self._tools.items():
            schemas[name] = tool.json_schema()
        return {"schemas": schemas}

    @staticmethod
    def unified_result_envelope(
        payload: Dict[str, Any], is_error: bool = False
    ) -> Dict[str, Any]:
        """Normalize every MCP tool response into a consistent typed envelope.

        Every result contains:
          - status: "success" | "error"
          - data: tool-specific payload
          - meta: { tool, elapsed_ms, server_version }
        """
        status = "error" if is_error else payload.get("status", "success")
        if status not in ("success", "error"):
            status = "success"
        return {
            "status": status,
            "data": payload,
            "meta": {
                "tool": payload.get("tool", "unknown"),
                "server_version": SERVER_VERSION,
            },
        }

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
                logging.getLogger(__name__).debug("suppressed exception", exc_info=True)
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
            "has_captcha_signal": any(
                k in sig for k in ("captcha", "verify you are human", "challenge")
            ),
            "has_rate_limit_signal": any(
                k in sig for k in ("too many requests", "rate limit", "429")
            ),
        }

    def _resolve_snapshot_path(self, session_name: str, tab_id: str) -> Path:
        safe_session = (
            "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in session_name)
            or "default"
        )
        safe_tab = (
            "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in tab_id)
            or "tab"
        )
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
                logging.getLogger(__name__).debug("suppressed exception", exc_info=True)

    def _guard_observability_payload(
        self, payload: Dict[str, Any], endpoint: str
    ) -> Dict[str, Any]:
        redacted = AuditLogger._redact_sensitive(payload)
        raw = json.dumps(redacted, default=str)
        if len(raw) <= self._observability_max_chars:
            return redacted
        clipped = raw[: self._observability_max_chars]
        return {
            "status": redacted.get("status", "success")
            if isinstance(redacted, dict)
            else "success",
            "truncated": True,
            "message": "Observability payload truncated by server size guardrail.",
            "details": {
                "endpoint": endpoint,
                "max_chars": self._observability_max_chars,
                "original_chars": len(raw),
            },
            "preview": clipped,
        }

    async def _resolve_page(
        self, session_name: str, browser: Any, tab_id: Optional[str]
    ) -> tuple[str, Any]:
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

    async def handle_jsonrpc(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        msg_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}

        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != JSONRPC_VERSION
            or not method
        ):
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

        if method == "health":
            return self._jsonrpc_result(
                msg_id,
                {
                    "status": "healthy",
                    "server": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "active_sessions": len(self._sessions),
                    "uptime_seconds": int(
                        time.monotonic()
                        - getattr(self, "_start_time", time.monotonic())
                    ),
                },
            )

        if method == "tools/list":
            return self._jsonrpc_result(msg_id, self.list_tools())

        if method == "tools/call":
            if not isinstance(params, dict):
                return self._jsonrpc_error(msg_id, -32602, "Invalid params")
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(tool_name, str) or not tool_name:
                return self._jsonrpc_error(
                    msg_id, -32602, "Invalid params: tool name required"
                )
            if not isinstance(arguments, dict):
                return self._jsonrpc_error(
                    msg_id, -32602, "Invalid params: arguments must be object"
                )

            tool = self._tools.get(tool_name)
            if not tool:
                payload = self._tool_error_payload(
                    "MCP_TOOL_NOT_FOUND",
                    f"Unknown tool '{tool_name}'",
                    {"available_tools": list(self._tools.keys())},
                )
                return self._jsonrpc_result(
                    msg_id, self._tool_result(payload, is_error=True)
                )

            # #455: enforce declarative validation before any handler execution.
            # Rejects unknown args (matches additionalProperties: false in schemas),
            # type/length/range/required/pattern violations. Never calls handler on bad input.
            try:
                validated_args = validate_tool_input(tool_name, arguments)
            except InputValidationError as ive:
                payload = self._tool_error_payload(
                    "MCP_VALIDATION_ERROR",
                    f"Invalid input for {ive.tool_name}: {ive.field} {ive.reason}",
                    {"tool": ive.tool_name, "field": ive.field, "reason": ive.reason},
                )
                return self._jsonrpc_result(
                    msg_id, self._tool_result(payload, is_error=True)
                )

            # Security gate: sensitive-action approval before handler execution.
            # No-op for non-sensitive tools; permissive unless an operator installs an
            # approval callback (see __init__). Blocks on DENIED/PENDING when enforced.
            gate = self._approval_gate.check_sensitive(
                tool_name, validated_args, str(validated_args.get("session_name") or "")
            )
            if gate.decision != ApprovalDecision.ALLOWED:
                payload = self._tool_error_payload(
                    "MCP_APPROVAL_REQUIRED",
                    f"Action '{tool_name}' requires approval: {gate.reason}"
                    " — approve via resolve_pending(request_id) or set STEALTH_APPROVAL_MODE=permissive",
                    {
                        "tool": tool_name,
                        "request_id": gate.request_id,
                        "decision": gate.decision.value,
                    },
                )
                return self._jsonrpc_result(
                    msg_id, self._tool_result(payload, is_error=True)
                )

            try:
                payload = await tool.handler(validated_args)
                return self._jsonrpc_result(
                    msg_id, self._tool_result(payload, is_error=False)
                )
            except ToolError as te:
                payload = self._tool_error_payload(
                    te.error_code, te.message, te.details
                )
                return self._jsonrpc_result(
                    msg_id, self._tool_result(payload, is_error=True)
                )
            except Exception as exc:
                payload = self._tool_error_payload("MCP_INTERNAL_ERROR", str(exc))
                return self._jsonrpc_result(
                    msg_id, self._tool_result(payload, is_error=True)
                )

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
                err = self._jsonrpc_error(
                    None, -32700, "Parse error", {"error": str(exc)}
                )
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
    parser = argparse.ArgumentParser(
        description="Agentic Stealth Browser MCP server (stdio)"
    )
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
