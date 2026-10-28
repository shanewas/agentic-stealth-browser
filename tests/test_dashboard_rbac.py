import pytest
from fastapi.testclient import TestClient

from production.hermes_dashboard import (
    BrowserRuntimeManager,
    DashboardSettings,
    create_app,
    run_dashboard,
)

try:
    from tests.test_hermes_dashboard import _FakeBrowser
except ImportError:

    class _FakeBrowser:
        def __init__(self, session_name=None, anonymous=False, ephemeral=False):
            self.session_name = session_name
            self.anonymous = anonymous
            self.ephemeral = ephemeral
            self.closed = False

        async def launch(
            self, headless=True, debug_cdp=False, preset=None, region=None
        ):
            _ = (headless, debug_cdp, preset, region)

        async def close(self):
            self.closed = True

        async def safe_goto(self, url, **kwargs):
            _ = (url, kwargs)
            return True


pytestmark = pytest.mark.contract


def _login(client, username, password):
    return client.post(
        "/login",
        content=f"username={username}&password={password}",
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )


def test_viewer_cannot_mutate(tmp_path):
    settings = DashboardSettings(
        users={
            "vic": {"password": "pw", "role": "viewer"},
            "op": {"password": "pw", "role": "operator"},
        },
        secret_key="test-secret",
        cookie_secure=False,
    )
    app = create_app(
        manager=BrowserRuntimeManager(
            agent_browser_cls=_FakeBrowser, storage_root=tmp_path
        ),
        settings=settings,
    )
    client = TestClient(app)

    login = _login(client, "vic", "pw")
    assert login.status_code == 303

    assert client.get("/api/status").status_code == 200

    csrf = next(iter(app.state.hermes_auth.sessions.values()))["csrf"]
    resp = client.post(
        "/api/browser/navigate", json={"csrf": csrf, "url": "about:blank"}
    )
    assert resp.status_code == 403


def test_operator_can_mutate(tmp_path):
    settings = DashboardSettings(
        users={
            "vic": {"password": "pw", "role": "viewer"},
            "op": {"password": "pw", "role": "operator"},
        },
        secret_key="test-secret",
        cookie_secure=False,
    )
    app = create_app(
        manager=BrowserRuntimeManager(
            agent_browser_cls=_FakeBrowser, storage_root=tmp_path
        ),
        settings=settings,
    )
    client = TestClient(app)

    login = _login(client, "op", "pw")
    assert login.status_code == 303

    csrf = next(iter(app.state.hermes_auth.sessions.values()))["csrf"]
    resp = client.post("/api/browser/start", json={"csrf": csrf})
    assert resp.status_code == 200


def test_boot_refuses_change_me():
    with pytest.raises(RuntimeError):
        run_dashboard(host="127.0.0.1", password="change-me")


def _app_with_users(tmp_path):
    settings = DashboardSettings(
        users={
            "vic": {"password": "pw", "role": "viewer"},
            "op": {"password": "pw", "role": "operator"},
        },
        secret_key="test-secret",
        cookie_secure=False,
    )
    app = create_app(
        manager=BrowserRuntimeManager(
            agent_browser_cls=_FakeBrowser, storage_root=tmp_path
        ),
        settings=settings,
    )
    return app, TestClient(app)


def _csrf(app):
    return next(iter(app.state.hermes_auth.sessions.values()))["csrf"]


def _seed_workflow_and_schedule(app):
    manager = app.state.hermes_manager
    workflow = manager.workflow_root / "demo.yaml"
    workflow.write_text("name: demo\nsteps: []\n", encoding="utf-8")
    schedule = manager.create_schedule(
        str(workflow), profile="default", interval_seconds=60
    )
    return workflow, schedule


def test_viewer_cannot_delete_workflow_or_schedule(tmp_path):
    app, client = _app_with_users(tmp_path)
    workflow, schedule = _seed_workflow_and_schedule(app)
    assert _login(client, "vic", "pw").status_code == 303
    csrf = _csrf(app)

    assert client.delete(
        "/api/workflows/demo.yaml", headers={"x-csrf-token": csrf}
    ).status_code == 403
    assert workflow.exists()
    assert client.delete(
        f"/api/schedules/{schedule['id']}", headers={"x-csrf-token": csrf}
    ).status_code == 403
    assert app.state.hermes_manager.list_schedules()


def test_viewer_cannot_record_start_or_save(tmp_path):
    app, client = _app_with_users(tmp_path)
    assert _login(client, "vic", "pw").status_code == 303
    csrf = _csrf(app)

    assert client.post(
        "/api/workflows/record/start", json={"csrf": csrf, "name": "x"}
    ).status_code == 403
    assert client.post(
        "/api/workflows/record/save", json={"csrf": csrf}
    ).status_code == 403
    assert app.state.hermes_manager.recorder.active is False


def test_delete_routes_require_csrf_for_operator(tmp_path):
    app, client = _app_with_users(tmp_path)
    workflow, schedule = _seed_workflow_and_schedule(app)
    assert _login(client, "op", "pw").status_code == 303

    assert client.delete("/api/workflows/demo.yaml").status_code == 403
    assert client.delete(
        "/api/workflows/demo.yaml", headers={"x-csrf-token": "bogus"}
    ).status_code == 403
    assert workflow.exists()
    assert client.delete(f"/api/schedules/{schedule['id']}").status_code == 403
    assert app.state.hermes_manager.list_schedules()


def test_operator_with_csrf_can_delete_and_record(tmp_path):
    app, client = _app_with_users(tmp_path)
    workflow, schedule = _seed_workflow_and_schedule(app)
    assert _login(client, "op", "pw").status_code == 303
    csrf = _csrf(app)

    started = client.post(
        "/api/workflows/record/start", json={"csrf": csrf, "name": "rec-demo"}
    )
    assert started.status_code == 200
    app.state.hermes_manager.recorder.record("wait", ms=10)
    saved = client.post("/api/workflows/record/save", json={"csrf": csrf})
    assert saved.status_code == 200

    assert client.delete(
        "/api/workflows/demo.yaml", headers={"x-csrf-token": csrf}
    ).status_code == 200
    assert not workflow.exists()
    assert client.delete(
        f"/api/schedules/{schedule['id']}", headers={"x-csrf-token": csrf}
    ).status_code == 200
    assert app.state.hermes_manager.list_schedules() == []


def test_create_app_rejects_default_and_empty_credentials(tmp_path):
    def _manager():
        return BrowserRuntimeManager(
            agent_browser_cls=_FakeBrowser, storage_root=tmp_path
        )

    with pytest.raises(RuntimeError):
        create_app(manager=_manager(), settings=DashboardSettings(secret_key="s"))
    with pytest.raises(RuntimeError):
        create_app(
            manager=_manager(),
            settings=DashboardSettings(password="", secret_key="s"),
        )
    with pytest.raises(RuntimeError):
        create_app(
            manager=_manager(),
            settings=DashboardSettings(
                users={"u": {"password": "", "role": "operator"}}, secret_key="s"
            ),
        )
    with pytest.raises(RuntimeError):
        create_app(
            manager=_manager(),
            settings=DashboardSettings(
                users={"u": {"role": "operator"}}, secret_key="s"
            ),
        )


def test_metrics_requires_session(tmp_path):
    app, client = _app_with_users(tmp_path)
    assert client.get("/metrics").status_code == 401
    assert _login(client, "vic", "pw").status_code == 303
    assert client.get("/metrics").status_code == 200
