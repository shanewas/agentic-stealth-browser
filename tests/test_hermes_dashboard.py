from pathlib import Path

import pytest

from production.hermes_dashboard import (
    BrowserRuntimeManager,
    DashboardSettings,
    create_app,
    devtools_url_from_cdp,
)

pytestmark = pytest.mark.contract


class _FakePage:
    def __init__(self):
        self.url = "about:blank"
        self.clicked = []
        self.filled = {}

    async def title(self):
        return "Fake Hermes Page"

    async def goto(self, url):
        self.url = url

    async def click(self, selector):
        self.clicked.append(selector)

    async def fill(self, selector, value):
        self.filled[selector] = value

    async def evaluate(self, js):
        return None

    async def screenshot(self, path=None, full_page=False):
        _ = full_page
        if path:
            Path(path).write_bytes(b"fake")
        return b"fake"


class _FakeBrowser:
    def __init__(self, session_name=None, anonymous=False, ephemeral=False):
        self.session_name = session_name
        self.anonymous = anonymous
        self.ephemeral = ephemeral
        self.page = _FakePage()
        self.closed = False
        self.debug_cdp = False

    async def launch(self, headless=True, debug_cdp=False, preset=None, region=None):
        _ = (headless, preset, region)
        self.debug_cdp = debug_cdp

    def page_getter(self):
        return self.page

    async def safe_goto(self, url, **kwargs):
        _ = kwargs
        self.page.url = url
        return True

    async def safe_click(self, selector, **kwargs):
        _ = kwargs
        self.page.clicked.append(selector)

    async def safe_type(self, selector, text, **kwargs):
        _ = kwargs
        self.page.filled[selector] = text

    async def get_cdp_endpoint(self):
        if not self.debug_cdp:
            return {"status": "disabled"}
        return {
            "status": "enabled",
            "ws_endpoint": "ws://127.0.0.1:9222/devtools/browser/fake",
        }

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_runtime_manager_start_status_and_backend_switch(tmp_path):
    manager = BrowserRuntimeManager(agent_browser_cls=_FakeBrowser, storage_root=tmp_path)

    status = await manager.start(profile="linkedin-work", backend="playwright-mcp")
    assert status["running"] is True
    assert status["profile"] == "linkedin-work"
    assert status["backend"] == "playwright-mcp"

    switched = await manager.switch_backend("cdp-bridge")
    assert switched["backend"] == "cdp-bridge"
    assert switched["live_view_url"].startswith("http://127.0.0.1:9222/devtools/")


@pytest.mark.asyncio
async def test_record_save_and_replay_workflow(tmp_path):
    manager = BrowserRuntimeManager(agent_browser_cls=_FakeBrowser, storage_root=tmp_path)
    await manager.start(profile="demo", backend="playwright-mcp")

    manager.start_recording("five-step-demo")
    await manager.navigate("https://example.com")
    await manager.fill("#email", "a@example.com")
    await manager.click("#next")
    manager.recorder.record("wait", ms=10)
    manager.recorder.record("screenshot")
    saved = manager.save_recording()

    assert saved["steps"] == 5
    assert Path(saved["path"]).exists()

    result = await manager.replay_workflow(saved["path"])
    assert result["success"] is True
    assert result["steps_executed"] == 5


def test_human_intervention_state_and_timeline(tmp_path):
    manager = BrowserRuntimeManager(agent_browser_cls=_FakeBrowser, storage_root=tmp_path)

    waiting = manager.request_intervention("captcha", "Solve challenge")
    assert waiting["execution_state"] == "waiting_for_human"
    assert waiting["intervention"]["reason"] == "captcha"

    resolved = manager.resolve_intervention("Solved")
    assert resolved["resolved"] is True
    events = manager.activity.export()["events"]
    assert any(e["event"] == "intervention_requested" for e in events)
    assert any(e["event"] == "intervention_resolved" for e in events)


def test_devtools_url_from_cdp_endpoint():
    url = devtools_url_from_cdp(
        {"status": "enabled", "ws_endpoint": "ws://127.0.0.1:9222/devtools/browser/fake"}
    )
    assert url == "http://127.0.0.1:9222/devtools/inspector.html?ws=127.0.0.1:9222/devtools/browser/fake"


def test_dashboard_requires_auth_and_csrf(tmp_path):
    from fastapi.testclient import TestClient

    manager = BrowserRuntimeManager(agent_browser_cls=_FakeBrowser, storage_root=tmp_path)
    app = create_app(
        manager=manager,
        settings=DashboardSettings(password="secret", secret_key="test-secret"),
    )
    client = TestClient(app)

    assert client.get("/api/status").status_code == 401

    login = client.post(
        "/login",
        content="password=secret",
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    assert client.post("/api/browser/start", json={}).status_code == 403

    csrf = next(iter(app.state.hermes_auth.sessions.values()))["csrf"]
    ok = client.post("/api/browser/start", json={}, headers={"x-csrf-token": csrf})
    assert ok.status_code == 200
    assert ok.json()["running"] is True


@pytest.mark.asyncio
async def test_schedule_runs_workflow_on_named_profile(tmp_path):
    manager = BrowserRuntimeManager(agent_browser_cls=_FakeBrowser, storage_root=tmp_path)
    await manager.start(profile="default", backend="playwright-mcp")
    manager.start_recording("scheduled-demo")
    await manager.navigate("https://example.com")
    saved = manager.save_recording()

    schedule = manager.create_schedule(saved["path"], profile="scheduled-profile", interval_seconds=1)
    schedule["next_run_at"] = 0
    results = await manager.run_due_schedules_once(now=10)

    assert len(results) == 1
    assert results[0]["result"]["success"] is True
    assert manager.active_profile == "scheduled-profile"
