import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.mcp

from production.mcp_server import StealthMCPServer


class _FakePage:
    def __init__(self):
        self.url = "about:blank"
        self._title = "Fake Page"

    async def title(self):
        return self._title

    async def screenshot(self, path: str, full_page: bool = False):
        _ = full_page
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"fake-png-bytes")
        return b"fake-png-bytes"

    async def evaluate(self, js: str):
        return None

    async def goto(self, url: str):
        self.url = url
        return None


class _FakeBrowser:
    def __init__(
        self,
        session_name=None,
        anonymous=False,
        ephemeral=False,
        light_mode=False,
        use_pooled_context=False,
    ):
        self.session_name = session_name
        self.anonymous = anonymous
        self.ephemeral = ephemeral
        self.light_mode = light_mode
        self.use_pooled_context = use_pooled_context
        self.current_preset = None
        self.current_region = "global"
        self._page = _FakePage()
        self._pages = [self._page]
        self._closed = False

    async def launch(self, headless=True, debug=False, debug_cdp=False, preset=None, region=None):
        self.current_preset = preset
        self.current_region = region or "global"
        self.debug = debug
        self.debug_cdp = debug_cdp
        self.headless = headless

    def page_getter(self):
        return self._page

    async def safe_goto(self, url: str, warm_up=True, platform="unknown", rate_limit=True, domain=None, account=None):
        _ = (warm_up, platform, rate_limit, domain, account)
        self._page.url = url
        self._page._title = f"Visited {url}"
        return True

    async def get_health_status(self):
        return {"status": "ok", "launched": True, "region": self.current_region}

    async def debug_report(self, print_report: bool = False, limit: int = None, cursor: str = None, since_ts: str = None):
        _ = (print_report, limit, cursor, since_ts)
        return {"status": "success", "report": {"ok": True}}

    async def get_cdp_endpoint(self):
        return {
            "status": "disabled",
            "message": "CDP attach is disabled for this session.",
        }

    def get_replay_sequence(self, limit: int = 30, cursor: str = None, since_ts: str = None):
        _ = (cursor, since_ts)
        return {"status": "ok", "sequence": [{"event": "navigate", "ts": 1}]}

    def get_pages(self):
        return list(self._pages)

    @property
    def page(self):
        return self._page

    async def close(self):
        self._closed = True


def _tool_structured_content(resp: dict) -> dict:
    return resp["result"]["structuredContent"]


def _call_tool(server, name, arguments, msg_id=100):
    return server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )


@pytest.mark.asyncio
async def test_new_workflow_tools_appear_in_tools_list():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    names = {t["name"] for t in server.list_tools()["tools"]}
    assert "stealth_teach" in names
    assert "stealth_replay" in names
    assert "stealth_workflow_list" in names
    assert "stealth_workflow_delete" in names


@pytest.mark.asyncio
async def test_replay_fails_with_path_traversal():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "stealth_replay",
                "arguments": {"filename": "../secret.yaml"},
            },
        }
    )
    payload = _tool_structured_content(resp)
    assert payload["status"] == "error"
    assert payload["error_code"] == "MCP_SECURITY_PATH_DENIED"
    assert resp["result"].get("isError") is True


@pytest.mark.asyncio
async def test_replay_fails_with_path_traversal_encoded():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "stealth_replay",
                "arguments": {"filename": "foo/../../etc/passwd.yaml"},
            },
        }
    )
    payload = _tool_structured_content(resp)
    assert payload["status"] == "error"
    assert payload["error_code"] == "MCP_SECURITY_PATH_DENIED"
    assert resp["result"].get("isError") is True


@pytest.mark.asyncio
async def test_delete_fails_without_confirm_true():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "stealth_workflow_delete",
                "arguments": {"filename": "test.yaml"},
            },
        }
    )
    payload = _tool_structured_content(resp)
    assert payload["status"] == "error"
    assert payload["error_code"] == "MCP_VALIDATION_ERROR"
    assert "Confirmation required" in payload["message"]
    assert resp["result"].get("isError") is True


