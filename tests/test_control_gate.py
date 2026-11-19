"""#446 slice A1: ControlGate, dashboard delegation, endpoint gating.

Mode matrix under test (spike-446 section 1):
    mode    agent action    human action
    agent   allowed         CONTROL_MODE_AGENT
    human   CONTROL_MODE_HUMAN  allowed
    shared  allowed         allowed
Pause and an open intervention block agent actions only.
Read-only endpoints are never gated.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from production.control_gate import ControlGate, ControlModeError
from production.hermes_dashboard import (
    BrowserRuntimeManager,
    DashboardSettings,
    create_app,
)

try:
    from tests.test_hermes_dashboard import _FakeBrowser
except ImportError:  # pragma: no cover - direct-file test runs
    from test_hermes_dashboard import _FakeBrowser

pytestmark = pytest.mark.contract


# --- ControlGate unit ---------------------------------------------------


@pytest.mark.parametrize(
    "mode,agent_ok,human_ok",
    [
        ("agent", True, False),
        ("human", False, True),
        ("shared", True, True),
    ],
)
def test_gate_mode_matrix(mode, agent_ok, human_ok):
    gate = ControlGate(mode=mode)
    assert gate.is_agent_allowed() is agent_ok
    assert gate.is_human_allowed() is human_ok
    if agent_ok:
        gate.check_agent_allowed()
    else:
        with pytest.raises(ControlModeError):
            gate.check_agent_allowed()
    if human_ok:
        gate.check_human_allowed()
    else:
        with pytest.raises(ControlModeError):
            gate.check_human_allowed()


def test_gate_error_codes():
    gate = ControlGate(mode="human")
    with pytest.raises(ControlModeError) as agent_err:
        gate.check_agent_allowed()
    assert agent_err.value.code == "CONTROL_MODE_HUMAN"
    assert agent_err.value.to_dict()["mode"] == "human"

    gate.set_mode("agent")
    with pytest.raises(ControlModeError) as human_err:
        gate.check_human_allowed()
    assert human_err.value.code == "CONTROL_MODE_AGENT"


def test_gate_rejects_invalid_mode_and_actor():
    with pytest.raises(ValueError):
        ControlGate(mode="nobody")
    gate = ControlGate()
    with pytest.raises(ValueError):
        gate.set_mode("nobody")
    with pytest.raises(ValueError):
        gate.check_allowed("robot")


def test_gate_pause_blocks_agent_only():
    gate = ControlGate(mode="shared")
    gate.pause("manual")
    assert gate.is_agent_allowed() is False
    assert gate.is_human_allowed() is True
    with pytest.raises(ControlModeError) as err:
        gate.check_agent_allowed()
    assert err.value.code == "CONTROL_PAUSED"
    gate.resume()
    assert gate.is_agent_allowed() is True


def test_gate_intervention_blocks_agent_until_resolved():
    gate = ControlGate(mode="shared")
    gate.request_intervention("captcha", "Solve challenge", checkpoint_id="cp-1")
    assert gate.intervention["reason"] == "captcha"
    assert gate.intervention["checkpoint_id"] == "cp-1"
    with pytest.raises(ControlModeError) as err:
        gate.check_agent_allowed()
    assert err.value.code == "CONTROL_INTERVENTION"
    assert gate.is_human_allowed() is True

    previous = gate.resolve_intervention("done")
    assert previous["reason"] == "captcha"
    assert gate.intervention is None
    gate.check_agent_allowed()


def test_gate_resume_clears_pause_and_intervention():
    gate = ControlGate(mode="agent")
    gate.pause()
    gate.request_intervention("login")
    gate.resume()
    assert gate.paused is False
    assert gate.intervention is None
    gate.check_agent_allowed()


@pytest.mark.asyncio
async def test_gate_wait_until_agent_allowed_unblocks_on_resume():
    gate = ControlGate(mode="shared")
    gate.pause()
    waiter = asyncio.create_task(gate.wait_until_agent_allowed())
    await asyncio.sleep(0.05)
    assert not waiter.done()
    gate.resume()
    await asyncio.wait_for(waiter, timeout=1)


@pytest.mark.asyncio
async def test_gate_wait_until_agent_allowed_unblocks_on_mode_change():
    gate = ControlGate(mode="human")
    waiter = asyncio.create_task(gate.wait_until_agent_allowed())
    await asyncio.sleep(0.05)
    assert not waiter.done()
    gate.set_mode("shared")
    await asyncio.wait_for(waiter, timeout=1)


@pytest.mark.asyncio
async def test_gate_wait_returns_immediately_when_allowed():
    gate = ControlGate(mode="agent")
    await asyncio.wait_for(gate.wait_until_agent_allowed(), timeout=1)


# --- Dashboard delegation -------------------------------------------------


def test_manager_control_methods_delegate_to_gate(tmp_path):
    manager = BrowserRuntimeManager(
        agent_browser_cls=_FakeBrowser, storage_root=tmp_path
    )
    assert manager.control_mode == "shared"
    assert manager.control_gate.mode == "shared"

    assert manager.set_control_mode("human") == {"control_mode": "human"}
    assert manager.control_gate.mode == "human"
    assert manager.control_mode == "human"
    with pytest.raises(ValueError):
        manager.set_control_mode("nobody")

    manager.pause("test")
    assert manager.control_gate.paused is True
    assert manager.execution_state == "paused"

    manager.resume()
    assert manager.control_gate.paused is False
    assert manager.execution_state == "running"

    waiting = manager.request_intervention("captcha", "Solve challenge")
    assert manager.control_gate.intervention["reason"] == "captcha"
    assert waiting["intervention"]["reason"] == "captcha"
    assert manager.execution_state == "waiting_for_human"

    resolved = manager.resolve_intervention("Solved")
    assert resolved["resolved"] is True
    assert manager.control_gate.intervention is None
    assert manager.intervention is None


@pytest.mark.asyncio
async def test_manager_status_reflects_gate_state(tmp_path):
    manager = BrowserRuntimeManager(
        agent_browser_cls=_FakeBrowser, storage_root=tmp_path
    )
    manager.set_control_mode("human")
    manager.request_intervention("captcha")
    status = await manager.status()
    assert status["control_mode"] == "human"
    assert status["intervention"]["reason"] == "captcha"


# --- Manager-level gating matrix ------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,origin,code",
    [
        ("agent", "agent", None),
        ("agent", "human", "CONTROL_MODE_AGENT"),
        ("human", "agent", "CONTROL_MODE_HUMAN"),
        ("human", "human", None),
        ("shared", "agent", None),
        ("shared", "human", None),
    ],
)
async def test_manager_browser_actions_mode_matrix(tmp_path, mode, origin, code):
    manager = BrowserRuntimeManager(
        agent_browser_cls=_FakeBrowser, storage_root=tmp_path
    )
    await manager.start(profile="demo", backend="playwright-mcp")
    manager.set_control_mode(mode)

    actions = [
        lambda: manager.navigate("https://example.com", origin=origin),
        lambda: manager.click("#next", origin=origin),
        lambda: manager.fill("#email", "a@example.com", origin=origin),
    ]
    for action in actions:
        if code is None:
            await action()
        else:
            with pytest.raises(ControlModeError) as err:
                await action()
            assert err.value.code == code


@pytest.mark.asyncio
async def test_manager_replay_blocked_in_human_mode_and_when_paused(tmp_path):
    manager = BrowserRuntimeManager(
        agent_browser_cls=_FakeBrowser, storage_root=tmp_path
    )
    await manager.start(profile="demo", backend="playwright-mcp")

    manager.set_control_mode("human")
    with pytest.raises(ControlModeError) as err:
        await manager.replay_workflow("missing.yaml")
    assert err.value.code == "CONTROL_MODE_HUMAN"

    manager.set_control_mode("shared")
    manager.pause()
    with pytest.raises(ControlModeError) as err:
        await manager.replay_workflow("missing.yaml")
    assert err.value.code == "CONTROL_PAUSED"


# --- HTTP endpoint gating ---------------------------------------------------


def _client(tmp_path):
    manager = BrowserRuntimeManager(
        agent_browser_cls=_FakeBrowser, storage_root=tmp_path
    )
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
        "/api/browser/start", json={"csrf": csrf}, headers={"x-csrf-token": csrf}
    )
    assert started.status_code == 200
    return manager, client, csrf


def _post(client, csrf, endpoint, **payload):
    return client.post(
        endpoint, json={"csrf": csrf, **payload}, headers={"x-csrf-token": csrf}
    )


@pytest.mark.parametrize(
    "mode,origin,expected",
    [
        ("agent", "agent", 200),
        ("agent", "human", 403),
        ("human", "agent", 403),
        ("human", "human", 200),
        ("shared", "agent", 200),
        ("shared", "human", 200),
    ],
)
def test_http_browser_actions_mode_matrix(tmp_path, mode, origin, expected):
    manager, client, csrf = _client(tmp_path)
    manager.set_control_mode(mode)

    for path, payload in (
        ("/api/browser/navigate", {"url": "https://example.com"}),
        ("/api/browser/click", {"selector": "#next"}),
        ("/api/browser/fill", {"selector": "#email", "value": "a@example.com"}),
    ):
        resp = _post(client, csrf, path, origin=origin, **payload)
        assert resp.status_code == expected, (path, resp.text)
        if expected == 403:
            detail = resp.json()["detail"]
            expected_code = (
                "CONTROL_MODE_AGENT" if mode == "agent" else "CONTROL_MODE_HUMAN"
            )
            assert detail["code"] == expected_code
            assert detail["mode"] == mode
            assert detail["actor"] == origin


def test_http_replay_is_agent_gated(tmp_path):
    manager, client, csrf = _client(tmp_path)
    workflow = manager.workflow_root / "demo.yaml"
    workflow.write_text("name: demo\nsteps: []\n", encoding="utf-8")

    manager.set_control_mode("human")
    resp = _post(client, csrf, "/api/workflows/replay", path="demo.yaml")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "CONTROL_MODE_HUMAN"

    manager.set_control_mode("agent")
    resp = _post(client, csrf, "/api/workflows/replay", path="demo.yaml")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_http_read_only_endpoints_never_gated(tmp_path):
    manager, client, csrf = _client(tmp_path)
    _ = csrf
    for mode in ("agent", "human", "shared"):
        manager.set_control_mode(mode)
        manager.pause()
        assert client.get("/api/status").status_code == 200
        assert client.get("/api/workflows").status_code == 200
        assert client.get("/api/events").status_code == 200
        manager.resume()


def test_http_pause_blocks_agent_not_human_and_control_stays_open(tmp_path):
    manager, client, csrf = _client(tmp_path)

    paused = _post(client, csrf, "/api/control/pause", reason="test")
    assert paused.status_code == 200

    blocked = _post(
        client,
        csrf,
        "/api/browser/navigate",
        url="https://example.com",
        origin="agent",
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "CONTROL_PAUSED"

    allowed = _post(
        client,
        csrf,
        "/api/browser/navigate",
        url="https://example.com",
        origin="human",
    )
    assert allowed.status_code == 200

    # Control endpoints are never gated: the operator can always recover.
    resumed = _post(client, csrf, "/api/control/resume")
    assert resumed.status_code == 200
    again = _post(
        client,
        csrf,
        "/api/browser/navigate",
        url="https://example.com",
        origin="agent",
    )
    assert again.status_code == 200


def test_http_mode_can_be_changed_while_actions_are_blocked(tmp_path):
    manager, client, csrf = _client(tmp_path)
    manager.set_control_mode("agent")

    blocked = _post(
        client,
        csrf,
        "/api/browser/navigate",
        url="https://example.com",
        origin="human",
    )
    assert blocked.status_code == 403

    changed = _post(client, csrf, "/api/control/mode", mode="shared")
    assert changed.status_code == 200
    allowed = _post(
        client,
        csrf,
        "/api/browser/navigate",
        url="https://example.com",
        origin="human",
    )
    assert allowed.status_code == 200
