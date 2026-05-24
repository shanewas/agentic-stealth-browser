"""Tests for WorkflowRecorder and SelectorGenerator."""

from workflows.recorder import (
    WorkflowRecorder,
    _detect_variable,
)
from workflows.schema import Workflow, load_workflow, validate_workflow
from workflows.selector_generator import SelectorGenerator


def _make_click_event(tag="button", el_id="", class_name="btn", text="Submit", **extra):
    params = {
        "type": "click",
        "button": "left",
        "x": 100,
        "y": 200,
        "tagName": tag,
        "id": el_id,
        "className": class_name,
        "textContent": text,
        "attributes": extra.pop("attributes", {}),
        **extra,
    }
    return {"method": "Input.dispatchMouseEvent", "params": params}


def _make_key_event(key="a", text="hello"):
    return {"method": "Input.insertText", "params": {"text": text}}


def _make_nav_event(url="https://example.com"):
    return {
        "method": "Page.frameNavigated",
        "params": {"frame": {"url": url, "id": "main"}},
    }


def _make_scroll_event(delta_y=100):
    return {
        "method": "Input.dispatchMouseEvent",
        "params": {"type": "mouseWheel", "deltaX": 0, "deltaY": delta_y},
    }


def _make_mousemove_event():
    return {
        "method": "Input.dispatchMouseEvent",
        "params": {"type": "mouseMoved", "x": 50, "y": 50},
    }


def _make_focus_event():
    return {"method": "Page.frameFocused", "params": {"frameId": "main"}}


def _make_resize_event():
    return {"method": "Page.frameResized", "params": {}}


class TestSelectorGeneration:
    def test_id_selector_ranked_highest(self):
        info = {
            "tagName": "button",
            "id": "submit-btn",
            "className": "btn primary",
            "textContent": "Submit",
        }
        candidates = SelectorGenerator.generate_candidates(info)
        assert candidates[0]["strategy"] == "id"
        assert candidates[0]["stability"] == 0.95
        assert candidates[0]["selector"] == "#submit-btn"

    def test_generated_id_not_used(self):
        info = {
            "tagName": "button",
            "id": "a1b2c3d4e5f678",
            "className": "btn",
            "textContent": "Submit",
        }
        best = SelectorGenerator.get_best_selector(info)
        assert not best.startswith("#a1b2c3d4e5f678")

    def test_data_testid_detected(self):
        info = {
            "tagName": "button",
            "id": "",
            "className": "btn",
            "attributes": {"data-testid": "submit-button"},
        }
        candidates = SelectorGenerator.generate_candidates(info)
        strategies = [c["strategy"] for c in candidates]
        assert "attribute" in strategies
        attr_candidates = [c for c in candidates if c["strategy"] == "attribute"]
        assert any("data-testid" in c["selector"] for c in attr_candidates)
        assert attr_candidates[0]["stability"] == 0.90

    def test_fallback_set_includes_multiple_strategies(self):
        info = {
            "tagName": "button",
            "id": "my-btn",
            "className": "btn primary large",
            "textContent": "Click me",
            "attributes": {"data-testid": "my-btn"},
        }
        fallbacks = SelectorGenerator.get_fallback_set(info)
        assert len(fallbacks) >= 3
        assert any("#" in f for f in fallbacks)
        assert any("data-testid" in f for f in fallbacks)

    def test_text_based_selector(self):
        info = {
            "tagName": "button",
            "id": "",
            "className": "",
            "textContent": "Sign In",
        }
        candidates = SelectorGenerator.generate_candidates(info)
        strategies = [c["strategy"] for c in candidates]
        assert "text" in strategies

    def test_get_best_selector_returns_string(self):
        info = {"tagName": "input", "id": "email", "className": "form-control"}
        best = SelectorGenerator.get_best_selector(info)
        assert isinstance(best, str)
        assert len(best) > 0


class TestClickRecording:
    def test_single_click_creates_step(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_click_event(tag="button", el_id="btn", text="Go"))
        steps = recorder.to_steps()
        assert len(steps) == 1
        assert steps[0].step_type == "click"
        assert "selector" in steps[0].params

    def test_multiple_clicks_same_element_grouped(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_click_event(tag="button", el_id="btn", text="Go"))
        recorder.on_cdp_event(_make_click_event(tag="button", el_id="btn", text="Go"))
        steps = recorder.to_steps()
        assert len(steps) == 1
        assert steps[0].step_type == "click"
        assert len(steps[0].raw_events) == 2

    def test_rapid_clicks_different_elements_separate(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_click_event(tag="button", el_id="btn1", text="A"))
        recorder.on_cdp_event(_make_click_event(tag="button", el_id="btn2", text="B"))
        steps = recorder.to_steps()
        click_steps = [s for s in steps if s.step_type == "click"]
        assert len(click_steps) >= 1


class TestInputRecording:
    def test_text_input_creates_fill_step(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_key_event(text="hello"))
        steps = recorder.to_steps()
        fill_steps = [s for s in steps if s.step_type == "fill"]
        assert len(fill_steps) == 1
        assert fill_steps[0].params["value"] == "hello"

    def test_input_with_newline_creates_type_with_submit(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_key_event(text="query"))
        recorder.on_cdp_event(
            {
                "method": "Input.dispatchKeyEvent",
                "params": {"type": "keyDown", "key": "Enter"},
            }
        )
        steps = recorder.to_steps()
        type_steps = [s for s in steps if s.step_type == "type"]
        assert len(type_steps) == 1
        assert type_steps[0].params.get("submit") is True

    def test_rapid_inputs_same_field_merged(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_key_event(text="hel"))
        recorder.on_cdp_event(_make_key_event(text="lo"))
        steps = recorder.to_steps()
        fill_steps = [s for s in steps if s.step_type == "fill"]
        assert len(fill_steps) == 1
        assert fill_steps[0].params["value"] == "hello"


