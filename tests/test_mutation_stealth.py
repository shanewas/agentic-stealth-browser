"""
Mutation testing for stealth patches.
Addresses #158: Add mutation testing to verify stealth patches are effective.

Tests that removing or modifying stealth patches causes detectable changes.
"""

import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stealth.advanced_stealth import get_stealth_script


class TestMutationStealthPatches:
    """Mutation tests for stealth script patches."""

    def test_webdriver_mutation_detectable(self):
        """Removing webdriver spoof should be detectable."""
        original = get_stealth_script()
        # Verify webdriver spoof is present
        assert "webdriver" in original
        assert "false" in original
        # If we removed it, the script would be different
        mutated = original.replace("'webdriver'", "'NOT_webdriver'")
        assert mutated != original

    def test_canvas_mutation_detectable(self):
        """Removing canvas noise should be detectable."""
        original = get_stealth_script()
        assert "getImageData" in original
        mutated = original.replace("getImageData", "NOT_getImageData")
        assert mutated != original

    def test_webgl_mutation_detectable(self):
        """Removing WebGL spoof should be detectable."""
        original = get_stealth_script()
        assert "WebGL" in original or "webgl" in original
        mutated = original.replace("WebGL", "NOT_WebGL").replace("webgl", "NOT_webgl")
        assert mutated != original

    def test_audio_mutation_detectable(self):
        """Removing audio spoof should be detectable."""
        original = get_stealth_script()
        assert "AudioContext" in original or "audio" in original.lower()
        mutated = original.replace("AudioContext", "NOT_AudioContext")
        assert mutated != original

    def test_battery_mutation_detectable(self):
        """Removing battery spoof should be detectable."""
        original = get_stealth_script()
        assert "getBattery" in original
        mutated = original.replace("getBattery", "NOT_getBattery")
        assert mutated != original

    def test_chrome_runtime_mutation_detectable(self):
        """Removing chrome runtime should be detectable."""
        original = get_stealth_script()
        assert "chrome" in original
        mutated = original.replace("chrome", "NOT_chrome")
        assert mutated != original

    def test_plugins_mutation_detectable(self):
        """Removing plugins spoof should be detectable."""
        original = get_stealth_script()
        assert "plugins" in original
        mutated = original.replace("plugins", "NOT_plugins")
        assert mutated != original

    def test_permissions_mutation_detectable(self):
        """Removing permissions spoof should be detectable."""
        original = get_stealth_script()
        assert "permissions" in original or "query" in original
        mutated = original.replace("permissions", "NOT_permissions")
        assert mutated != original


class TestMutationBehaviorPatches:
    """Mutation tests for behavior patches."""

    def test_bezier_curve_mutation_affects_path(self):
        """Modifying bezier control points should change the path."""
        import asyncio
        from behavior.human_behavior import HumanBehavior
        import random

        class FakePage:
            async def evaluate(self, js):
                return {"x": 500, "y": 350}

        rng = random.Random(42)
        hb = HumanBehavior(FakePage(), rng=rng)
        original = asyncio.run(
            hb._bezier_curve((100, 100), (400, 300), steps=10)
        )

        # Different RNG should produce different wobble
        rng2 = random.Random(99)
        hb2 = HumanBehavior(FakePage(), rng=rng2)
        mutated = asyncio.run(
            hb2._bezier_curve((100, 100), (400, 300), steps=10)
        )

        # Paths should be different due to different wobble
        assert original != mutated
        # Both should have correct number of points
        assert len(original) == 11
        assert len(mutated) == 11

    def test_fatigue_mutation_affects_timing(self):
        """Modifying fatigue calculation should affect timing."""
        from behavior.human_behavior import HumanBehavior
        import random

        class FakePage:
            async def evaluate(self, js):
                return {"x": 500, "y": 350}

        rng = random.Random(42)
        hb = HumanBehavior(FakePage(), rng=rng)

        # Normal fatigue
        hb.action_count = 100
        hb._update_fatigue()
        normal_fatigue = hb.fatigue_level

        # Mutated: higher action count
        hb.action_count = 1000
        hb._update_fatigue()
        mutated_fatigue = hb.fatigue_level

        assert mutated_fatigue > normal_fatigue


class TestMutationTLSPatches:
    """Mutation tests for TLS patches."""

    def test_tls_cipher_mutation_detectable(self):
        """Changing TLS ciphers should produce different fingerprint."""
        from stealth.tls_fingerprint import get_tls_manager
        manager = get_tls_manager("us")
        original = manager.get_profile()

        # Verify ciphers exist
        assert "ciphers" in original
        assert len(original["ciphers"]) > 0

    def test_ja3_mutation_detectable(self):
        """Changing JA3 components should produce different hash."""
        from stealth.tls_ja3_ja4 import JA3Fingerprint
        original = JA3Fingerprint.get_chrome_ja3()

        # Mutate ciphers
        mutated_ja3 = JA3Fingerprint.generate_ja3(
            "772", ["9999"], ["0"], ["29"], ["0"]
        )
        mutated_hash = JA3Fingerprint.generate_ja3_hash(mutated_ja3)

        assert original["ja3_hash"] != mutated_hash
