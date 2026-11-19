"""Tests for workflows.teach_bridge.TeachSession (#445, slice B1).

Deterministic fakes stand in for the Playwright page/context/CDP session,
following the fake-object style of the existing recorder/MCP tests. The
binding callback captured from the fake context is invoked with the same
report dicts the injected JS listeners would send.
"""

import asyncio

import pytest

from workflows.recorder import WorkflowRecorder
from workflows.teach_bridge import (
    BINDING_NAME,
    TeachSession,
    shape_binding_report,
    shape_cdp_event,
)


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
        """Simulate the injected JS listener calling the exposed binding."""
        callback = self.bindings[BINDING_NAME]
        callback({"page": None, "context": self, "frame": None}, payload)


class FakePage:
    def __init__(self):
        self.context = FakeContext()
        self.url = "https://example.com/form"
        self._listeners = {}

    def on(self, event, handler):
        self._listeners.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        handlers = self._listeners.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    def emit_close(self):
        for handler in list(self._listeners.get("close", [])):
            handler()


def _el(tag="button", el_id="go", text="Go", attrs=None, class_name="btn"):
    return {
        "tagName": tag,
        "id": el_id,
        "className": class_name,
        "textContent": text,
        "attributes": attrs or {},
    }


async def _started_session(capture_seconds=60):
    page = FakePage()
    session = TeachSession()
    await session.start(page, capture_seconds=capture_seconds)
    return page, session


class TestShaping:
    def test_click_report_shapes_to_mouse_event(self):
        shaped = shape_binding_report({"type": "click", "element": _el()})
        assert shaped["method"] == "Input.dispatchMouseEvent"
        assert shaped["params"]["type"] == "click"
        assert shaped["params"]["id"] == "go"

    def test_input_report_shapes_to_insert_text(self):
        shaped = shape_binding_report(
            {"type": "input", "element": _el(tag="input"), "value": "hello"}
        )
        assert shaped == {
            "method": "Input.insertText",
            "params": {**shaped["params"], "text": "hello"},
        }
        assert shaped["params"]["text"] == "hello"

    def test_keydown_only_enter_and_tab(self):
        assert shape_binding_report({"type": "keydown", "key": "a", "element": _el()}) is None
        enter = shape_binding_report({"type": "keydown", "key": "Enter", "element": _el()})
        assert enter["method"] == "Input.dispatchKeyEvent"
        assert enter["params"]["key"] == "Enter"

    def test_scroll_report_shapes_to_mouse_wheel(self):
        shaped = shape_binding_report({"type": "scroll", "deltaX": 0, "deltaY": 240})
        assert shaped["params"]["type"] == "mouseWheel"
        assert shaped["params"]["deltaY"] == 240

    def test_cdp_event_only_navigation_passes(self):
        nav = shape_cdp_event("Page.frameNavigated", {"frame": {"url": "https://x.test/"}})
        assert nav["method"] == "Page.frameNavigated"
        assert shape_cdp_event("Page.loadEventFired", {}) is None


class TestCaptureFlow:
    async def test_start_installs_binding_script_and_cdp(self):
        page, session = await _started_session()
        try:
            assert session.is_active
            assert BINDING_NAME in page.context.bindings
            assert len(page.context.init_scripts) == 1
            script = page.context.init_scripts[0]
            for needle in ("click", "keydown", "scroll", "submit", "addEventListener"):
                assert needle in script
            assert "Page.enable" in page.context.cdp_session.sent
            # CDP navigation listener + page-close hook.
            assert session.active_listener_count == 2
            assert session.cleanup_state["cdp_listener_count"] == 1
        finally:
            await session.stop()

    async def test_local_page_actions_become_workflow_steps(self):
        page, session = await _started_session()
        ctx = page.context
        ctx.report({"type": "click", "element": _el()})
        ctx.report(
            {
                "type": "input",
                "element": _el(tag="input", el_id="q", text="", attrs={"type": "text", "name": "q"}),
                "value": "hello",
            }
        )
        ctx.report({"type": "keydown", "key": "Enter", "element": _el(tag="input", el_id="q")})
        ctx.report({"type": "scroll", "deltaX": 0, "deltaY": 300})
        page.context.cdp_session.emit(
            "Page.frameNavigated", {"frame": {"url": "https://example.com/done", "id": "main"}}
        )
        await session.stop()

        steps = session.recorder.to_steps()
        types = [s.step_type for s in steps]
        assert "click" in types
        assert "navigate" in types
        nav = [s for s in steps if s.step_type == "navigate"][0]
        assert nav.params["url"] == "https://example.com/done"
        yaml_text = session.recorder.to_workflow_yaml(name="teach-test")
        assert "teach-test" in yaml_text

    async def test_navigation_via_handle_cdp_event(self):
        _page, session = await _started_session()
        session.handle_cdp_event(
            "Page.frameNavigated", {"frame": {"url": "https://example.com/next"}}
        )
        await session.stop()
        steps = session.recorder.to_steps()
        assert [s.step_type for s in steps] == ["navigate"]


