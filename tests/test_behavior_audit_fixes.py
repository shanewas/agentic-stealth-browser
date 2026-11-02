"""
Regression tests for the stealth/behavior audit findings 14-16, 18,
23-25, and 30.

Mirrors the MockPage / seeded-RNG style of
tests/test_human_behavior_fuzz.py. No real browser is used.
"""

import asyncio
import json
import random
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from behavior.adaptive_tuner import BehaviorTuner, FeedbackStore
from behavior.human_behavior import (
    MAX_SCROLL_PIXELS,
    ElementNotFoundError,
    HumanBehavior,
)
from behavior.persona_rotator import PersonaRotator, PersonaTrait


async def _instant_sleep(_delay=0, *args, **kwargs):
    return None


class MockPage:
    """Mock Playwright Page recording every dispatch, with a text buffer.

    Typing appends to ``buffer``; a Backspace press deletes exactly one
    trailing character, so tests can assert the net filled value.
    """

    def __init__(self, resolve=True, viewport=None):
        self._calls = []
        self.buffer = ""
        self.type_delays = []
        self._resolve = resolve
        self.viewport_size = viewport or {"width": 800, "height": 600}
        self._mouse_pos = (500, 400)
        self.mouse = self.Mouse(self)
        self.keyboard = self.Keyboard(self)

    async def evaluate(self, js, arg=None):
        self._calls.append(("evaluate", js, arg))
        return {"x": self._mouse_pos[0], "y": self._mouse_pos[1]}

    async def query_selector(self, selector):
        self._calls.append(("query_selector", selector))
        if not self._resolve:
            return None

        class MockElement:
            async def bounding_box(self):
                return {"x": 100, "y": 200, "width": 200, "height": 50}

        return MockElement()

    async def type(self, selector, text, **kwargs):
        self._calls.append(("type", selector, text, kwargs))
        if "delay" in kwargs:
            self.type_delays.append(kwargs["delay"])
        self.buffer += text

    class Mouse:
        def __init__(self, page):
            self._page = page

        async def move(self, x, y):
            self._page._calls.append(("mouse.move", x, y))
            self._page._mouse_pos = (x, y)

        async def down(self):
            self._page._calls.append(("mouse.down",))

        async def up(self):
            self._page._calls.append(("mouse.up",))

        async def click(self, x, y, **kwargs):
            self._page._calls.append(("mouse.click", x, y, kwargs))
            self._page._mouse_pos = (x, y)

        async def wheel(self, dx, dy):
            self._page._calls.append(("mouse.wheel", dx, dy))

    class Keyboard:
        def __init__(self, page):
            self._page = page

        async def press(self, key):
            self._page._calls.append(("keyboard.press", key))
            if key == "Backspace" and self._page.buffer:
                self._page.buffer = self._page.buffer[:-1]

        async def type(self, text, **kwargs):
            self._page._calls.append(("keyboard.type", text, kwargs))
            self._page.buffer += text

    def mouse_dispatches(self):
        return [c for c in self._calls if c[0].startswith("mouse.")]

    def scroll_actions(self):
        actions = []
        for call in self._calls:
            if call[0] == "evaluate" and isinstance(call[2], list) and call[2]:
                if isinstance(call[2][0], dict) and "dy" in call[2][0]:
                    actions.extend(call[2])
        return actions

    def dispatched_points(self):
        points = [(c[1], c[2]) for c in self._calls if c[0] == "mouse.move"]
        for call in self._calls:
            if call[0] == "evaluate" and isinstance(call[2], list):
                for point in call[2]:
                    if isinstance(point, dict) and "x" in point:
                        points.append((point["x"], point["y"]))
        points.extend((c[1], c[2]) for c in self._calls if c[0] == "mouse.click")
        return points


def _make_behavior(page, seed=42, **kwargs):
    return HumanBehavior(page, rng=random.Random(seed), **kwargs)


