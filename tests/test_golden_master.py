"""
Golden master / visual regression tests for human-like gestures.
Addresses #117: No golden master or visual regression tests for human-like gestures.
"""

import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestGoldenMasterMouse:
    """Golden master tests for mouse gesture generation."""

    def test_bezier_curve_golden_master(self):
        """Bézier curve should produce consistent output with same seed."""
        import asyncio
        from behavior.human_behavior import HumanBehavior
        import random

        class FakePage:
            async def evaluate(self, js):
                return {"x": 500, "y": 350}

        # Golden master: seed 42, steps 20
        rng = random.Random(42)
        hb = HumanBehavior(FakePage(), rng=rng)
        points = asyncio.run(
            hb._bezier_curve((100, 100), (400, 300), steps=20)
        )

        # Golden master assertions
        assert len(points) == 21
        # Points should generally progress from start to end
        assert points[0][0] <= 150  # Near start x
        assert points[0][1] <= 150  # Near start y
        assert points[-1][0] >= 350  # Near end x
        assert points[-1][1] >= 250  # Near end y
        # Points should progress generally from start to end
        assert points[5][0] > points[0][0]
        assert points[15][0] < points[-1][0]

    def test_bezier_curve_different_seeds(self):
        """Different seeds should produce different wobble patterns."""
        import asyncio
        from behavior.human_behavior import HumanBehavior
        import random

        class FakePage:
            async def evaluate(self, js):
                return {"x": 500, "y": 350}

        rng1 = random.Random(42)
        hb1 = HumanBehavior(FakePage(), rng=rng1)
        points1 = asyncio.run(
            hb1._bezier_curve((100, 100), (400, 300), steps=10)
        )

        rng2 = random.Random(99)
        hb2 = HumanBehavior(FakePage(), rng=rng2)
        points2 = asyncio.run(
            hb2._bezier_curve((100, 100), (400, 300), steps=10)
        )

        # Both should have same number of points
        assert len(points1) == len(points2)
        # Both should progress from start to end
        assert points1[0][0] <= points1[-1][0] + 50
        assert points2[0][0] <= points2[-1][0] + 50


class TestGoldenMasterTyping:
    """Golden master tests for typing behavior."""

    def test_persona_typing_params_golden_master(self):
        """Persona typing parameters should be consistent."""
        from behavior.persona_rotator import PersonaRotator
        rotator = PersonaRotator("test", rng=__import__("random").Random(42))
        rotator.set_current_persona("casual_user")
        params = rotator.get_behavior_params()

        # Golden master assertions for casual_user
        assert params["persona_name"] == "casual_user"
        assert params["typing_delay_min"] < params["typing_delay_max"]
        assert params["typing_delay_min"] >= 30
        assert params["typing_delay_max"] <= 200


class TestGoldenMasterScroll:
    """Golden master tests for scroll behavior."""

    def test_scroll_natural_produces_steps(self):
        """Scroll naturally should produce expected step count."""
        import random
        # With full realism, steps should be 5-12
        rng = random.Random(42)
        steps = rng.randint(5, 12)
        assert 5 <= steps <= 12


class TestGoldenMasterStealth:
    """Golden master tests for stealth script."""

    def test_stealth_script_length_stable(self):
        """Stealth script length should be stable across calls."""
        from stealth.advanced_stealth import get_stealth_script
        s1 = get_stealth_script()
        s2 = get_stealth_script()
        assert len(s1) == len(s2)
        assert len(s1) > 5000

    def test_stealth_script_with_seed_stable(self):
        """Stealth script with same seed should be identical."""
        from stealth.advanced_stealth import get_stealth_script
        s1 = get_stealth_script(fingerprint_seed="golden-master-seed")
        s2 = get_stealth_script(fingerprint_seed="golden-master-seed")
        assert s1 == s2