class TestRedaction:
    async def test_password_value_lands_as_variable_not_literal(self):
        page, session = await _started_session()
        ctx = page.context
        pwd_el = _el(
            tag="input",
            el_id="pwd",
            text="",
            class_name="",
            attrs={"type": "password", "name": "pwd"},
        )
        ctx.report({"type": "click", "element": pwd_el})
        ctx.report({"type": "input", "element": pwd_el, "value": "hunter2-secret"})
        await session.stop()

        yaml_text = session.recorder.to_workflow_yaml(name="redaction-test")
        assert "{{password}}" in yaml_text
        assert "hunter2-secret" not in yaml_text
        steps = session.recorder.to_steps()
        fill = [s for s in steps if s.step_type == "fill"]
        assert len(fill) == 1
        assert fill[0].params["value"] == "{{password}}"


class TestCleanup:
    async def test_stop_removes_listeners_detaches_and_is_idempotent(self):
        page, session = await _started_session()
        cdp = page.context.cdp_session
        await session.stop("completed")
        state = session.cleanup_state
        assert state["active"] is False
        assert state["stop_reason"] == "completed"
        assert state["cdp_session_attached"] is False
        assert state["cdp_listener_count"] == 0
        assert state["active_listener_count"] == 0
        assert state["timer_pending"] is False
        assert cdp.detached is True
        assert cdp.listeners.get("Page.frameNavigated", []) == []

        await session.stop("completed")
        assert session.cleanup_state["stop_count"] == 1

    async def test_events_after_stop_are_ignored(self):
        page, session = await _started_session()
        await session.stop()
        before = session.events_forwarded
        page.context.report({"type": "click", "element": _el()})
        session.handle_cdp_event("Page.frameNavigated", {"frame": {"url": "https://x.test/"}})
        assert session.events_forwarded == before
        assert session.recorder.to_steps() == []

    async def test_timeout_stops_session(self):
        _page, session = await _started_session(capture_seconds=0.05)
        await session.wait()
        assert session.is_active is False
        assert session.stop_reason == "timeout"
        assert session.active_listener_count == 0

    async def test_page_close_stops_session(self):
        page, session = await _started_session()
        page.emit_close()
        await asyncio.sleep(0.05)
        assert session.is_active is False
        assert session.stop_reason == "session-close"
        assert session.cleanup_state["cdp_session_attached"] is False

    async def test_double_start_rejected(self):
        _page, session = await _started_session()
        try:
            with pytest.raises(RuntimeError):
                await session.start(FakePage(), capture_seconds=60)
        finally:
            await session.stop()

    async def test_session_without_cdp_support_still_captures(self):
        class BarePage:
            url = "https://example.com/"
            context = None

            async def expose_binding(self, name, callback):
                self.binding = callback

            async def add_init_script(self, script):
                self.script = script

        page = BarePage()
        session = TeachSession()
        await session.start(page, capture_seconds=60)
        assert session.is_active
        assert session.active_listener_count == 0
        page.binding({}, {"type": "click", "element": _el()})
        await session.stop()
        assert [s.step_type for s in session.recorder.to_steps()] == ["click"]


class TestRecorderPassthrough:
    def test_bridge_uses_supplied_recorder(self):
        recorder = WorkflowRecorder()
        session = TeachSession(recorder=recorder)
        assert session.recorder is recorder
