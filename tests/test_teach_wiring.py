"""Tests for #445 slice B2: stealth_teach / dashboard teach wiring.

The MCP handler and the dashboard manager are routed through
``workflows.teach_bridge.TeachSession`` (slice B1). Fakes are copied
subsets of tests/test_teach_bridge.py (page/context/CDP), the
``_FakeBrowser`` style of tests/test_mcp_stealth_workflows.py, and the
player fakes of tests/test_player.py.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from production.hermes_dashboard import (
    BrowserRuntimeManager,
    DashboardSettings,
    create_app,
)
from production.mcp_server import StealthMCPServer
from workflows.player import WorkflowPlayer
from workflows.schema import load_workflow
from workflows.teach_bridge import BINDING_NAME


@pytest.fixture(autouse=True)
def _permissive_approval(monkeypatch):
    monkeypatch.setenv("STEALTH_APPROVAL_MODE", "permissive")


# -- teach page fakes (subset of tests/test_teach_bridge.py) -----------------


class FakeCDPSession:
    def __init__(self):
        self.listeners = {}
        self.sent = []
        self.detached = False

    def on(self, event, handler):
        self.listeners.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        handlers = self.listeners.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    async def send(self, method, params=None):
        self.sent.append(method)
        return {}

    async def detach(self):
        self.detached = True

    def emit(self, event, params):
        for handler in list(self.listeners.get(event, [])):
            handler(params)


class FakeContext:
    def __init__(self):
        self.bindings = {}
        self.init_scripts = []
        self.cdp_session = FakeCDPSession()

    async def expose_binding(self, name, callback):
        self.bindings[name] = callback

    async def add_init_script(self, script):
        self.init_scripts.append(script)

    async def new_cdp_session(self, page):
        return self.cdp_session

    def report(self, payload):
        callback = self.bindings[BINDING_NAME]
        callback({"page": None, "context": self, "frame": None}, payload)


class FakePage:
    def __init__(self):
        self.context = FakeContext()
        self.url = "https://example.com/form"
        self._listeners = {}

    async def title(self):
        return "Fake Teach Page"

    def on(self, event, handler):
        self._listeners.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        handlers = self._listeners.get(event, [])
        if handler in handlers:
            handlers.remove(handler)


def _el(tag="button", el_id="go", text="Go", attrs=None, class_name="btn"):
    return {
        "tagName": tag,
        "id": el_id,
        "className": class_name,
        "textContent": text,
        "attributes": attrs or {},
    }


def _fire_teach_actions(page):
    """Drive the actions a human would perform during a teach window.

    Navigation comes first: the recorder intentionally drops an input
    group that is immediately followed by a navigation, so a password
    fill recorded right before a navigation would not survive.
    """
    page.context.cdp_session.emit(
        "Page.frameNavigated",
        {"frame": {"url": "https://example.com/done", "id": "main"}},
    )
    page.context.report({"type": "click", "element": _el()})
    pwd_el = _el(
        tag="input",
        el_id="pwd",
        text="",
        class_name="",
        attrs={"type": "password", "name": "pwd"},
    )
    page.context.report({"type": "click", "element": pwd_el})
    page.context.report({"type": "input", "element": pwd_el, "value": "hunter2-secret"})


# -- MCP fake browsers (style of tests/test_mcp_stealth_workflows.py) --------


class _TeachBrowser:
    def __init__(
        self,
        session_name=None,
        anonymous=False,
        ephemeral=False,
        light_mode=False,
        use_pooled_context=False,
    ):
        self.session_name = session_name
        self.current_preset = None
        self.current_region = "global"
        self._page = FakePage()
        self._closed = False

    async def launch(
        self, headless=True, debug=False, debug_cdp=False, preset=None, region=None
    ):
        self.current_preset = preset
        self.current_region = region or "global"

    def page_getter(self):
        return self._page

    @property
    def page(self):
        return self._page

    async def get_health_status(self):
        return {"status": "ok", "launched": True, "region": self.current_region}

    async def close(self):
        self._closed = True


class _NoPageBrowser(_TeachBrowser):
    def page_getter(self):
        return None


def _call_tool(server, name, arguments, msg_id=100):
    return server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )


def _make_server(tmp_path, monkeypatch, browser_cls):
    monkeypatch.setattr("production.mcp_server.Path.home", lambda: tmp_path)
    return StealthMCPServer(agent_browser_cls=browser_cls)


async def _wait_for_binding(page):
    for _ in range(100):
        if BINDING_NAME in page.context.bindings:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("teach binding was not installed")


async def _run_live_teach(tmp_path, monkeypatch, workflow_name):
    server = _make_server(tmp_path, monkeypatch, _TeachBrowser)
    await _call_tool(server, "stealth_launch", {"session_name": "teach-live"}, msg_id=1)
    page = server._sessions["teach-live"].page_getter()
    task = asyncio.create_task(
        server._tool_stealth_teach(
            {
                "session_name": "teach-live",
                "workflow_name": workflow_name,
                "description": "Live teach test",
                "capture_seconds": 1,
            }
        )
    )
    await _wait_for_binding(page)
    _fire_teach_actions(page)
    return await task


# -- MCP wiring ---------------------------------------------------------------


async def test_mcp_teach_live_path_records_through_teach_session(tmp_path, monkeypatch):
    payload = await _run_live_teach(tmp_path, monkeypatch, "live-teach")

    assert payload["status"] == "success"
    assert payload["recording_mode"] == "live"
    assert "TeachSession" in payload["note"]
    assert payload["step_count"] >= 2

    workflow_path = Path(payload["workflow_path"])
    assert workflow_path.exists()
    yaml_text = workflow_path.read_text()
    assert "hunter2-secret" not in yaml_text
    assert "{{password}}" in yaml_text


async def test_mcp_teach_falls_back_when_no_live_page(tmp_path, monkeypatch):
    server = _make_server(tmp_path, monkeypatch, _NoPageBrowser)
    await _call_tool(server, "stealth_launch", {"session_name": "teach-none"}, msg_id=2)

    payload = await server._tool_stealth_teach(
        {
            "session_name": "teach-none",
            "workflow_name": "fallback-teach",
            "capture_seconds": 1,
        }
    )

    assert payload["status"] == "success"
    assert payload["recording_mode"] == "fallback"
    note = payload["note"].lower()
    assert "synthetic" in note
    assert "fallback" in note
    assert Path(payload["workflow_path"]).exists()


# -- replay -------------------------------------------------------------------


class _PlayerBrowser:
    """Fake browser in the style of tests/test_player.py MockBrowser."""

    def __init__(self):
        self.page = AsyncMock()
        self.page.evaluate = AsyncMock(return_value="")
        self.page.screenshot = AsyncMock(return_value={"path": "/tmp/screen.png"})
        self.page.url = "https://example.com"
        self.page.title = "Example"
        self.goto = AsyncMock(return_value=True)
        self.safe_goto = AsyncMock(return_value=True)
        self.safe_click = AsyncMock(return_value=True)
        self.safe_type = AsyncMock(return_value=True)
        self.screenshot_on_error = AsyncMock(return_value="screenshots/error.png")


async def test_recorded_teach_yaml_replays_through_player(tmp_path, monkeypatch):
    payload = await _run_live_teach(tmp_path, monkeypatch, "replay-teach")
    assert payload["recording_mode"] == "live"

    workflow = load_workflow(payload["workflow_path"])
    player = WorkflowPlayer(_PlayerBrowser())
    result = await player.execute(workflow, runtime_vars={"password": "hunter2-secret"})

    assert result.success, result.error_message
    assert result.steps_executed == result.total_steps
    assert result.total_steps == payload["step_count"]


# -- dashboard wiring ---------------------------------------------------------


class _DashboardBrowser:
    def __init__(self, session_name=None, anonymous=False, ephemeral=False):
        self.session_name = session_name
        self.page = FakePage()
        self.closed = False

    def page_getter(self):
        return self.page

    async def get_cdp_endpoint(self):
        return {"status": "disabled"}

    async def close(self):
        self.closed = True


async def test_dashboard_teach_records_and_saves(tmp_path):
    manager = BrowserRuntimeManager(
        agent_browser_cls=_DashboardBrowser, storage_root=tmp_path
    )
    manager.browser = _DashboardBrowser()

    started = await manager.start_teach_recording("dash-teach", "Dashboard teach")
    assert started == {"recording": True, "workflow": "dash-teach"}
    session = manager.teach_session
    assert session is not None
    assert session.is_active

    status = await manager.status()
    assert status["recording"] is True
    assert status["recording_name"] == "dash-teach"

    _fire_teach_actions(manager.browser.page)
    saved = await manager.save_teach_recording()

    assert saved["workflow"] == "dash-teach"
    assert saved["steps"] >= 2
    saved_path = Path(saved["path"])
    assert saved_path.exists()
    yaml_text = saved_path.read_text()
    assert "hunter2-secret" not in yaml_text
    assert "{{password}}" in yaml_text

    assert manager.teach_session is None
    cleanup = session.cleanup_state
    assert cleanup["active"] is False
    assert cleanup["cdp_session_attached"] is False
    assert cleanup["active_listener_count"] == 0


def test_dashboard_teach_endpoints_route_through_teach_session(tmp_path):
    from fastapi.testclient import TestClient

    manager = BrowserRuntimeManager(
        agent_browser_cls=_DashboardBrowser, storage_root=tmp_path
    )
    manager.browser = _DashboardBrowser()
    app = create_app(
        manager=manager,
        settings=DashboardSettings(
            password="secret", secret_key="test-secret", cookie_secure=False
        ),
    )
    client = TestClient(app)
    login = client.post(
        "/login",
        content="password=secret",
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    csrf = next(iter(app.state.hermes_auth.sessions.values()))["csrf"]

    started = client.post(
        "/api/workflows/record/start",
        json={"name": "api-teach"},
        headers={"x-csrf-token": csrf},
    )
    assert started.status_code == 200
    assert manager.teach_session is not None

    _fire_teach_actions(manager.browser.page)
    saved = client.post(
        "/api/workflows/record/save",
        json={},
        headers={"x-csrf-token": csrf},
    )
    assert saved.status_code == 200
    assert Path(saved.json()["path"]).exists()
    assert manager.teach_session is None
