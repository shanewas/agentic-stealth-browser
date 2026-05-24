import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from workflows.schema import SCHEMA_VERSION, Workflow, WorkflowStep, workflow_to_yaml_str
from workflows.selector_generator import SelectorGenerator

_NOISE_EVENTS = {
    "Input.dispatchMouseEvent:mousemove",
    "Input.dispatchMouseEvent:mouseMove",
    "Page.frameStoppedLoading",
    "Runtime.consoleAPICalled",
    "Network.requestWillBeSent",
    "Network.responseReceived",
    "Network.loadingFinished",
    "Network.loadingFailed",
    "Page.lifecycleEvent",
    "Page.domContentEventFired",
    "Page.loadEventFired",
    "Runtime.executionContextCreated",
}

_NOISE_METHODS = {
    "Page.frameResized",
    "Page.frameAttached",
    "Page.frameDetached",
    "Page.frameStartedLoading",
    "Runtime.executionContextsCleared",
    "Target.attachedToTarget",
    "Target.detachedFromTarget",
    "Emulation.",
    "Fetch.",
    "Debugger.",
    "Profiler.",
    "Overlay.",
    "Page.screencastFrame",
    "Page.windowOpen",
    "Page.javascriptDialogOpening",
    "Page.javascriptDialogClosed",
    "Log.",
}

_VARIABLE_PATTERNS = [
    (re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"), "email", "{{email}}"),

    (re.compile(r"^\d{3}-?\d{3}-?\d{4}$"), "phone", "{{phone}}"),
    (re.compile(r"^https?://[^\s]+$"), "url", "{{url}}"),
    (re.compile(r"^[+\-]?\d+\.?\d*$"), "number", "{{number}}"),
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "date", "{{date_value}}"),
    (re.compile(r"^\d{2}/\d{2}/\d{4}$"), "date", "{{date_value}}"),
]

_KNOWN_PLACEHOLDER_ATTRS = {"placeholder", "aria-placeholder", "name", "title", "label"}


def _detect_variable(text: str, element_info: Optional[Dict] = None) -> Optional[str]:
    if not text:
        return None

    if element_info:
        attrs = element_info.get("attributes", {})
        if isinstance(attrs, list):
            attrs = {k.lower(): v for item in attrs for k, v in (item.items() if isinstance(item, dict) else [])}
        elif isinstance(attrs, dict):
            attrs = {k.lower(): v for k, v in attrs.items()}
        else:
            attrs = {}

        for attr_key in _KNOWN_PLACEHOLDER_ATTRS:
            if attr_key in attrs:
                val = str(attrs[attr_key]).lower()
                if "email" in val:
                    return "{{email}}"
                if "password" in val:
                    return "{{password}}"
                if "name" in val or "fullname" in val:
                    return "{{name}}"
                if "phone" in val:
                    return "{{phone}}"
                if "url" in val:
                    return "{{url}}"
                if "search" in val:
                    return "{{search_query}}"
                if "address" in val:
                    return "{{address}}"

    if not text.strip():
        return None

    for pattern, kind, placeholder in _VARIABLE_PATTERNS:
        if pattern.match(text.strip()):
            return placeholder

    return None


def _is_noise_event(method: str) -> bool:
    if method in _NOISE_EVENTS:
        return True

    base = method.split(":")[0] if ":" in method else method
    subtype = method

    for noise_method in _NOISE_METHODS:
        if noise_method.endswith("."):
            if method.startswith(noise_method):
                return True
        elif method == noise_method:
            return True
        elif ":" in noise_method:
            if subtype == noise_method:
                return True

    return False


def _event_base(method: str) -> str:
    return method.split(":")[0] if ":" in method else method


def _is_mouse_click_event(method: str, params: dict) -> bool:
    if method == "Input.dispatchMouseEvent":
        ptype = params.get("type", "")
        return ptype in ("mousePressed", "click")
    return False


def _is_keyboard_event(method: str) -> bool:
    return method in (
        "Input.dispatchKeyEvent",
        "Input.insertText",
        "Input.dispatchTextInput",
        "Input.imeSetComposition",
    )


def _is_scroll_event(method: str, params: dict) -> bool:
    if method == "Input.dispatchMouseEvent" and params.get("type") == "mouseWheel":
        return True
    return False


def _is_navigation_event(method: str) -> bool:
    return method in (
        "Page.frameNavigated",
        "Page.navigatedWithinDocument",
    )


def _is_focus_blur_event(method: str) -> bool:
    return method in (
        "Page.frameFocused",
        "Page.frameBlurred",
    )


def _is_select_event(method: str) -> bool:
    return method in (
        "Page.inputEvent",
    )


@dataclass
class RecordedEvent:
    type: str
    timestamp: float
    element_info: Optional[Dict] = None
    value: Optional[str] = None
    url: Optional[str] = None
    scroll_position: Optional[Dict] = None


@dataclass
class RecordedStep:
    step_type: str
    params: Dict[str, Any]
    raw_events: List[RecordedEvent] = field(default_factory=list)
    confidence: float = 1.0


