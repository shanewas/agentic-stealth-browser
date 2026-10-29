"""
Regression tests for the stealth/behavior/proxy audit fixes.

Findings covered:
- F8:  TLS launch-arg retrieval must not mutate the shared profile
- F19: DeviceProfile validation and explicit-hardware precedence
- F20: Persona / nested dicts must not be shared mutable singletons
- F21: Unknown persona/preset names must not silently resolve
- F22: stealth.presets must re-export the canonical stealth.profiles types
- F31: JA4 generation must reject empty/unsupported tokens
- F32: Cache helpers must not crash with TypeError when generator is omitted
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stealth.cache import (
    StealthCache,
    clear_all_caches,
    get_cached_profile,
    get_cached_script,
)
from stealth.profiles import (
    PERSONAS,
    DeviceProfile,
    Persona,
    get_persona,
)
from stealth.tls_fingerprint import Region, TLSFingerprintManager
from stealth.tls_ja3_ja4 import JA4Fingerprint


class TestTLSLaunchArgsDoNotMutateProfile:
    """Finding 8."""

    def test_two_consecutive_calls_equal_and_profile_unchanged(self):
        manager = TLSFingerprintManager(Region.US)
        before = list(TLSFingerprintManager.PROFILES[Region.US]["recommended_args"])
        args1 = manager.get_launch_args()
        args2 = manager.get_launch_args()
        assert args1 == args2
        assert len(args1) == len(before) + 2
        assert TLSFingerprintManager.PROFILES[Region.US]["recommended_args"] == before

    def test_returned_profile_is_a_copy(self):
        manager = TLSFingerprintManager(Region.US)
        profile = manager.get_profile()
        profile["ciphers"].append("MUTATED")
        profile["recommended_args"].append("--mutated")
        fresh = manager.get_profile()
        assert "MUTATED" not in fresh["ciphers"]
        assert "--mutated" not in fresh["recommended_args"]


class TestDeviceProfileValidation:
    """Finding 19."""

    def test_non_positive_dpr_rejected(self):
        with pytest.raises(ValueError):
            DeviceProfile(screen={**DeviceProfile().screen, "devicePixelRatio": 0})

    def test_viewport_larger_than_screen_rejected(self):
        with pytest.raises(ValueError):
            DeviceProfile(viewport={"width": 5000, "height": 768})

    def test_non_positive_viewport_rejected(self):
        with pytest.raises(ValueError):
            DeviceProfile(viewport={"width": 0, "height": 768})

    def test_avail_larger_than_screen_rejected(self):
        with pytest.raises(ValueError):
            DeviceProfile(screen={**DeviceProfile().screen, "availWidth": 9999})

    def test_unknown_orientation_rejected(self):
        with pytest.raises(ValueError):
            DeviceProfile(screen={**DeviceProfile().screen, "orientation": "diagonal"})

    def test_non_positive_hardware_concurrency_rejected(self):
        with pytest.raises(ValueError):
            DeviceProfile(hardware_concurrency=0)

    def test_non_positive_device_memory_rejected(self):
        with pytest.raises(ValueError):
            DeviceProfile(device_memory=-1)

    def test_unknown_power_level_rejected(self):
        with pytest.raises(ValueError):
            DeviceProfile(power_level="ultra")

    def test_explicit_hardware_wins_over_power_level(self):
        device = DeviceProfile(hardware_concurrency=16, device_memory=32, power_level="low")
        hw = device.get_hardware_fingerprint()
        assert hw == {"hardwareConcurrency": 16, "deviceMemory": 32}

    def test_power_level_mapping_is_default_when_unset(self):
        assert DeviceProfile(power_level="low").get_hardware_fingerprint() == {
            "hardwareConcurrency": 4,
            "deviceMemory": 4,
        }
        assert DeviceProfile().get_hardware_fingerprint() == {
            "hardwareConcurrency": 8,
            "deviceMemory": 8,
        }

    def test_partial_explicit_hardware_mixes_with_mapping(self):
        hw = DeviceProfile(hardware_concurrency=6, power_level="high").get_hardware_fingerprint()
        assert hw == {"hardwareConcurrency": 6, "deviceMemory": 16}

    def test_builtin_registry_profiles_are_valid(self):
        for persona in PERSONAS.values():
            assert isinstance(persona.device, DeviceProfile)
            hw = persona.device.get_hardware_fingerprint()
            assert hw["hardwareConcurrency"] > 0
            assert hw["deviceMemory"] > 0


class TestPersonaDeepCopies:
    """Finding 20."""

    def test_mutating_returned_persona_does_not_affect_fresh_lookup(self):
        persona = get_persona("default")
        persona.name = "mutated"
        persona.device.viewport["width"] = 1
        fresh = get_persona("default")
        assert fresh.name != "mutated"
        assert fresh.device.viewport["width"] != 1

    def test_mutating_launch_overrides_viewport_does_not_affect_fresh_lookup(self):
        persona = get_persona("default")
        overrides = persona.to_launch_overrides()
        overrides["viewport"]["width"] = 1
        fresh_overrides = get_persona("default").to_launch_overrides()
        assert fresh_overrides["viewport"]["width"] != 1

    def test_mutating_screen_profile_does_not_affect_fresh_lookup(self):
        persona = get_persona("default")
        screen = persona.device.get_screen_profile()
        screen["width"] = 1
        assert persona.device.get_screen_profile()["width"] != 1
        assert get_persona("default").device.get_screen_profile()["width"] != 1


class TestStrictPersonaAndPresetLookup:
    """Finding 21."""

    def test_get_persona_empty_raises(self):
        with pytest.raises(ValueError):
            get_persona("")

    def test_get_persona_unknown_raises(self):
        with pytest.raises((KeyError, ValueError)):
            get_persona("us_professiona")

    def test_get_persona_substring_does_not_resolve(self):
        with pytest.raises((KeyError, ValueError)):
            get_persona("us")

    def test_get_persona_exact_alias_still_works(self):
        assert isinstance(get_persona("eu_professional"), Persona)
        assert get_persona("eu_professional").name == "professional_eu_desktop"

    def test_get_preset_empty_raises(self):
        from stealth.presets import get_preset

        with pytest.raises(ValueError):
            get_preset("")

    def test_get_preset_unknown_raises(self):
        from stealth.presets import get_preset

        with pytest.raises((KeyError, ValueError)):
            get_preset("linkedn_2026")

    def test_get_preset_substring_does_not_resolve(self):
        from stealth.presets import get_preset

        with pytest.raises((KeyError, ValueError)):
            get_preset("link")
        with pytest.raises((KeyError, ValueError)):
            get_preset("linkedin_202")

    def test_get_preset_exact_alias_still_works(self):
        from stealth.presets import get_preset

        assert get_preset("linkedin_2026").name == "linkedin_2026"
        assert get_preset("linkedin").name == "linkedin_2026"


class TestPresetsReExportCanonicalProfiles:
    """Finding 22."""

    def test_both_import_paths_expose_same_classes(self):
        from stealth import presets, profiles

        assert presets.DeviceProfile is profiles.DeviceProfile
        assert presets.Persona is profiles.Persona
        assert presets.DEFAULT_PERSONA is profiles.DEFAULT_PERSONA
        assert presets.get_persona is profiles.get_persona
        assert presets.list_personas is profiles.list_personas

    def test_presets_registry_results_match_profiles(self):
        from stealth import presets, profiles

        assert presets.list_personas() == profiles.list_personas()
        assert presets.get_persona("eu_professional") == profiles.get_persona("eu_professional")
        assert "eu_professional" in presets.list_personas()


class TestJA4Validation:
    """Finding 31."""

    def test_empty_alpn_raises_value_error(self):
        with pytest.raises(ValueError):
            JA4Fingerprint.generate_ja4(alpn="")

    def test_empty_protocol_raises_value_error(self):
        with pytest.raises(ValueError):
            JA4Fingerprint.generate_ja4(protocol="")

    def test_empty_tls_version_raises_value_error(self):
        with pytest.raises(ValueError):
            JA4Fingerprint.generate_ja4(tls_version="")

    def test_empty_sni_raises_value_error(self):
        with pytest.raises(ValueError):
            JA4Fingerprint.generate_ja4(sni="")

    def test_unsupported_alpn_raises_value_error(self):
        with pytest.raises(ValueError):
            JA4Fingerprint.generate_ja4(alpn="bogus")

    def test_valid_generation_still_works(self):
        assert JA4Fingerprint.generate_ja4().startswith("q13d")
        assert JA4Fingerprint.generate_ja4(alpn="h3")


class TestCacheMissingGenerator:
    """Finding 32."""

    def setup_method(self):
        clear_all_caches()

    def test_core_getter_uncached_without_generator_raises_value_error(self):
        cache = StealthCache()
        with pytest.raises(ValueError, match="generator"):
            cache.get_or_generate("missing")

    def test_get_cached_script_uncached_without_generator_raises_value_error(self):
        with pytest.raises(ValueError, match="get_cached_script.*generator"):
            get_cached_script("uncached_profile_f32")

    def test_get_cached_profile_uncached_without_generator_raises_value_error(self):
        with pytest.raises(ValueError, match="get_cached_profile.*generator"):
            get_cached_profile("uncached_profile_f32")

    def test_provided_generator_populates_cache(self):
        cache = StealthCache()
        assert cache.get_or_generate("k", lambda: "generated") == "generated"
        assert cache.get_or_generate("k") == "generated"

    def test_cached_key_returns_without_generator(self):
        assert get_cached_script("cached_profile_f32", generator=lambda: "script") == "script"
        assert get_cached_script("cached_profile_f32") == "script"
        assert get_cached_profile("cached_profile_f32", generator=lambda: {"p": 1}) == {"p": 1}
        assert get_cached_profile("cached_profile_f32") == {"p": 1}