@pytest.mark.asyncio
async def test_delete_fails_with_confirm_false():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "stealth_workflow_delete",
                "arguments": {"filename": "test.yaml", "confirm": False},
            },
        }
    )
    payload = _tool_structured_content(resp)
    assert payload["status"] == "error"
    assert payload["error_code"] == "MCP_VALIDATION_ERROR"
    assert "Confirmation required" in payload["message"]
    assert resp["result"].get("isError") is True


@pytest.mark.asyncio
async def test_delete_fails_with_path_traversal():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "stealth_workflow_delete",
                "arguments": {"filename": "../evil.yaml", "confirm": True},
            },
        }
    )
    payload = _tool_structured_content(resp)
    assert payload["status"] == "error"
    assert payload["error_code"] == "MCP_SECURITY_PATH_DENIED"
    assert resp["result"].get("isError") is True


@pytest.mark.asyncio
async def test_workflow_list_returns_expected_structure():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "stealth_workflow_list",
                "arguments": {},
            },
        }
    )
    payload = _tool_structured_content(resp)
    assert payload["status"] == "success"
    assert "workflows" in payload
    assert isinstance(payload["workflows"], list)


@pytest.mark.asyncio
async def test_teach_produces_saved_workflow_file(tmp_path, monkeypatch):
    monkeypatch.setattr("production.mcp_server.Path.home", lambda: tmp_path)
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)

    await _call_tool(server, "stealth_launch", {"session_name": "teach-test"}, msg_id=10)
    await _call_tool(
        server,
        "stealth_navigate",
        {"session_name": "teach-test", "url": "https://example.com"},
        msg_id=11,
    )

    resp = await _call_tool(
        server,
        "stealth_teach",
        {
            "session_name": "teach-test",
            "workflow_name": "test-teach",
            "description": "A test workflow",
            "capture_seconds": 10,
        },
        msg_id=12,
    )
    payload = _tool_structured_content(resp)
    assert payload["status"] == "success"
    assert payload["workflow_name"] == "test-teach"
    assert "workflow_path" in payload
    assert payload["step_count"] >= 1

    workflow_path = Path(payload["workflow_path"])
    assert workflow_path.exists()
    content = workflow_path.read_text()
    assert "test-teach" in content or "test-teach" in content.lower()


@pytest.mark.asyncio
async def test_replay_loads_and_executes_a_simple_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr("production.mcp_server.Path.home", lambda: tmp_path)
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)

    await _call_tool(server, "stealth_launch", {"session_name": "replay-test"}, msg_id=20)

    workflow_yaml = """name: simple-test
description: A simple workflow for replay testing
steps:
  - type: navigate
    url: https://example.com
  - type: wait
    ms: 500
"""
    workflow_file = server._workflow_library_root / "simple-test.yaml"
    workflow_file.write_text(workflow_yaml)

    resp = await _call_tool(
        server,
        "stealth_replay",
        {
            "filename": "simple-test.yaml",
            "session_name": "replay-test",
            "variables": {"test_var": "value1"},
        },
        msg_id=21,
    )
    payload = _tool_structured_content(resp)
    assert payload["status"] == "success"
    assert payload["success"] is True
    assert payload["steps_executed"] >= 2
    assert payload["total_steps"] >= 2
    assert payload["failed_step"] is None
    assert payload["error_message"] is None
    assert "execution_time" in payload


@pytest.mark.asyncio
async def test_replay_fails_for_nonexistent_workflow():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    await _call_tool(server, "stealth_launch", {"session_name": "replay-test"}, msg_id=30)
    resp = await _call_tool(
        server,
        "stealth_replay",
        {"filename": "nonexistent-workflow.yaml", "session_name": "replay-test"},
        msg_id=31,
    )
    payload = _tool_structured_content(resp)
    assert payload["status"] == "error"
    assert payload["error_code"] == "MCP_WORKFLOW_NOT_FOUND"
    assert resp["result"].get("isError") is True


@pytest.mark.asyncio
async def test_replay_uses_active_session_when_session_name_omitted():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    await _call_tool(server, "stealth_launch", {"session_name": "only-session"}, msg_id=40)

    workflow_yaml = """name: auto-session-test
steps:
  - type: wait
    ms: 100
"""
    workflow_file = server._workflow_library_root / "auto-session-test.yaml"
    workflow_file.write_text(workflow_yaml)

    resp = await _call_tool(
        server,
        "stealth_replay",
        {"filename": "auto-session-test.yaml"},
        msg_id=41,
    )
    payload = _tool_structured_content(resp)
    assert payload["status"] == "success"
    assert payload["session_name"] == "only-session"
    assert payload["success"] is True


