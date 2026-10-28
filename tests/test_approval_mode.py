"""SEC-09: MCP approval gate is fail-closed by default; STEALTH_APPROVAL_MODE=permissive opts out."""

import pytest

from production.approval_gate import (
    MCP_TOOL_CLASSIFICATION,
    ApprovalDecision,
    is_sensitive_action,
)
from production.mcp_server import StealthMCPServer


def test_default_is_enforce(monkeypatch):
    monkeypatch.delenv("STEALTH_APPROVAL_MODE", raising=False)
    srv = StealthMCPServer()
    assert srv._approval_gate._allow_callback is None
    result = srv._approval_gate.check_sensitive("execute_js", {"code": "1"})
    assert result.decision.value == "pending"


def test_permissive_mode(monkeypatch):
    monkeypatch.setenv("STEALTH_APPROVAL_MODE", "permissive")
    srv = StealthMCPServer()
    result = srv._approval_gate.check_sensitive("execute_js", {"code": "1"})
    assert result.decision.value == "allowed"


@pytest.mark.parametrize(
    "tool",
    [
        "stealth_scrape",
        "stealth_attach_over_cdp",
        "stealth_load_cookies",
        "stealth_teach",
        "stealth_launch",
        "stealth_close",
        "stealth_set_region",
        "stealth_workflow_delete",
        "stealth_replay",
        "stealth_get_cdp_endpoint",
    ],
)
def test_effect_sensitive_tools_pend_in_enforce_mode(monkeypatch, tool):
    monkeypatch.delenv("STEALTH_APPROVAL_MODE", raising=False)
    srv = StealthMCPServer()
    details = {"url": "https://unclassified-example.invalid/"} if tool in {
        "stealth_scrape",
        "stealth_navigate",
    } else {}
    result = srv._approval_gate.check_sensitive(tool, details)
    assert result.decision == ApprovalDecision.PENDING
    assert is_sensitive_action(tool) is True


@pytest.mark.parametrize(
    "tool",
    [
        "stealth_status",
        "stealth_tabs_list",
        "stealth_tab_snapshot",
        "stealth_session_timeline",
        "stealth_debug_report",
        "stealth_capabilities",
        "stealth_workflow_list",
    ],
)
def test_read_only_tools_allowed_in_enforce_mode(monkeypatch, tool):
    monkeypatch.delenv("STEALTH_APPROVAL_MODE", raising=False)
    srv = StealthMCPServer()
    result = srv._approval_gate.check_sensitive(tool, {})
    assert result.decision == ApprovalDecision.ALLOWED
    assert is_sensitive_action(tool) is False


def test_every_server_tool_has_classification(monkeypatch):
    monkeypatch.delenv("STEALTH_APPROVAL_MODE", raising=False)
    srv = StealthMCPServer()
    listed = {t["name"] for t in srv.list_tools()["tools"]}
    missing = listed - set(MCP_TOOL_CLASSIFICATION)
    assert not missing, f"unclassified MCP tools: {sorted(missing)}"
    assert set(MCP_TOOL_CLASSIFICATION) == listed


def test_unclassified_tool_defaults_to_sensitive(monkeypatch):
    monkeypatch.delenv("STEALTH_APPROVAL_MODE", raising=False)
    srv = StealthMCPServer()
    assert is_sensitive_action("stealth_brand_new_tool") is True
    result = srv._approval_gate.check_sensitive("stealth_brand_new_tool", {})
    assert result.decision == ApprovalDecision.PENDING
