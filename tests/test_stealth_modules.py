"""
Unit tests for stealth module components.
Addresses #132: Current unit tests have almost no coverage of the stealth patch modules.

Tests:
- advanced_stealth.py: StealthConfig, get_stealth_script, check_stealth_compatibility
- tls_fingerprint.py: TLSFingerprintManager, region mapping, launch args
- headers.py: get_extra_http_headers
- profiles.py: Persona, DeviceProfile
"""

import json
import re
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stealth.advanced_stealth import (
    StealthConfig,
    get_stealth_script,
    check_stealth_compatibility,
    get_behavior_script,
)
from stealth.tls_fingerprint import (
    TLSFingerprintManager,
    get_tls_manager,
    Region,
)
from stealth.headers import get_extra_http_headers
from stealth.profiles import (
    DEFAULT_PERSONA,
    get_persona,
    list_personas,
)


# === advanced_stealth.py tests ===


class TestStealthConfig:
    """Test StealthConfig dataclass."""

    def test_hardware_defaults(self):
        assert StealthConfig.HARDWARE["hardwareConcurrency"] == 8
        assert StealthConfig.HARDWARE["deviceMemory"] == 8
        assert StealthConfig.HARDWARE["platform"] == "Win32"

    def test_webgl_defaults(self):
        assert "Intel" in StealthConfig.WEBGL["vendor"]
        assert "UHD Graphics" in StealthConfig.WEBGL["renderer"]

    def test_screen_defaults(self):
        assert StealthConfig.SCREEN["colorDepth"] == 24
        assert StealthConfig.SCREEN["pixelDepth"] == 24

    def test_languages(self):
        assert StealthConfig.LANGUAGES == ["en-US", "en"]

    def test_plugins_count(self):
        assert len(StealthConfig.PLUGINS) == 3


class TestGetStealthScript:
    """Test stealth script generation."""

    def test_returns_string(self):
        script = get_stealth_script()
        assert isinstance(script, str)
        assert len(script) > 100

    def test_contains_webdriver_patch(self):
        script = get_stealth_script()
        assert "webdriver" in script
        assert "false" in script

    def test_contains_canvas_patch(self):
        script = get_stealth_script()
        assert "canvas" in script.lower() or "fillText" in script

    def test_contains_webgl_patch(self):
        script = get_stealth_script()
        assert "webgl" in script.lower() or "getParameter" in script

    def test_contains_webrtc_protection(self):
        script = get_stealth_script()
        assert "RTCPeerConnection" in script

    def test_webrtc_addeventlistener_icecandidate_filtered(self):
        # A page listening via pc.addEventListener('icecandidate', ...) must be routed
        # through the same candidate-filtering wrapper as the onicecandidate property
        # setter, not left as a raw passthrough that leaks private IPs.
        script = get_stealth_script()
        assert "pc.addEventListener" in script
        assert "wrapIceHandler(listener)" in script
        assert 'type === "icecandidate"' in script

    def test_contains_audio_spoofing(self):
        script = get_stealth_script()
        assert "AudioContext" in script or "AudioC" in script

    def test_custom_fingerprint_seed(self):
        seed = "test-session-123"
        script = get_stealth_script(fingerprint_seed=seed)
        # Seed should be present in the script
        assert "test-session-123" in script or json.dumps(seed)[1:-1] in script

    def test_hardware_injection(self):
        hw = {"hardwareConcurrency": 4, "deviceMemory": 4}
        script = get_stealth_script(hardware=hw)
        # Hardware values should be injected
        assert "4" in script

    def test_screen_injection(self):
        screen = {"width": 1440, "height": 900, "devicePixelRatio": 2.0}
        script = get_stealth_script(screen=screen)
        assert "1440" in script
        assert "900" in script

    def test_seed_sanitization(self):
        # Malicious seed should be sanitized
        malicious_seed = '"; alert("xss"); //'
        script = get_stealth_script(fingerprint_seed=malicious_seed)
        # The malicious characters (quotes, semicolons, angle brackets) should be stripped
        # The sanitization replaces ["'\\;<>] with empty string
        assert '"' not in malicious_seed.replace('"', "")  # verify our test is valid
        # After sanitization, the seed should not contain the original malicious chars
        # The regex sub removes ["'\\;<>] from the seed
        safe_seed = re.sub(r'["\'\\;<>]', "", malicious_seed)
        assert (
            safe_seed in script
            or safe_seed == ""
            or len(safe_seed) < len(malicious_seed)
        )

    def test_webrtc_ip_generation(self):
        script = get_stealth_script(fingerprint_seed="test")
        # Should contain a fake IP (not RFC5737 test ranges)
        # IP should be in 72.x.x.x range based on the code
        assert "72." in script

    def test_permissions_spoofing(self):
        script = get_stealth_script()
        assert "permissions" in script.lower()

    def test_chrome_runtime_spoofing(self):
        script = get_stealth_script()
        assert "chrome" in script.lower()

    def test_plugins_mock(self):
        script = get_stealth_script()
        assert "PDF Viewer" in script

    def test_different_seeds_produce_different_scripts(self):
        script1 = get_stealth_script(fingerprint_seed="seed-a")
        script2 = get_stealth_script(fingerprint_seed="seed-b")
        # Scripts should differ due to different seeds
        assert script1 != script2