class WorkflowRecorder:

    def __init__(self):
        self._events: List[RecordedEvent] = []
        self._current_group: List[RecordedEvent] = []
        self._current_group_type: Optional[str] = None
        self._current_element_info: Optional[Dict] = None
        self._last_input_time: float = 0.0
        self._last_scroll_time: float = 0.0
        self._last_click_target: Optional[str] = None
        self._last_click_time: float = 0.0
        self._group_timeout: float = 2.0

    def _commit_group(self):
        """Append current group events to _events and clear the group state."""
        if self._current_group:
            self._events.extend(self._current_group)
        self._current_group = []
        self._current_group_type = None
        self._current_element_info = None
        self._last_input_time = 0.0
        self._last_scroll_time = 0.0
        self._last_click_target = None
        self._last_click_time = 0.0

    def on_cdp_event(self, data: dict):
        method = data.get("method", "")
        params = data.get("params", {})

        if _is_noise_event(method):
            return

        if _is_focus_blur_event(method):
            return

        if method == "Page.frameResized":
            return

        now = time.time()

        if _is_navigation_event(method):
            url = ""
            frame = params.get("frame", {})
            if isinstance(frame, dict):
                url = frame.get("url", "")
            self._commit_group()
            evt = RecordedEvent(
                type="navigation",
                timestamp=now,
                url=url,
            )
            self._current_group = [evt]
            self._current_group_type = "navigation"
            self._commit_group()
            return

        if _is_mouse_click_event(method, params):
            element_info = {
                "tagName": params.get("tagName", "button"),
                "id": params.get("id", ""),
                "className": params.get("className", ""),
                "textContent": params.get("textContent", ""),
                "attributes": params.get("attributes", {}),
            }
            target_key = SelectorGenerator.get_best_selector(element_info)

            if self._current_group_type == "click" and target_key == self._last_click_target and now - self._last_click_time < 0.2:
                self._current_group.append(RecordedEvent(
                    type="click",
                    timestamp=now,
                    element_info=element_info,
                ))
                self._last_click_time = now
                return

            self._commit_group()
            self._current_group_type = "click"
            self._current_element_info = element_info
            self._last_click_target = target_key
            self._last_click_time = now
            evt = RecordedEvent(
                type="click",
                timestamp=now,
                element_info=element_info,
            )
            self._current_group = [evt]
            return

        if _is_keyboard_event(method):
            text = self._extract_text(params, method)

            if self._current_group_type == "input" and now - self._last_input_time < self._group_timeout:
                self._current_group.append(RecordedEvent(
                    type="input",
                    timestamp=now,
                    value=text,
                    element_info=self._current_element_info,
                ))
                self._last_input_time = now
                return

            self._commit_group()
            self._current_group_type = "input"
            self._last_input_time = now
            evt = RecordedEvent(
                type="input",
                timestamp=now,
                value=text,
                element_info=self._current_element_info,
            )
            self._current_group = [evt]
            return

        if _is_scroll_event(method, params):
            if self._current_group_type == "scroll" and now - self._last_scroll_time < 0.5:
                self._current_group.append(RecordedEvent(
                    type="scroll",
                    timestamp=now,
                    scroll_position={"deltaX": params.get("deltaX", 0), "deltaY": params.get("deltaY", 0)},
                ))
                self._last_scroll_time = now
                return

            self._commit_group()
            self._current_group_type = "scroll"
            self._last_scroll_time = now
            evt = RecordedEvent(
                type="scroll",
                timestamp=now,
                scroll_position={"deltaX": params.get("deltaX", 0), "deltaY": params.get("deltaY", 0)},
            )
            self._current_group = [evt]
            return

        self._check_timeout(now)

    def _extract_text(self, params: dict, method: str) -> Optional[str]:
        if method == "Input.insertText":
            return params.get("text", "")
        if method == "Input.dispatchTextInput":
            return params.get("text", "")
        if method == "Input.dispatchKeyEvent":
            if params.get("type") in ("keyDown", "keyPress"):
                return params.get("key", "")
        return None

    def _flush_group(self):
        self._current_group = []
        self._current_group_type = None
        self._current_element_info = None
        self._last_input_time = 0.0
        self._last_scroll_time = 0.0
        self._last_click_target = None
        self._last_click_time = 0.0

    def _check_timeout(self, now: float):
        if self._current_group_type == "input" and now - self._last_input_time >= self._group_timeout:
            self._commit_group()
        elif self._current_group_type == "scroll" and now - self._last_scroll_time >= self._group_timeout:
            self._commit_group()
        elif self._current_group_type == "click" and now - self._last_click_time >= self._group_timeout:
            self._commit_group()

    def to_steps(self) -> List[RecordedStep]:
        self._commit_group()
        steps: List[RecordedStep] = []

        i = 0
        while i < len(self._events):
            event = self._events[i]

            if event.type == "navigation":
                url = event.url or ""
                steps.append(RecordedStep(
                    step_type="navigate",
                    params={"url": url},
                    raw_events=[event],
                    confidence=1.0,
                ))
                i += 1
                continue

            if event.type == "click":
                group = [event]
                j = i + 1
                while j < len(self._events):
                    if self._events[j].type != "click":
                        break
                    if self._events[j].element_info and event.element_info:
                        sel1 = SelectorGenerator.get_best_selector(self._events[j].element_info)
                        sel0 = SelectorGenerator.get_best_selector(event.element_info)
                        if sel1 == sel0 and self._events[j].timestamp - event.timestamp < 0.2:
                            group.append(self._events[j])
                            j += 1
                        else:
                            break

                selector = ""
                fallbacks: List[str] = []
                confidence = 0.5
                if event.element_info:
                    selector, confidence = SelectorGenerator.get_best_selector_with_confidence(
                        event.element_info
                    )
                    fallbacks = SelectorGenerator.get_fallback_set(event.element_info)
                    if len(fallbacks) > 1:
                        fallbacks = fallbacks[1:]

                params: Dict[str, Any] = {"selector": selector}
                if fallbacks:
                    params["selector_fallbacks"] = fallbacks
                steps.append(RecordedStep(
                    step_type="click",
                    params=params,
                    raw_events=group,
                    confidence=confidence,
                ))
                i = j
                continue

            if event.type == "input":
                group = [event]
                j = i + 1
                while j < len(self._events):
                    if self._events[j].type != "input":
                        break
                    if self._events[j].timestamp - event.timestamp < self._group_timeout:
                        group.append(self._events[j])
                        j += 1
                    else:
                        break

                next_event = self._events[j] if j < len(self._events) else None
                if next_event and next_event.type == "navigation":
                    i = j
                    continue

                full_text = ""
                has_enter = False
                for e in group:
                    if e.value is not None:
                        if e.value == "Enter" or e.value == "\n":
                            has_enter = True
                        elif len(e.value) == 1:
                            full_text += e.value
                        else:
                            full_text += e.value

                if not full_text and not has_enter:
                    i = j
                    continue

                variable = _detect_variable(full_text, event.element_info)

                selector = ""
                confidence = 0.5
                if event.element_info:
                    selector, confidence = SelectorGenerator.get_best_selector_with_confidence(
                        event.element_info
                    )

                if has_enter:
                    steps.append(RecordedStep(
                        step_type="type",
                        params={
                            "selector": selector,
                            "value": variable if variable else full_text,
                            "submit": True,
                        },
                        raw_events=group,
                        confidence=confidence,
                    ))
                else:
                    steps.append(RecordedStep(
                        step_type="fill",
                        params={
                            "selector": selector,
                            "value": variable if variable else full_text,
                        },
                        raw_events=group,
                        confidence=confidence,
                    ))
                i = j
                continue

            if event.type == "scroll":
                group = [event]
                j = i + 1
                while j < len(self._events) and self._events[j].type == "scroll" and self._events[j].timestamp - event.timestamp < 0.5:
                    group.append(self._events[j])
                    j += 1

                total_dy = 0.0
                for e in group:
                    if e.scroll_position:
                        total_dy += e.scroll_position.get("deltaY", 0)

                direction = "down" if total_dy >= 0 else "up"
                amount = abs(int(total_dy)) or 300
                steps.append(RecordedStep(
                    step_type="scroll",
                    params={"direction": direction, "amount": amount},
                    raw_events=group,
                    confidence=0.8,
                ))
                i = j
                continue

            i += 1

        return steps

    def to_workflow(self, name: str = "recorded-workflow", description: Optional[str] = None) -> Workflow:
        recorded_steps = self.to_steps()
        workflow_steps = [
            WorkflowStep(type=rs.step_type, params=rs.params)
            for rs in recorded_steps
        ]

        avg_confidence = 0.0
        if recorded_steps:
            avg_confidence = sum(rs.confidence for rs in recorded_steps) / len(recorded_steps)
        low_confidence_steps = [
            {"index": i, "type": rs.step_type, "confidence": rs.confidence}
            for i, rs in enumerate(recorded_steps)
            if rs.confidence < 0.6
        ]

        metadata = {
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event_count": len(self._events),
            "step_count": len(workflow_steps),
            "average_confidence": round(avg_confidence, 3),
            "low_confidence_steps": low_confidence_steps,
            "changelog": [
                {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "action": "recorded",
                    "description": f"Recorded {len(workflow_steps)} steps from {len(self._events)} events",
                }
            ],
        }

        return Workflow(
            name=name,
            steps=workflow_steps,
            description=description or f"Recorded workflow with {len(workflow_steps)} steps",
            metadata=metadata,
        )

    def append_changelog(self, workflow: Workflow, action: str, description: str) -> Workflow:
        if workflow.metadata is None:
            workflow.metadata = {}
        changelog = workflow.metadata.get("changelog", [])
        if not isinstance(changelog, list):
            changelog = []
        changelog.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "action": action,
            "description": description,
        })
        workflow.metadata["changelog"] = changelog
        workflow.metadata["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return workflow

    def to_workflow_yaml(self, name: str = "recorded-workflow", description: Optional[str] = None) -> str:
        workflow = self.to_workflow(name=name, description=description)
        return workflow_to_yaml_str(workflow)