@pytest.mark.asyncio
async def test_workflow_list_filters_by_platform(tmp_path, monkeypatch):
    monkeypatch.setattr("production.mcp_server.Path.home", lambda: tmp_path)
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)

    common_dir = server._workflow_library_root / "common"
    common_dir.mkdir(parents=True, exist_ok=True)
    upwork_dir = server._workflow_library_root / "upwork"
    upwork_dir.mkdir(parents=True, exist_ok=True)

    (common_dir / "login.yaml").write_text("name: login\nsteps: []\n")
    (upwork_dir / "apply.yaml").write_text("name: apply\nsteps: []\n")
    (common_dir / "verify-email.yaml").write_text("name: verify-email\nsteps: []\n")

    resp = await _call_tool(
        server,
        "stealth_workflow_list",
        {"platform": "common"},
        msg_id=50,
    )
    payload = _tool_structured_content(resp)
    assert payload["status"] == "success"
    workflows = payload["workflows"]
    assert len(workflows) == 2
    paths = {w["path"] for w in workflows}
    assert "common/login.yaml" in paths
    assert "common/verify-email.yaml" in paths

    resp2 = await _call_tool(
        server,
        "stealth_workflow_list",
        {"platform": "common", "pattern": "*verify*"},
        msg_id=51,
    )
    payload2 = _tool_structured_content(resp2)
    assert payload2["status"] == "success"
    assert len(payload2["workflows"]) == 1
    assert payload2["workflows"][0]["name"] == "verify-email"


@pytest.mark.asyncio
async def test_workflow_list_returns_empty_for_nonexistent_platform():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    resp = await _call_tool(
        server,
        "stealth_workflow_list",
        {"platform": "nonexistent-platform"},
        msg_id=60,
    )
    payload = _tool_structured_content(resp)
    assert payload["status"] == "success"
    assert payload["workflows"] == []


@pytest.mark.asyncio
async def test_delete_workflow_success(tmp_path, monkeypatch):
    monkeypatch.setattr("production.mcp_server.Path.home", lambda: tmp_path)
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)

    workflow_path = server._workflow_library_root / "to-delete.yaml"
    workflow_path.write_text("name: to-delete\nsteps: []\n")
    assert workflow_path.exists()

    resp = await _call_tool(
        server,
        "stealth_workflow_delete",
        {"filename": "to-delete.yaml", "confirm": True},
        msg_id=70,
    )
    payload = _tool_structured_content(resp)
    assert payload["status"] == "success"
    assert payload["deleted"] is True
    assert payload["filename"] == "to-delete.yaml"
    assert not workflow_path.exists()


@pytest.mark.asyncio
async def test_delete_fails_for_nonexistent_workflow():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    resp = await _call_tool(
        server,
        "stealth_workflow_delete",
        {"filename": "does-not-exist.yaml", "confirm": True},
        msg_id=80,
    )
    payload = _tool_structured_content(resp)
    assert payload["status"] == "error"
    assert payload["error_code"] == "MCP_WORKFLOW_NOT_FOUND"
    assert resp["result"].get("isError") is True


@pytest.mark.asyncio
async def test_workflow_list_includes_metadata_fields(tmp_path, monkeypatch):
    monkeypatch.setattr("production.mcp_server.Path.home", lambda: tmp_path)
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)

    workflow_path = server._workflow_library_root / "meta-test.yaml"
    workflow_path.write_text("name: meta-test\nsteps: []\n")

    resp = await _call_tool(
        server,
        "stealth_workflow_list",
        {},
        msg_id=90,
    )
    payload = _tool_structured_content(resp)
    assert payload["status"] == "success"
    workflows = payload["workflows"]
    assert len(workflows) >= 1

    meta_workflow = next(w for w in workflows if w["name"] == "meta-test")
    for key in ("name", "path", "platform", "size", "modified_at"):
        assert key in meta_workflow, f"Expected key '{key}' in workflow metadata"
    assert isinstance(meta_workflow["size"], int)
    assert meta_workflow["size"] > 0