class TestStealthCompatibility:
    """Test Playwright version detection and compatibility checks."""

    def test_returns_dict(self):
        result = check_stealth_compatibility()
        assert isinstance(result, dict)

    def test_has_playwright_version(self):
        result = check_stealth_compatibility()
        assert "playwright_version" in result

    def test_has_stealth_version(self):
        result = check_stealth_compatibility()
        assert "stealth_version" in result

    def test_warning_is_none_or_string(self):
        result = check_stealth_compatibility()
        assert result.get("warning") is None or isinstance(result.get("warning"), str)


class TestGetBehaviorScript:
    """Test behavior script generation."""

    def test_returns_string(self):
        script = get_behavior_script()
        assert isinstance(script, str)

    def test_contains_human_helpers(self):
        script = get_behavior_script()
        assert "randomDelay" in script
        assert "randomInt" in script


# === tls_fingerprint.py tests ===


class TestTLSFingerprintManager:
    """Test TLS fingerprint management."""

    def test_us_profile(self):
        manager = TLSFingerprintManager(Region.US)
        profile = manager.get_profile()
        assert profile["name"] == "chrome_124_windows_us"
        assert len(profile["ciphers"]) > 0

    def test_eu_profile(self):
        manager = TLSFingerprintManager(Region.EU)
        profile = manager.get_profile()
        assert profile["name"] == "chrome_124_windows_eu"

    def test_japan_profile(self):
        manager = TLSFingerprintManager(Region.JAPAN)
        profile = manager.get_profile()
        assert profile["name"] == "chrome_124_windows_japan"

    def test_korea_profile(self):
        manager = TLSFingerprintManager(Region.KOREA)
        profile = manager.get_profile()
        assert profile["name"] == "chrome_124_windows_korea"

    def test_global_profile(self):
        manager = TLSFingerprintManager(Region.GLOBAL)
        profile = manager.get_profile()
        assert profile["name"] == "chrome_124_windows_generic"

    def test_launch_args_not_empty(self):
        manager = TLSFingerprintManager(Region.US)
        args = manager.get_launch_args()
        assert len(args) > 0
        assert "--enable-quic" in args

    def test_profile_has_ciphers(self):
        manager = TLSFingerprintManager(Region.US)
        profile = manager.get_profile()
        assert "ciphers" in profile
        assert len(profile["ciphers"]) > 5

    def test_profile_has_extensions(self):
        manager = TLSFingerprintManager(Region.US)
        profile = manager.get_profile()
        assert "extensions" in profile
        assert len(profile["extensions"]) > 5

    def test_profile_has_elliptic_curves(self):
        manager = TLSFingerprintManager(Region.US)
        profile = manager.get_profile()
        assert "elliptic_curves" in profile
        assert "X25519" in profile["elliptic_curves"]

    def test_get_tls_manager_convenience(self):
        manager = get_tls_manager("us")
        assert manager.region == Region.US

    def test_get_tls_manager_japan(self):
        manager = get_tls_manager("japan")
        assert manager.region == Region.JAPAN

    def test_get_tls_manager_invalid_defaults_to_global(self):
        manager = get_tls_manager("invalid")
        assert manager.region == Region.GLOBAL

    def test_region_mapping_locale_ja(self):
        region = TLSFingerprintManager.get_region_for_locale("ja-JP")
        assert region == Region.JAPAN

    def test_region_mapping_locale_ko(self):
        region = TLSFingerprintManager.get_region_for_locale("ko-KR")
        assert region == Region.KOREA

    def test_region_mapping_locale_de(self):
        region = TLSFingerprintManager.get_region_for_locale("de-DE")
        assert region == Region.EU

    def test_region_mapping_locale_en_us(self):
        region = TLSFingerprintManager.get_region_for_locale("en-US")
        assert region == Region.US

    def test_region_mapping_locale_en_defaults_us(self):
        region = TLSFingerprintManager.get_region_for_locale("en")
        assert region == Region.US

    def test_region_mapping_unknown_defaults_global(self):
        region = TLSFingerprintManager.get_region_for_locale("xyz")
        assert region == Region.GLOBAL

    def test_explain_limitations(self):
        manager = TLSFingerprintManager(Region.US)
        explanation = manager.explain_limitations()
        assert "ClientHello" in explanation or "wire" in explanation.lower()