class TestTypingMistakesExactFill:
    """Finding 14: simulated mistakes must not corrupt the target text."""

    @pytest.mark.parametrize("speed", ["normal", "fast", "slow"])
    def test_net_buffer_equals_target_with_mistakes(self, monkeypatch, speed):
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
        page = MockPage()
        behavior = _make_behavior(page, seed=7)
        target = "hello world"
        asyncio.run(
            behavior.type_like_human("input", target, mistake_rate=1.0, speed=speed)
        )
        assert page.buffer == target
        backspaces = [c for c in page._calls if c == ("keyboard.press", "Backspace")]
        # Exactly one inserted wrong char per target char, deleted exactly.
        assert len(backspaces) == len(target)

    def test_type_text_alias_exact_fill(self, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
        page = MockPage()
        behavior = _make_behavior(page, seed=11)
        asyncio.run(behavior.type_text("input", "abc", mistake_rate=1.0, speed="fast"))
        assert page.buffer == "abc"


class TestHumanClickUnresolved:
    """Finding 15: unresolved selector raises, with zero mouse dispatches."""

    def test_unresolved_selector_raises_and_never_clicks(self, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
        page = MockPage(resolve=False)
        behavior = _make_behavior(page)
        with pytest.raises(ElementNotFoundError):
            asyncio.run(behavior.human_click("#missing"))
        assert page.mouse_dispatches() == []

    def test_unresolved_selector_error_is_runtime_error(self, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
        page = MockPage(resolve=False)
        behavior = _make_behavior(page)
        with pytest.raises(RuntimeError, match="not found"):
            asyncio.run(behavior.human_click("#missing"))


class TestPersonaEvolutionStability:
    """Finding 16: evolution saturates, stays in range, never oscillates."""

    @pytest.mark.parametrize("days", [0, 1, 10, 30, 90])
    def test_evolve_range_and_no_overshoot(self, days):
        trait = PersonaTrait(
            name="typing_speed",
            current_value=0.2,
            target_value=0.9,
            evolution_rate=0.1,
        )
        trait.evolve(days)
        assert 0.0 <= trait.current_value <= 1.0
        assert trait.current_value <= trait.target_value
        if days == 0:
            assert trait.current_value == 0.2

    def test_repeated_long_evolutions_do_not_oscillate(self):
        trait = PersonaTrait(
            name="typing_speed",
            current_value=0.2,
            target_value=0.9,
            evolution_rate=0.1,
        )
        distances = []
        for _ in range(6):
            trait.evolve(90)
            assert 0.0 <= trait.current_value <= 1.0
            distances.append(abs(trait.target_value - trait.current_value))
        # Distance to target never grows and the sign never flips.
        assert distances == sorted(distances, reverse=True)
        assert trait.current_value <= trait.target_value

    def test_rotator_evolution_up_to_90_days_stays_in_range(self):
        rotator = PersonaRotator("acct", rng=random.Random(42))
        rotator.set_current_persona("casual_user")
        rotator.transition_to("power_user", transition_days=14)
        for days in (0, 1, 10, 30, 90, 90):
            rotator.evolve(days)
            for value in rotator.get_trait_values().values():
                assert 0.0 <= value <= 1.0


class TestAdaptiveTunerBlockedOutcomes:
    """Finding 18: blocked/challenged feedback is a failure, not a success.

    Representation choice (see BehaviorTuner.record_feedback): outcomes
    already live in the ``blocked`` flag + ``block_type``, so challenged
    attempts are forced through that same flag into the failure stats.
    """

    def _tuner(self, tmp_path):
        return BehaviorTuner(
            feedback_store=FeedbackStore(str(tmp_path / "feedback.json"))
        )

    def test_blocked_outcome_does_not_improve_params(self, tmp_path):
        tuner = self._tuner(tmp_path)
        tuner.record_feedback(
            blocked=False,
            behavior_params={"typing_speed": 0.3},
            domain="example.com",
        )
        assert tuner.get_optimized_params()["typing_speed"] == pytest.approx(0.3)
        domain_before = tuner.get_optimized_params("example.com")["typing_speed"]

        # Attempt was challenged even though it did not error.
        tuner.record_feedback(
            blocked=False,
            block_type="captcha",
            outcome="challenged",
            behavior_params={"typing_speed": 0.95},
            domain="example.com",
        )
        assert len(tuner._successful_params) == 1
        assert len(tuner._failed_params) == 1
        assert tuner.get_optimized_params()["typing_speed"] == pytest.approx(0.3)
        assert tuner.get_optimized_params("example.com")[
            "typing_speed"
        ] == pytest.approx(domain_before)
        profile = tuner.get_domain_profile("example.com")
        assert profile.fail_count == 1
        assert profile.success_count == 1

    def test_clean_success_does_improve_params(self, tmp_path):
        tuner = self._tuner(tmp_path)
        tuner.record_feedback(blocked=False, behavior_params={"typing_speed": 0.3})
        tuner.record_feedback(
            blocked=False, outcome="success", behavior_params={"typing_speed": 0.5}
        )
        assert len(tuner._successful_params) == 2
        assert tuner.get_optimized_params()["typing_speed"] == pytest.approx(0.4)
        assert tuner.get_success_rate() == 1.0

    def test_blocked_flag_still_recorded_as_failure(self, tmp_path):
        tuner = self._tuner(tmp_path)
        tuner.record_feedback(blocked=True, block_type="captcha")
        assert len(tuner._failed_params) == 1
        assert tuner.get_success_rate() == 0.0


class TestTypingSpeedOrdering:
    """Finding 23: slow >= normal >= fast effective inter-key delay."""

    def test_average_inter_key_delay_ordering(self, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
        averages = {}
        for speed in ("slow", "normal", "fast"):
            page = MockPage()
            behavior = _make_behavior(page, seed=42)
            asyncio.run(
                behavior.type_like_human(
                    "input",
                    "abcdefghijklmnopqrst",
                    mistake_rate=1.0,
                    speed=speed,
                )
            )
            assert page.type_delays
            averages[speed] = sum(page.type_delays) / len(page.type_delays)
        assert averages["slow"] > averages["normal"] > averages["fast"]


class TestScrollNaturallyBounds:
    """Finding 24: distance=0 is a no-op; large distances are clamped."""

    def test_zero_distance_dispatches_no_wheel_or_scroll(self, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
        page = MockPage()
        behavior = _make_behavior(page)
        asyncio.run(behavior.scroll_naturally(0))
        asyncio.run(behavior.scroll_naturally(distance=0))
        assert page.scroll_actions() == []
        assert [c for c in page._calls if c[0] == "mouse.wheel"] == []
        assert page._calls == []

    def test_excessive_distance_is_clamped_to_cap(self, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
        page = MockPage()
        behavior = _make_behavior(page)
        asyncio.run(behavior.scroll_naturally(100000))
        actions = page.scroll_actions()
        assert actions
        main_total = sum(a["dy"] for a in actions if not a["is_back"])
        assert abs(main_total) == MAX_SCROLL_PIXELS


class TestMouseViewportClamping:
    """Finding 25: dispatched mouse coordinates stay inside the viewport."""

    def test_extreme_target_clamped_to_device_profile_viewport(self, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
        page = MockPage(viewport={"width": 800, "height": 600})
        profile = SimpleNamespace(viewport={"width": 300, "height": 200})
        behavior = _make_behavior(page, device_profile=profile)
        asyncio.run(behavior.move_mouse_naturally(10000, -50))
        points = page.dispatched_points()
        assert points
        for x, y in points:
            assert 0 <= x < 300
            assert 0 <= y < 200

    def test_extreme_target_clamped_to_page_viewport(self, monkeypatch):
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
        page = MockPage(viewport={"width": 640, "height": 480})
        behavior = _make_behavior(page)
        asyncio.run(behavior.move_mouse_naturally(-9999, 99999))
        for x, y in page.dispatched_points():
            assert 0 <= x < 640
            assert 0 <= y < 480
        assert 0 <= behavior.last_mouse_pos[0] < 640
        assert 0 <= behavior.last_mouse_pos[1] < 480


class TestFeedbackStoreDurability:
    """Finding 30: corrupt stores are preserved; concurrent records survive."""

    def test_corrupt_store_backed_up_and_operation_continues(self, tmp_path):
        store_path = tmp_path / "feedback.json"
        store_path.write_text("{not valid json")
        store = FeedbackStore(str(store_path))
        backup = Path(str(store_path) + ".corrupt")
        assert backup.exists()
        assert backup.read_text() == "{not valid json"
        assert store._events == []
        store.record_event("navigate", "example.com", {"ok": True})
        assert len(store._events) == 1
        reloaded = FeedbackStore(str(store_path))
        assert len(reloaded._events) == 1
        assert json.loads(store_path.read_text())["events"][0]["domain"] == (
            "example.com"
        )

    def test_concurrent_record_calls_lose_no_entries(self, tmp_path):
        store = FeedbackStore(str(tmp_path / "feedback.json"))
        thread_count, per_thread = 4, 10
        barrier = threading.Barrier(thread_count)

        def worker(worker_id):
            barrier.wait()
            for i in range(per_thread):
                store.record_event("navigate", f"site{worker_id}.example.com", {"i": i})

        threads = [
            threading.Thread(target=worker, args=(n,)) for n in range(thread_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(store._events) == thread_count * per_thread
        reloaded = FeedbackStore(str(tmp_path / "feedback.json"))
        assert len(reloaded._events) == thread_count * per_thread
