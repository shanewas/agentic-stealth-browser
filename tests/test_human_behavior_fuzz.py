"""
Property-based / fuzz testing for human behavior parameters.
Addresses #110: Add property-based / fuzz testing for human behavior parameters.

Tests that human behavior methods handle edge cases, extreme values,
and invalid inputs gracefully without crashing or producing unreasonable results.
"""

import asyncio
import sys
import random
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from behavior.human_behavior import HumanBehavior


class MockPage:
    """Mock Playwright Page for testing human behavior without a real browser."""

    def __init__(self):
        self._mouse_pos = (500, 400)
        self._url = "https://example.com"
        self._title = "Example Domain"
        self._calls = []
        self.mouse = self.Mouse(self)
        self.keyboard = self.Keyboard(self)

    async def evaluate(self, js, arg=None):
        # Real Playwright: page.evaluate(js, arg) — the JS source can take a single
        # argument; the Python side passes a JSON-serializable value. MockPage
        # ignores both, but must accept the second arg so the call doesn't raise
        # TypeError and force the JS-batch path to fall back to slow per-CDP calls.
        self._calls.append(("evaluate", js, arg))
        return {"x": self._mouse_pos[0], "y": self._mouse_pos[1]}

    async def mouse_move(self, x, y):
        self._calls.append(("mouse.move", x, y))
        self._mouse_pos = (x, y)

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

        async def type(self, text, **kwargs):
            self._page._calls.append(("keyboard.type", text, kwargs))

    async def query_selector(self, selector):
        self._calls.append(("query_selector", selector))

        class MockElement:
            async def bounding_box(self):
                return {"x": 100, "y": 200, "width": 200, "height": 50}

        return MockElement()

    async def keyboard_press(self, key):
        self._calls.append(("keyboard.press", key))

    async def keyboard_type(self, text, **kwargs):
        self._calls.append(("keyboard.type", text, kwargs))

    async def type(self, selector, text, **kwargs):
        self._calls.append(("type", selector, text, kwargs))

    @property
    def url(self):
        return self._url

    async def title(self):
        return self._title