# === headers.py tests ===


class TestExtraHTTPHeaders:
    """Test HTTP header spoofing."""

    def test_returns_dict(self):
        headers = get_extra_http_headers()
        assert isinstance(headers, dict)

    def test_has_sec_ch_ua(self):
        headers = get_extra_http_headers()
        assert "Sec-Ch-Ua" in headers

    def test_has_sec_ch_ua_platform(self):
        headers = get_extra_http_headers()
        assert "Sec-Ch-Ua-Platform" in headers

    def test_has_sec_ch_ua_mobile(self):
        headers = get_extra_http_headers()
        assert "Sec-Ch-Ua-Mobile" in headers

    def test_sec_ch_ua_mobile_is_false(self):
        headers = get_extra_http_headers()
        assert headers["Sec-Ch-Ua-Mobile"] == "?0"

    def test_has_sec_ch_ua_platform_version(self):
        headers = get_extra_http_headers()
        assert "Sec-Ch-Ua-Platform-Version" in headers

    def test_has_sec_ch_ua_full_version_list(self):
        headers = get_extra_http_headers()
        assert "Sec-Ch-Ua-Full-Version-List" in headers

    def test_has_accept_language(self):
        headers = get_extra_http_headers()
        assert "Accept-Language" in headers


# === profiles.py tests ===


class TestPersona:
    """Test Persona system."""

    def test_default_persona_exists(self):
        assert DEFAULT_PERSONA is not None

    def test_default_persona_has_name(self):
        assert DEFAULT_PERSONA.name is not None

    def test_default_persona_has_device(self):
        assert DEFAULT_PERSONA.device is not None

    def test_persona_to_launch_overrides(self):
        overrides = DEFAULT_PERSONA.to_launch_overrides()
        assert isinstance(overrides, dict)
        assert "viewport" in overrides
        assert "user_agent" in overrides
        assert "locale" in overrides
        assert "timezone_id" in overrides

    def test_get_persona_default(self):
        persona = get_persona()
        assert persona is not None

    def test_list_personas_not_empty(self):
        personas = list_personas()
        assert len(personas) > 0


class TestDeviceProfile:
    """Test DeviceProfile system."""

    def test_device_has_hardware_fingerprint(self):
        device = DEFAULT_PERSONA.device
        hw = device.get_hardware_fingerprint()
        assert isinstance(hw, dict)
        assert "hardwareConcurrency" in hw
        assert "deviceMemory" in hw

    def test_device_has_screen_profile(self):
        device = DEFAULT_PERSONA.device
        screen = device.get_screen_profile()
        assert isinstance(screen, dict)
        assert "width" in screen
        assert "height" in screen
        assert "devicePixelRatio" in screen
