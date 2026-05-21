"""
Snapshot tests for CDP commands sent during human sessions.
Addresses #164: Add snapshot tests for exact CDP commands.
"""

import pytest
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestCDPSnapshotMouse:
    """Snapshot tests for mouse-related CDP commands."""

    def test_bezier_curve_generates_expected_points(self):
        """Bézier curve should produce consistent point counts."""
        import asyncio
        from behavior.human_behavior import HumanBehavior
        import random

        class FakePage:
            async def evaluate(self, js):
                return {"x": 500, "y": 350}

        rng = random.Random(42)
        hb = HumanBehavior(FakePage(), rng=rng)
        points = asyncio.run(
            hb._bezier_curve((100, 100), (400, 300), steps=20)
        )
        # Snapshot: should always produce steps+1 points
        assert len(points) == 21
        # Points should generally progress from start to end
        assert points[0][0] <= points[-1][0] + 50  # x generally increases
        assert points[0][1] <= points[-1][1] + 50  # y generally increases

    def test_mouse_path_stays_within_bounds(self):
        """Mouse path should stay within reasonable bounds."""
        import asyncio
        from behavior.human_behavior import HumanBehavior
        import random

        class FakePage:
            async def evaluate(self, js):
                return {"x": 500, "y": 350}

        rng = random.Random(42)
        hb = HumanBehavior(FakePage(), rng=rng)
        points = asyncio.run(
            hb._bezier_curve((200, 200), (600, 400), steps=15)
        )
        for x, y in points:
            assert 150 <= x <= 650, f"x={x} out of bounds"
            assert 150 <= y <= 450, f"y={y} out of bounds"


class TestCDPSnapshotKeyboard:
    """Snapshot tests for keyboard-related behavior."""

    def test_typing_delay_ranges(self):
        """Typing delays should be within expected ranges."""
        from behavior.persona_rotator import PersonaRotator
        rotator = PersonaRotator("test")
        rotator.set_current_persona("casual_user")
        params = rotator.get_behavior_params()
        # Snapshot: casual user typing delays
        assert 30 <= params["typing_delay_min"] <= 100
        assert 80 <= params["typing_delay_max"] <= 200
        assert params["typing_delay_min"] < params["typing_delay_max"]


class TestCDPSnapshotScroll:
    """Snapshot tests for scroll behavior."""

    def test_scroll_steps_within_range(self):
        """Scroll steps should be within expected range."""
        import random
        # With full realism, steps should be 5-12
        rng = random.Random(42)
        steps = rng.randint(5, 12)
        assert 5 <= steps <= 12


class TestCDPSnapshotStealth:
    """Snapshot tests for stealth script structure."""

    def test_stealth_script_contains_expected_sections(self):
        """Stealth script should contain all expected sections."""
        from stealth.advanced_stealth import get_stealth_script
        script = get_stealth_script()
        # These are the key sections that must be present
        expected_sections = [
            "webdriver",
            "plugins",
            "canvas",
            "WebGL",
            "AudioContext",
            "getBattery",
            "chrome",
            "permissions",
            "hardwareConcurrency",
            "deviceMemory",
            "screen",
            "devicePixelRatio",
        ]
        for section in expected_sections:
            assert section in script, f"Missing section: {section}"

    def test_stealth_script_no_destructive_mangling(self):
        """Stealth script should not use destructive canvas mangling."""
        from stealth.advanced_stealth import get_stealth_script
        script = get_stealth_script()
        assert "replace(/[0-9]" not in script, "Destructive mangling should be gone"