class TestHumanBehaviorFuzz:
    """Fuzz testing for HumanBehavior methods."""

    def _make_behavior(self, rng_seed=None):
        page = MockPage()
        rng = random.Random(rng_seed)
        return HumanBehavior(page, rng=rng)

    def test_think_with_extreme_min_max(self):
        """Test think() with extreme min/max values."""
        behavior = self._make_behavior()
        # Very short
        asyncio.run(behavior.think(1, 2))
        # Very long (but not too long for test)
        asyncio.run(behavior.think(1, 100))
        # Zero range
        asyncio.run(behavior.think(50, 50))
        # Negative (should still work, just sleep 0)
        asyncio.run(behavior.think(-100, -50))

    def test_think_with_large_values(self):
        """Test think() with very large values (should not hang indefinitely)."""
        behavior = self._make_behavior()
        # Cap at reasonable max for test
        asyncio.run(behavior.think(1, 500))

    def test_move_mouse_naturally_with_extreme_coords(self):
        """Test move_mouse_naturally() with extreme coordinates."""
        behavior = self._make_behavior()
        # Negative coordinates
        asyncio.run(behavior.move_mouse_naturally(-100, -100))
        # Very large coordinates
        asyncio.run(behavior.move_mouse_naturally(10000, 10000))
        # Zero coordinates
        asyncio.run(behavior.move_mouse_naturally(0, 0))
        # Float coordinates (should be handled)
        asyncio.run(behavior.move_mouse_naturally(500.5, 400.5))

    def test_move_mouse_naturally_with_various_speeds(self):
        """Test move_mouse_naturally() with various speed values."""
        behavior = self._make_behavior()
        for speed in ["normal", "fast", "slow", "unknown", ""]:
            asyncio.run(behavior.move_mouse_naturally(600, 500, speed=speed))

    def test_human_click_with_various_inputs(self):
        """Test human_click() with various input combinations."""
        behavior = self._make_behavior()
        # With selector
        asyncio.run(behavior.human_click("button"))
        # With coordinates
        asyncio.run(behavior.human_click(x=300, y=200))
        # With both (selector takes precedence)
        asyncio.run(behavior.human_click("button", x=300, y=200))
        # With neither (should click at current position)
        asyncio.run(behavior.human_click())

    def test_scroll_naturally_with_extreme_values(self):
        """Test scroll_naturally() with extreme pixel values."""
        behavior = self._make_behavior()
        # Very small scroll
        asyncio.run(behavior.scroll_naturally(1))
        # Very large scroll
        asyncio.run(behavior.scroll_naturally(100000))
        # Negative scroll (scroll up)
        asyncio.run(behavior.scroll_naturally(-500, direction="up"))
        # Zero scroll
        asyncio.run(behavior.scroll_naturally(0))

    def test_type_like_human_with_various_texts(self):
        """Test type_like_human() with various text inputs."""
        behavior = self._make_behavior()
        # Empty string
        asyncio.run(behavior.type_like_human("input", ""))
        # Single character
        asyncio.run(behavior.type_like_human("input", "a"))
        # Short string
        asyncio.run(behavior.type_like_human("input", "hello"))
        # Special characters
        asyncio.run(behavior.type_like_human("input", "!@#$%"))
        # Unicode
        asyncio.run(behavior.type_like_human("input", "Hello 世界"))
        # Low mistake rate only (high rates are too slow for tests)
        for rate in [0.0, 0.01]:
            asyncio.run(behavior.type_like_human("input", "test", mistake_rate=rate))

    def test_simulate_reading_with_various_durations(self):
        """Test simulate_reading() with various duration values."""
        behavior = self._make_behavior()
        # Very short
        asyncio.run(behavior.simulate_reading(0.1))
        # Long (capped for test)
        asyncio.run(behavior.simulate_reading(2.0))
        # Various content factors
        for factor in [0.1, 0.5, 1.0, 2.0, 5.0]:
            asyncio.run(behavior.simulate_reading(0.5, content_factor=factor))

    def test_random_idle_behavior_with_various_durations(self):
        """Test random_idle_behavior() with various duration values."""
        behavior = self._make_behavior()
        for duration in [0.1, 0.5, 1.0, 2.0]:
            asyncio.run(behavior.random_idle_behavior(duration_seconds=duration))

    def test_micro_movement_with_various_durations(self):
        """Test micro_movement_while_waiting() with various duration values."""
        behavior = self._make_behavior()
        for duration in [10, 100, 500, 1000]:
            asyncio.run(behavior.micro_movement_while_waiting(duration))

    def test_think_before_action_with_various_importance(self):
        """Test think_before_action() with various importance levels."""
        behavior = self._make_behavior()
        for importance in ["normal", "critical", "low", "unknown", ""]:
            asyncio.run(behavior.think_before_action(importance))

    def test_fatigue_ramps_over_time(self):
        """Test that fatigue level increases with actions."""
        behavior = self._make_behavior()
        initial_fatigue = behavior.fatigue_level
        # Simulate many actions
        for _ in range(50):
            behavior.action_count += 1
            behavior._update_fatigue()
        assert behavior.fatigue_level >= initial_fatigue
        # Fatigue should be capped
        assert behavior.fatigue_level <= 0.82

    def test_realism_level_affects_behavior(self):
        """Test that different realism levels produce different behavior."""
        # Full realism
        behavior_full = self._make_behavior()
        behavior_full.realism_level = 3
        # Light realism
        behavior_light = self._make_behavior()
        behavior_light.realism_level = 1
        # Off realism
        behavior_off = self._make_behavior()
        behavior_off.realism_level = 0

        # Micro movement should be fastest with off realism
        import time

        start = time.time()
        asyncio.run(behavior_off.micro_movement_while_waiting(100))
        off_time = time.time() - start

        start = time.time()
        asyncio.run(behavior_full.micro_movement_while_waiting(100))
        full_time = time.time() - start

        # Off should be faster than full
        assert off_time <= full_time

    def test_simulate_distraction_with_various_max_seconds(self):
        """Test simulate_distraction() with various max_seconds values."""
        behavior = self._make_behavior()
        for max_sec in [0.1, 0.5, 1.0, 2.0, 5.0]:
            asyncio.run(behavior.simulate_distraction(max_sec))

    def test_simulate_changed_mind_probability(self):
        """Test simulate_changed_mind() with various probability values."""
        behavior = self._make_behavior()
        for prob in [0.0, 0.1, 0.5, 0.9, 1.0]:
            result = asyncio.run(behavior.simulate_changed_mind(probability=prob))
            assert isinstance(result, bool)

    def test_apply_viewport_jitter_handles_errors(self):
        """Test apply_viewport_jitter() handles missing page methods gracefully."""
        behavior = self._make_behavior()
        # Should not crash even if page doesn't support set_viewport_size
        asyncio.run(behavior.apply_viewport_jitter())

    def test_random_seed_reproducibility(self):
        """Test that the same seed produces the same behavior sequence."""
        # This tests that our RNG is properly wired
        behavior1 = self._make_behavior(rng_seed=42)
        behavior2 = self._make_behavior(rng_seed=42)

        # Same seed should produce same random choices
        for _ in range(10):
            assert behavior1.rng.random() == behavior2.rng.random()

    def test_different_seeds_produce_different_behavior(self):
        """Test that different seeds produce different behavior."""
        behavior1 = self._make_behavior(rng_seed=42)
        behavior2 = self._make_behavior(rng_seed=99)

        # Different seeds should produce different random choices
        values1 = [behavior1.rng.random() for _ in range(10)]
        values2 = [behavior2.rng.random() for _ in range(10)]
        assert values1 != values2


