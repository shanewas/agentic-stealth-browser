"""SEC-09: MCP approval gate is fail-closed by default; STEALTH_APPROVAL_MODE=permissive opts out."""

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
