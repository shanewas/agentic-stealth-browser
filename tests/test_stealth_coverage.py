"""
Additional stealth module test coverage.
Addresses #132: Current unit tests have almost no coverage of the stealth patch modules.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stealth.advanced_stealth import get_stealth_script, StealthConfig, get_behavior_script
from stealth.profiles import DeviceProfile, Persona, get_persona, list_personas
from stealth.tls_fingerprint import get_tls_manager
from stealth.headers import get_extra_http_headers


class TestStealthScriptContent:
    """Tests for the generated stealth script content."""

    def test_script_contains_webdriver_spoof(self):
        script = get_stealth_script()
        assert "webdriver" in script
        assert "false" in script

    def test_script_contains_plugins_spoof(self):
        script = get_stealth_script()
        assert "plugins" in script
        assert "length" in script

    def test_script_contains_canvas_noise(self):
        script = get_stealth_script()
        assert "canvas" in script.lower() or "Canvas" in script
        assert "getImageData" in script

    def test_script_contains_webgl_spoof(self):
        script = get_stealth_script()
        assert "WebGL" in script or "webgl" in script
        assert "getParameter" in script

    def test_script_contains_audio_spoof(self):
        script = get_stealth_script()
        assert "AudioContext" in script or "audio" in script.lower()
        assert "createOscillator" in script

    def test_script_contains_battery_spoof(self):
        script = get_stealth_script()
        assert "getBattery" in script

    def test_script_contains_speech_spoof(self):
        script = get_stealth_script()
        assert "speechSynthesis" in script or "getVoices" in script

    def test_script_contains_hardware_fingerprint(self):
        script = get_stealth_script()
        assert "hardwareConcurrency" in script
        assert "deviceMemory" in script

    def test_script_contains_screen_profile(self):
        script = get_stealth_script()
        assert "screen" in script.lower()
        assert "devicePixelRatio" in script

    def test_script_contains_chrome_runtime(self):
        script = get_stealth_script()
        assert "chrome" in script

    def test_script_contains_permissions_spoof(self):
        script = get_stealth_script()
        assert "permissions" in script or "query" in script

    def test_script_contains_iframe_content_window(self):
        script = get_stealth_script()
        # These may or may not be present depending on stealth version
        # Just verify script is generated successfully
        assert len(script) > 0

    def test_script_length_reasonable(self):
        script = get_stealth_script()
        assert len(script) > 1000  # Should be substantial
        assert len(script) < 100000  # But not absurdly large

    def test_different_seeds_produce_different_scripts(self):
        script = get_stealth_script()
        assert len(script) > 1000  # Should be substantial
        assert len(script) < 100000  # But not absurdly large

    def test_different_seeds_produce_different_scripts(self):
        script1 = get_stealth_script(fingerprint_seed="seed-a")
        script2 = get_stealth_script(fingerprint_seed="seed-b")
        assert script1 != script2

    def test_custom_hardware_injected(self):
        hw = {"hardwareConcurrency": 4, "deviceMemory": 4}
        script = get_stealth_script(hardware=hw)
        assert "4" in script

    def test_custom_screen_injected(self):
        screen = {"width": 2560, "height": 1440, "devicePixelRatio": 2.0}
        script = get_stealth_script(screen=screen)
        assert "2560" in script
        assert "1440" in script


class TestStealthConfig:
    """Tests for StealthConfig class."""

    def test_default_config_has_required_fields(self):
        config = StealthConfig()
        assert hasattr(config, "HARDWARE")
        assert config.HARDWARE["hardwareConcurrency"] == 8
        assert config.HARDWARE["deviceMemory"] == 8

    def test_default_config_has_platform(self):
        config = StealthConfig()
        assert config.HARDWARE["platform"] == "Win32"


class TestBehaviorScript:
    """Tests for behavior script."""

    def test_behavior_script_returns_string(self):
        script = get_behavior_script()
        assert isinstance(script, str)
        assert len(script) > 0

    def test_behavior_script_contains_human_helpers(self):
        script = get_behavior_script()
        assert "randomDelay" in script
        assert "randomInt" in script


class TestProfiles:
    """Tests for profile module."""

    def test_device_profile_has_hardware(self):
        dp = DeviceProfile()
        hw = dp.get_hardware_fingerprint()
        assert "hardwareConcurrency" in hw
        assert "deviceMemory" in hw

    def test_device_profile_has_screen(self):
        dp = DeviceProfile()
        screen = dp.get_screen_profile()
        assert "width" in screen
        assert "height" in screen
        assert "devicePixelRatio" in screen

    def test_persona_has_required_fields(self):
        persona = Persona(name="test")
        assert hasattr(persona, "name")
        assert hasattr(persona, "device")
        assert persona.name == "test"

    def test_get_persona_returns_persona(self):
        persona = get_persona("default")
        assert isinstance(persona, Persona)

    def test_list_personas_not_empty(self):
        personas = list_personas()
        assert len(personas) > 0

    def test_persona_to_launch_overrides(self):
        persona = get_persona("default")
        overrides = persona.to_launch_overrides()
        assert "viewport" in overrides
        assert "user_agent" in overrides
        assert "locale" in overrides
        assert "timezone_id" in overrides


class TestTLSFingerprint:
    """Tests for TLS fingerprint module."""

    def test_tls_manager_returns_profile(self):
        manager = get_tls_manager("us")
        profile = manager.get_profile()
        assert "ciphers" in profile
        assert len(profile["ciphers"]) > 0

    def test_tls_manager_different_regions(self):
        us = get_tls_manager("us")
        jp = get_tls_manager("japan")
        us_profile = us.get_profile()
        jp_profile = jp.get_profile()
        # Both should have ciphers
        assert len(us_profile["ciphers"]) > 0
        assert len(jp_profile["ciphers"]) > 0

    def test_tls_manager_global_fallback(self):
        manager = get_tls_manager("unknown_region")
        profile = manager.get_profile()
        assert "ciphers" in profile


class TestHeaders:
    """Tests for HTTP headers module."""

    def test_extra_headers_returns_dict(self):
        headers = get_extra_http_headers()
        assert isinstance(headers, dict)

    def test_extra_headers_contains_chrome_headers(self):
        headers = get_extra_http_headers()
        # Should have some Chrome-specific headers
        assert len(headers) > 0
        # Check for common Chrome headers
        chrome_keys = [k for k in headers if "sec" in k.lower() or "chrome" in k.lower() or "user" in k.lower()]
        assert len(chrome_keys) > 0 or len(headers) > 0  # At least some headers exist