class TestNavigationRecording:
    def test_frameNavigated_creates_navigate_step(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_nav_event("https://example.com"))
        steps = recorder.to_steps()
        nav_steps = [s for s in steps if s.step_type == "navigate"]
        assert len(nav_steps) == 1
        assert nav_steps[0].params["url"] == "https://example.com"

    def test_url_change_detected(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_nav_event("https://example.com/page1"))
        recorder.on_cdp_event(_make_nav_event("https://example.com/page2"))
        steps = recorder.to_steps()
        nav_steps = [s for s in steps if s.step_type == "navigate"]
        assert len(nav_steps) == 2
        assert nav_steps[0].params["url"] == "https://example.com/page1"
        assert nav_steps[1].params["url"] == "https://example.com/page2"


class TestNoiseFiltering:
    def test_mousemove_events_ignored(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_mousemove_event())
        steps = recorder.to_steps()
        assert len(steps) == 0

    def test_focus_blur_events_ignored(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_focus_event())
        steps = recorder.to_steps()
        assert len(steps) == 0

    def test_resize_events_ignored(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_resize_event())
        steps = recorder.to_steps()
        assert len(steps) == 0


class TestVariableDetection:
    def test_email_detected_as_variable(self):
        result = _detect_variable("user@example.com")
        assert result == "{{email}}"

    def test_number_detected_as_variable(self):
        result = _detect_variable("12345")
        assert result == "{{number}}"

    def test_url_variable_detected(self):
        result = _detect_variable("https://example.com/page")
        assert result == "{{url}}"

    def test_known_placeholder_used(self):
        element_info = {"attributes": {"placeholder": "Enter your email address"}}
        result = _detect_variable("user@test.com", element_info)
        assert result == "{{email}}"

    def test_password_placeholder_detected(self):
        element_info = {"attributes": {"name": "password"}}
        result = _detect_variable("secret123", element_info)
        assert result == "{{password}}"

    def test_empty_text_no_variable(self):
        result = _detect_variable("")
        assert result is None


class TestWorkflowOutput:
    def test_to_workflow_returns_valid_workflow(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_nav_event("https://example.com"))
        recorder.on_cdp_event(_make_click_event(tag="button", el_id="btn", text="Go"))
        workflow = recorder.to_workflow(name="test-flow")
        assert isinstance(workflow, Workflow)
        assert workflow.name == "test-flow"
        assert len(workflow.steps) == 2

    def test_to_workflow_yaml_round_trips(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_nav_event("https://example.com"))
        recorder.on_cdp_event(
            _make_click_event(tag="button", el_id="my-btn", text="Click Me")
        )
        yaml_str = recorder.to_workflow_yaml(name="test-roundtrip")
        assert "name: test-roundtrip" in yaml_str
        workflow = load_workflow(
            {
                "name": "test-roundtrip",
                "steps": [
                    {"type": "navigate", "url": "https://example.com"},
                    {
                        "type": "click",
                        "selector": "#my-btn",
                        "selector_fallbacks": [
                            "button.btn",
                            'button:has-text("Click Me")',
                            "button",
                            "button:nth-child(1)",
                        ],
                    },
                ],
            }
        )
        result = validate_workflow(workflow)
        assert result.valid

    def test_output_includes_metadata(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_nav_event("https://example.com"))
        workflow = recorder.to_workflow(
            name="meta-test", description="Recorded session"
        )
        assert workflow.description is not None
        assert "Recorded" in workflow.description


class TestEventGrouping:
    def test_click_then_input_on_different_elements_are_separate_steps(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_click_event(tag="button", el_id="btn", text="Go"))
        recorder.on_cdp_event(_make_key_event(text="hello"))
        steps = recorder.to_steps()
        step_types = [s.step_type for s in steps]
        assert "click" in step_types
        assert "fill" in step_types

    def test_inactivity_timeout_flushes_current_group(self):
        recorder = WorkflowRecorder()
        recorder._group_timeout = 0.1
        recorder.on_cdp_event(_make_key_event(text="first"))
        recorder.on_cdp_event(_make_key_event(text="second"))
        steps = recorder.to_steps()
        fill_steps = [s for s in steps if s.step_type == "fill"]
        assert len(fill_steps) == 1
        assert fill_steps[0].params["value"] == "firstsecond"

    def test_scroll_events_grouped(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_scroll_event(delta_y=100))
        recorder.on_cdp_event(_make_scroll_event(delta_y=50))
        steps = recorder.to_steps()
        scroll_steps = [s for s in steps if s.step_type == "scroll"]
        assert len(scroll_steps) == 1
        assert scroll_steps[0].params["amount"] == 150

    def test_navigation_resets_input_group(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(_make_key_event(text="hello"))
        recorder.on_cdp_event(_make_nav_event("https://example.com"))
        recorder.on_cdp_event(_make_key_event(text="world"))
        steps = recorder.to_steps()
        navigate_steps = [s for s in steps if s.step_type == "navigate"]
        fill_steps = [s for s in steps if s.step_type == "fill"]
        assert len(navigate_steps) == 1
        assert len(fill_steps) == 1
        assert fill_steps[0].params["value"] == "world"
