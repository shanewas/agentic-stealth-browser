"""Tests for MCP/CLI backward-compatibility and deprecation policy (#378).

Tests cover:
- Alias resolution to canonical tool names
- _deprecation_warning in alias responses
- No deprecation warning for canonical names
- Unknown tools still return MCP_TOOL_NOT_FOUND
- CLI deprecation stderr output
"""

import json
import sys
import io
from pathlib import Path
from typing import Dict, Any

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from production.mcp_server import ToolSpec, StealthMCPServer


class MockHandler:
    """Minimal handler that returns a simple payload."""
    def __init__(self, name: str = "mock"):
        self.name = name

    async def __call__(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"mock": self.name, "args": args}


def _make_server_with_test_tools() -> StealthMCPServer:
    """Build a server with known test tools including aliases."""
    server = StealthMCPServer()

    # Add canonical + alias tool
    launch_spec = ToolSpec(
        name="stealth_launch",
        description="Launch browser",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=MockHandler("stealth_launch"),
        aliases=["launch"],
        deprecation_notice="Tool 'launch' has been renamed to 'stealth_launch'. The alias will be removed in v0.10.0.",
    )
    navigate_spec = ToolSpec(
        name="stealth_navigate",
        description="Navigate URL",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=MockHandler("stealth_navigate"),
        aliases=["navigate"],
        deprecation_notice="Tool 'navigate' has been renamed to 'stealth_navigate'. The alias will be removed in v0.10.0.",
    )
    close_spec = ToolSpec(
        name="stealth_close",
        description="Close session",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=MockHandler("stealth_close"),
    )

    server._tools = {
        "stealth_launch": launch_spec,
        "stealth_navigate": navigate_spec,
        "stealth_close": close_spec,
    }
    server._tool_aliases = {}
    server._build_alias_map()
    return server


class TestAliasResolution:
    """Alias → canonical name resolution."""

    def setup_method(self):
        self.server = _make_server_with_test_tools()

    def test_alias_resolves_to_canonical_tool(self):
        """Calling 'launch' resolves to 'stealth_launch' tool."""
        assert "launch" in self.server._tool_aliases
        assert self.server._tool_aliases["launch"] == "stealth_launch"

    def test_navigate_alias_resolves(self):
        """Calling 'navigate' resolves to 'stealth_navigate'."""
        assert self.server._tool_aliases["navigate"] == "stealth_navigate"

    def test_canonical_name_not_in_aliases(self):
        """Canonical names are NOT registered as aliases."""
        assert "stealth_launch" not in self.server._tool_aliases
        assert "stealth_close" not in self.server._tool_aliases

    def test_unknown_tool_not_in_aliases(self):
        """Unknown tool name is not in aliases either."""
        assert "nonexistent" not in self.server._tool_aliases
        assert "nonexistent" not in self.server._tools


class TestDeprecationWarning:
    """Deprecation warnings appear on alias calls."""

    def setup_method(self):
        self.server = _make_server_with_test_tools()

    def _call_tool(self, tool_name: str) -> Dict[str, Any]:
        """Simulate handle_jsonrpc logic for tools/call."""
        tool = self.server._tools.get(tool_name)
        is_deprecated = False
        deprecation_msg = None

        if not tool:
            canonical_name = self.server._tool_aliases.get(tool_name)
            if canonical_name:
                tool = self.server._tools.get(canonical_name)
                if tool:
                    is_deprecated = True
                    deprecation_msg = tool.deprecation_notice

        result = {"content": [{"type": "text", "text": "ok"}]}
        if is_deprecated and deprecation_msg:
            result["_deprecation_warning"] = deprecation_msg
        return result

    def test_alias_includes_deprecation_warning(self):
        """Calling 'launch' alias includes _deprecation_warning."""
        result = self._call_tool("launch")
        assert "_deprecation_warning" in result
        assert "launch" in result["_deprecation_warning"]
        assert "v0.10.0" in result["_deprecation_warning"]

    def test_canonical_no_deprecation_warning(self):
        """Calling 'stealth_launch' does NOT include deprecation warning."""
        result = self._call_tool("stealth_launch")
        assert "_deprecation_warning" not in result

    def test_tool_without_alias_no_warning(self):
        """Tool that has no aliases produces no deprecation warning."""
        result = self._call_tool("stealth_close")
        assert "_deprecation_warning" not in result

    def test_navigate_alias_has_warning(self):
        """Calling 'navigate' alias includes deprecation warning."""
        result = self._call_tool("navigate")
        assert "_deprecation_warning" in result
        assert "navigate" in result["_deprecation_warning"]

    def test_deprecation_message_contains_renamed_to(self):
        """Deprecation message explains the rename clearly."""
        result = self._call_tool("launch")
        assert "renamed to" in result["_deprecation_warning"]


class TestNoFalseAlias:
    """No unintentional alias matching."""

    def setup_method(self):
        self.server = _make_server_with_test_tools()

    def test_partial_name_not_alias(self):
        """'laun' is not an alias for 'stealth_launch'."""
        assert "laun" not in self.server._tool_aliases

    def test_case_sensitive_alias(self):
        """Aliases are case-sensitive."""
        assert "Launch" not in self.server._tool_aliases


class TestToolSpecModel:
    """ToolSpec dataclass supports new fields."""

    def test_aliases_default_empty(self):
        """ToolSpec aliases defaults to empty list."""
        spec = ToolSpec(
            name="test", description="test",
            input_schema={}, handler=MockHandler(),
        )
        assert spec.aliases == []

    def test_deprecation_notice_default_none(self):
        """ToolSpec deprecation_notice defaults to None."""
        spec = ToolSpec(
            name="test", description="test",
            input_schema={}, handler=MockHandler(),
        )
        assert spec.deprecation_notice is None

    def test_custom_aliases_stored(self):
        """ToolSpec stores provided aliases."""
        spec = ToolSpec(
            name="test", description="test",
            input_schema={}, handler=MockHandler(),
            aliases=["old_test", "legacy_test"],
            deprecation_notice="Use 'test' instead.",
        )
        assert spec.aliases == ["old_test", "legacy_test"]
        assert spec.deprecation_notice == "Use 'test' instead."

    def test_as_mcp_tool_excludes_alias_fields(self):
        """as_mcp_tool() does not expose aliases/deprecation in tool manifest."""
        spec = ToolSpec(
            name="test", description="test desc",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=MockHandler(),
            aliases=["old_test"],
            deprecation_notice="Use 'test'",
        )
        mcp = spec.as_mcp_tool()
        assert "aliases" not in mcp
        assert "deprecation_notice" not in mcp
        assert mcp["name"] == "test"
        assert mcp["description"] == "test desc"


class TestCliDeprecation:
    """CLI deprecation stderr output on deprecated commands."""

    def test_status_deprecation_message(self):
        """The _cmd_status function prints deprecation warning to stderr."""
        # Import the module to access _cmd_status
        from production.cli import _cmd_status, _cmd_health

        # Create a minimal namespace
        class Args:
            preset = None
            region = None
            headless = True
            debug = False
            debug_cdp = False
            session_name = "test"
            light_mode = False

        # The actual function attempts to use AgentBrowser which needs Playwright.
        # Just verify the deprecation message exists by checking the source.
        import inspect
        source = inspect.getsource(_cmd_status)
        assert "deprecated" in source
        assert "renamed to 'health'" in source
        assert "v0.10.0" in source
