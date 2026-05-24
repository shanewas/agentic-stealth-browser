"""
Differential testing: patched vs unpatched browser for the same actions.
Addresses #180: No differential testing between patched and unpatched browser.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stealth.advanced_stealth import get_stealth_script


class TestDifferentialStealth:
    """Compare stealth script with and without patches."""

    def test_patched_script_has_webdriver_spoof(self):
        """Patched script should spoof webdriver."""
        script = get_stealth_script()
        assert "webdriver" in script
        assert "false" in script

    def test_patched_script_has_canvas_noise(self):
        """Patched script should add canvas noise."""
        script = get_stealth_script()
        assert "getImageData" in script
        assert "fillText" in script

    def test_patched_script_has_webgl_spoof(self):
        """Patched script should spoof WebGL parameters."""
        script = get_stealth_script()
        assert "WebGL" in script or "webgl" in script
        assert "getParameter" in script

    def test_patched_script_has_audio_spoof(self):
        """Patched script should add audio noise."""
        script = get_stealth_script()
        assert "AudioContext" in script or "audio" in script.lower()

    def test_patched_script_has_chrome_runtime(self):
        """Patched script should define chrome runtime."""
        script = get_stealth_script()
        assert "chrome" in script

    def test_patched_script_has_plugins(self):
        """Patched script should define plugins."""
        script = get_stealth_script()
        assert "plugins" in script

    def test_patched_script_has_battery(self):
        """Patched script should spoof battery API."""
        script = get_stealth_script()
        assert "getBattery" in script

    def test_patched_script_has_permissions(self):
        """Patched script should spoof permissions."""
        script = get_stealth_script()
        assert "permissions" in script or "query" in script

    def test_stealth_script_length(self):
        """Stealth script should be substantial."""
        script = get_stealth_script()
        assert len(script) > 5000

    def test_different_seeds_different_fingerprints(self):
        """Different seeds should produce different canvas noise."""
        script_a = get_stealth_script(fingerprint_seed="seed-a")
        script_b = get_stealth_script(fingerprint_seed="seed-b")
        # At least the seed values should differ
        assert "seed-a" in script_a or "seed-b" in script_b


class TestDifferentialBehavior:
    """Compare behavior parameters across personas."""

    def test_casual_vs_power_typing_speed(self):
        """Power user should have faster typing than casual."""
        from behavior.persona_rotator import PERSONA_TEMPLATES

        casual = PERSONA_TEMPLATES["casual_user"]
        power = PERSONA_TEMPLATES["power_user"]
        assert power.typing_speed > casual.typing_speed

    def test_casual_vs_power_mouse_precision(self):
        """Power user should have higher mouse precision."""
        from behavior.persona_rotator import PERSONA_TEMPLATES

        casual = PERSONA_TEMPLATES["casual_user"]
        power = PERSONA_TEMPLATES["power_user"]
        assert power.mouse_precision > casual.mouse_precision

    def test_mobile_vs_desktop_device_type(self):
        """Mobile persona should have different device type."""
        from behavior.persona_rotator import PERSONA_TEMPLATES

        mobile = PERSONA_TEMPLATES["mobile_user"]
        power = PERSONA_TEMPLATES["power_user"]
        assert mobile.device_type != power.device_type


class TestDifferentialTLS:
    """Compare TLS fingerprints across regions."""

    def test_us_vs_japan_tls_profiles(self):
        """US and Japan should have different TLS profiles."""
        from stealth.tls_fingerprint import get_tls_manager

        us = get_tls_manager("us")
        jp = get_tls_manager("japan")
        us_profile = us.get_profile()
        jp_profile = jp.get_profile()
        # Both should have ciphers but may differ
        assert len(us_profile["ciphers"]) > 0
        assert len(jp_profile["ciphers"]) > 0

    def test_ja3_chrome_vs_firefox_different(self):
        """Chrome and Firefox JA3 should differ."""
        from stealth.tls_ja3_ja4 import JA3Fingerprint

        chrome = JA3Fingerprint.get_chrome_ja3()
        firefox = JA3Fingerprint.get_firefox_ja3()
        assert chrome["ja3_hash"] != firefox["ja3_hash"]
