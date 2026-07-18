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
