"""
MCP Tool Input Validation — v1.4.0 Security Hardening

Provides declarative parameter validation for all MCP tools:
- Type checks (str, int, bool, dict, list)
- Max length constraints
- Allowed patterns / enums
- Required field enforcement
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set


class InputValidationError(Exception):
    def __init__(self, tool_name: str, field: str, reason: str):
        self.tool_name = tool_name
        self.field = field
        self.reason = reason
        super().__init__(f"[{tool_name}] {field}: {reason}")


@dataclass
class ParamRule:
    name: str
    expected_type: type = str
    required: bool = False
    max_length: Optional[int] = None
    min_length: Optional[int] = None
    max_value: Optional[int | float] = None
    min_value: Optional[int | float] = None
    allowed_values: Optional[Set[str]] = None
    pattern: Optional[str] = None

    def validate(self, value: Any) -> Optional[str]:
        if value is None:
            if self.required:
                return "required field is missing"
            return None

        if not isinstance(value, self.expected_type):
            return f"expected {self.expected_type.__name__}, got {type(value).__name__}"

        if isinstance(value, str):
            if self.max_length is not None and len(value) > self.max_length:
                return f"length {len(value)} exceeds max {self.max_length}"
            if self.min_length is not None and len(value) < self.min_length:
                return f"length {len(value)} below min {self.min_length}"
            if self.pattern and not re.match(self.pattern, value):
                return f"does not match pattern {self.pattern}"
            if self.allowed_values and value not in self.allowed_values:
                return f"value '{value}' not in allowed set"

        if isinstance(value, (int, float)):
            if self.max_value is not None and value > self.max_value:
                return f"value {value} exceeds max {self.max_value}"
            if self.min_value is not None and value < self.min_value:
                return f"value {value} below min {self.min_value}"

        return None


class ToolInputSchema:
    def __init__(self, tool_name: str, params: List[ParamRule]):
        self.tool_name = tool_name
        self.params: Dict[str, ParamRule] = {p.name: p for p in params}
        self._required = {p.name for p in params if p.required}

    def validate_or_raise(self, args: Dict[str, Any]) -> Dict[str, Any]:
        for param in self.params.values():
            value = args.get(param.name)
            err = param.validate(value)
            if err:
                raise InputValidationError(self.tool_name, param.name, err)
        # Enforce additionalProperties: false to match advertised JSON schemas.
        known = set(self.params.keys())
        unknown = set(args.keys()) - known
        if unknown:
            first = sorted(unknown)[0]
            raise InputValidationError(
                self.tool_name, first, "unknown argument (additionalProperties: false)"
            )
        return args


_PLATFORMS: Set[str] = {
    "linkedin",
    "upwork",
    "instagram",
    "twitter",
    "x",
    "facebook",
    "tiktok",
    "reddit",
    "youtube",
    "github",
    "custom",
    "unknown",
}

MCP_TOOL_SCHEMAS: Dict[str, ToolInputSchema] = {
    "stealth_launch": ToolInputSchema(
        "stealth_launch",
        [
            ParamRule("session_name", str, max_length=128),
            ParamRule("headless", bool),
            ParamRule("debug", bool),
            ParamRule("debug_cdp", bool),
            ParamRule("preset", str, max_length=64),
            ParamRule("region", str, max_length=32),
            ParamRule("anonymous", bool),
            ParamRule("ephemeral", bool),
            ParamRule("light_mode", bool),
            ParamRule("use_pooled_context", bool),
        ],
    ),
    "stealth_navigate": ToolInputSchema(
        "stealth_navigate",
        [
            ParamRule("session_name", str, max_length=128),
            ParamRule(
                "url", str, required=True, max_length=4096, pattern=r"^https?://"
            ),
            ParamRule("platform", str, max_length=32, allowed_values=_PLATFORMS),
            ParamRule("warm_up", bool),
            ParamRule("rate_limit", bool),
            ParamRule("domain", str, max_length=256),
            ParamRule("account", str, max_length=128),
        ],
    ),
    "stealth_load_cookies": ToolInputSchema(
        "stealth_load_cookies",
        [
            ParamRule("session_name", str, max_length=128),
            ParamRule("cookies_path", str, required=True, max_length=4096),
        ],
    ),
    "stealth_set_region": ToolInputSchema(
        "stealth_set_region",
        [
            ParamRule("session_name", str, max_length=128),
            ParamRule("region", str, required=True, max_length=32),
            ParamRule("relaunch", bool),
        ],
    ),
    "stealth_scrape": ToolInputSchema(
        "stealth_scrape",
        [
            ParamRule("session_name", str, max_length=128),
            ParamRule(
                "url", str, required=True, max_length=4096, pattern=r"^https?://"
            ),
            ParamRule("extract_images", bool),
            ParamRule("platform", str, max_length=32, allowed_values=_PLATFORMS),
        ],
    ),
    "stealth_status": ToolInputSchema(
        "stealth_status",
        [
            ParamRule("session_name", str, max_length=128),
            ParamRule("include_debug", bool),
        ],
    ),
    "stealth_tabs_list": ToolInputSchema(
        "stealth_tabs_list",
        [
            ParamRule("session_name", str, max_length=128),
        ],
    ),
    "stealth_tab_snapshot": ToolInputSchema(
        "stealth_tab_snapshot",
        [
            ParamRule("session_name", str, max_length=128),
            ParamRule("tab_id", str, max_length=64),
            ParamRule("full_page", bool),
        ],
    ),
    "stealth_session_timeline": ToolInputSchema(
        "stealth_session_timeline",
        [
            ParamRule("session_name", str, max_length=128),
            ParamRule("limit", int, min_value=1, max_value=200),
            ParamRule("cursor", str, max_length=64),
            ParamRule("since_ts", str, max_length=64),
        ],
    ),
    "stealth_debug_report": ToolInputSchema(
        "stealth_debug_report",
        [
            ParamRule("session_name", str, max_length=128),
            ParamRule("print_report", bool),
            ParamRule("limit", int, min_value=1, max_value=100),
            ParamRule("cursor", str, max_length=64),
            ParamRule("since_ts", str, max_length=64),
        ],
    ),
    "stealth_get_cdp_endpoint": ToolInputSchema(
        "stealth_get_cdp_endpoint",
        [
            ParamRule("session_name", str, max_length=128),
        ],
    ),
    "stealth_attach_over_cdp": ToolInputSchema(
        "stealth_attach_over_cdp",
        [
            ParamRule("session_name", str, max_length=128),
            ParamRule("cdp_url", str, required=True, max_length=512),
            ParamRule("new_context", bool),
            ParamRule("context_index", int, min_value=0, max_value=128),
            ParamRule("apply_stealth", bool),
            ParamRule("allow_remote", bool),
            ParamRule("anonymous", bool),
            ParamRule("ephemeral", bool),
        ],
    ),
    "stealth_close": ToolInputSchema(
        "stealth_close",
        [
            ParamRule("session_name", str, max_length=128),
            ParamRule("close_all", bool),
        ],
    ),
    "stealth_capabilities": ToolInputSchema("stealth_capabilities", []),
    "stealth_teach": ToolInputSchema(
        "stealth_teach",
        [
            ParamRule("session_name", str, required=True, max_length=128),
            ParamRule("workflow_name", str, required=True, max_length=128),
            ParamRule("description", str, max_length=1024),
            ParamRule("capture_seconds", int, min_value=1, max_value=600),
        ],
    ),
    "stealth_replay": ToolInputSchema(
        "stealth_replay",
        [
            ParamRule("session_name", str, max_length=128),
            ParamRule("filename", str, required=True, max_length=512),
            ParamRule("variables", dict),
        ],
    ),
    "stealth_workflow_list": ToolInputSchema(
        "stealth_workflow_list",
        [
            ParamRule("platform", str, max_length=32),
            ParamRule("pattern", str, max_length=256),
        ],
    ),
    "stealth_workflow_delete": ToolInputSchema(
        "stealth_workflow_delete",
        [
            ParamRule("filename", str, required=True, max_length=512),
            ParamRule("confirm", bool, required=True),
        ],
    ),
}


def validate_tool_input(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    schema = MCP_TOOL_SCHEMAS.get(tool_name)
    if not schema:
        return dict(args)
    return schema.validate_or_raise(args)


def get_tool_schema(tool_name: str) -> Optional[ToolInputSchema]:
    return MCP_TOOL_SCHEMAS.get(tool_name)