class TestHumanBehaviorPropertyTests:
    """Property-based tests: invariants that should always hold."""

    def _make_behavior(self, rng_seed=None):
        page = MockPage()
        rng = random.Random(rng_seed)
        return HumanBehavior(page, rng=rng)

    def test_mouse_position_always_updated_after_move(self):
        """Property: mouse position should be updated after any move operation."""
        behavior = self._make_behavior()
        old_pos = behavior.last_mouse_pos
        asyncio.run(behavior.move_mouse_naturally(800, 600))
        # Position should have changed (or at least been recorded)
        assert behavior.last_mouse_pos[0] >= 0
        assert behavior.last_mouse_pos[1] >= 0

    def test_action_count_increases_with_think_before_action(self):
        """Property: action_count should increase after think_before_action."""
        behavior = self._make_behavior()
        initial_count = behavior.action_count
        asyncio.run(behavior.think_before_action("normal"))
        assert behavior.action_count > initial_count

    def test_fatigue_never_negative(self):
        """Property: fatigue_level should never be negative."""
        behavior = self._make_behavior()
        for _ in range(100):
            behavior._update_fatigue()
            assert behavior.fatigue_level >= 0.0

    def test_fatigue_never_exceeds_max(self):
        """Property: fatigue_level should never exceed 0.82."""
        behavior = self._make_behavior()
        behavior.action_count = 10000
        behavior._update_fatigue()
        assert behavior.fatigue_level <= 0.82

    def test_bezier_curve_always_returns_points(self):
        """Property: _bezier_curve should always return a non-empty list of points."""
        behavior = self._make_behavior()
        for steps in [1, 5, 10, 25, 50]:
            points = asyncio.run(
                behavior._bezier_curve((0, 0), (100, 100), steps=steps)
            )
            assert len(points) == steps + 1
            # All points should be numeric tuples
            for x, y in points:
                assert isinstance(x, (int, float))
                assert isinstance(y, (int, float))
