"""
Tests for Rotating Behavioral Personas.
Addresses #129: Rotating between multiple behavioral personas per account over time.
"""

import pytest
import time
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from behavior.persona_rotator import (
    PersonaRotator,
    PersonaProfile,
    PersonaTrait,
    PERSONA_TEMPLATES,
)


class TestPersonaTrait:
    """Trait evolution tests."""

    def test_evolve_moves_toward_target(self):
        trait = PersonaTrait(
            name="test",
            current_value=0.2,
            target_value=0.8,
            evolution_rate=0.1,
        )
        trait.evolve(10)  # 10 days
        assert trait.current_value > 0.2

    def test_evolve_respects_bounds(self):
        trait = PersonaTrait(
            name="test",
            current_value=0.5,
            target_value=1.5,  # Above max
            evolution_rate=0.1,
            max_value=1.0,
        )
        trait.evolve(100)
        assert trait.current_value <= 1.0

    def test_is_stable_when_close_to_target(self):
        trait = PersonaTrait(
            name="test",
            current_value=0.5,
            target_value=0.5,
            evolution_rate=0.1,
        )
        assert trait.is_stable()

    def test_is_not_stable_when_far_from_target(self):
        trait = PersonaTrait(
            name="test",
            current_value=0.2,
            target_value=0.8,
            evolution_rate=0.1,
        )
        assert not trait.is_stable()

    def test_no_evolution_with_zero_days(self):
        trait = PersonaTrait(
            name="test",
            current_value=0.5,
            target_value=0.8,
            evolution_rate=0.1,
        )
        initial = trait.current_value
        trait.evolve(0)
        assert trait.current_value == initial


class TestPersonaProfile:
    """Profile serialization tests."""

    def test_to_dict_contains_all_fields(self):
        profile = PersonaProfile(
            name="test",
            typing_speed=0.7,
            scroll_depth=0.6,
            device_type="mobile",
        )
        d = profile.to_dict()
        assert d["name"] == "test"
        assert d["typing_speed"] == 0.7
        assert d["device_type"] == "mobile"

    def test_round_trip(self):
        profile = PersonaProfile(
            name="test",
            typing_speed=0.7,
            scroll_depth=0.6,
            mouse_precision=0.8,
            device_type="laptop",
            timezone="PST",
        )
        restored = PersonaProfile.from_dict(profile.to_dict())
        assert restored.name == profile.name
        assert restored.typing_speed == profile.typing_speed
        assert restored.device_type == profile.device_type
        assert restored.timezone == profile.timezone


class TestPersonaTemplates:
    """Predefined template tests."""

    def test_has_multiple_templates(self):
        assert len(PERSONA_TEMPLATES) >= 3

    def test_templates_have_unique_names(self):
        names = [p.name for p in PERSONA_TEMPLATES.values()]
        assert len(names) == len(set(names))

    def test_casual_user_is_slower(self):
        casual = PERSONA_TEMPLATES["casual_user"]
        power = PERSONA_TEMPLATES["power_user"]
        assert casual.typing_speed < power.typing_speed

    def test_power_user_is_more_precise(self):
        power = PERSONA_TEMPLATES["power_user"]
        casual = PERSONA_TEMPLATES["casual_user"]
        assert power.mouse_precision > casual.mouse_precision


class TestPersonaRotator:
    """Rotator functionality tests."""

    def test_initial_state(self):
        rotator = PersonaRotator("test")
        assert rotator.current_persona is None
        assert rotator.days_active >= 0

    def test_set_current_persona(self):
        rotator = PersonaRotator("test")
        rotator.set_current_persona("casual_user")
        assert rotator.current_persona is not None
        assert rotator.current_persona.name == "casual_user"

    def test_set_custom_persona(self):
        rotator = PersonaRotator("test")
        custom = PersonaProfile(name="custom", typing_speed=0.9)
        rotator.set_custom_persona(custom)
        assert rotator.current_persona.name == "custom"

    def test_get_behavior_params(self):
        rotator = PersonaRotator("test")
        rotator.set_current_persona("casual_user")
        params = rotator.get_behavior_params()

        assert "typing_delay_min" in params
        assert "typing_delay_max" in params
        assert params["persona_name"] == "casual_user"

    def test_behavior_params_vary_by_persona(self):
        rotator = PersonaRotator("test")

        rotator.set_current_persona("casual_user")
        casual_params = rotator.get_behavior_params()

        rotator2 = PersonaRotator("test2")
        rotator2.set_current_persona("power_user")
        power_params = rotator2.get_behavior_params()

        # Power user should have faster typing (lower delay)
        assert power_params["typing_delay_min"] < casual_params["typing_delay_min"]

    def test_transition_progress(self):
        rotator = PersonaRotator("test")
        assert rotator.get_transition_progress() == 0.0
        assert not rotator.is_transitioning()

    def test_transition_to_new_persona(self):
        rotator = PersonaRotator("test")
        rotator.set_current_persona("casual_user")
        rotator.transition_to("power_user", transition_days=14)

        assert rotator.is_transitioning()
        assert rotator.get_transition_progress() >= 0

    def test_evolve_changes_traits(self):
        rotator = PersonaRotator("test")
        rotator.set_current_persona("casual_user")
        rotator.transition_to("power_user", transition_days=14)

        initial_traits = rotator.get_trait_values()
        # Simulate time passing
        rotator._transition_start = time.time() - (86400 * 7)  # 7 days ago
        rotator.evolve(7)

        evolved_traits = rotator.get_trait_values()
        # Traits should have changed
        assert evolved_traits != initial_traits

    def test_get_trait_values(self):
        rotator = PersonaRotator("test")
        rotator.set_current_persona("casual_user")
        traits = rotator.get_trait_values()

        assert "typing_speed" in traits
        assert "scroll_depth" in traits
        assert 0 <= traits["typing_speed"] <= 1

    def test_get_status(self):
        rotator = PersonaRotator("test")
        rotator.set_current_persona("casual_user")
        status = rotator.get_status()

        assert "account_id" in status
        assert "current_persona" in status
        assert "traits" in status
        assert "behavior_params" in status

    def test_default_params_when_no_persona(self):
        rotator = PersonaRotator("test")
        params = rotator.get_behavior_params()
        assert params["persona_name"] == "default"


class TestPersonaRotatorEvolution:
    """Long-term evolution tests."""

    def test_traits_converge_to_target(self):
        rotator = PersonaRotator("test")
        rotator.set_current_persona("casual_user")
        rotator.transition_to("power_user", transition_days=30)

        # Simulate 30 days of evolution
        for _ in range(30):
            rotator.evolve(1)

        # Typing speed should have increased (casual=0.4 -> power=0.8)
        traits = rotator.get_trait_values()
        assert traits["typing_speed"] > 0.4

    def test_behavior_params_change_after_evolution(self):
        rotator = PersonaRotator("test")
        rotator.set_current_persona("casual_user")

        initial_params = rotator.get_behavior_params()

        # Evolve significantly
        for _ in range(50):
            rotator.evolve(1)

        evolved_params = rotator.get_behavior_params()
        # Params should be different (or same if no transition)
        assert evolved_params["days_active"] > initial_params["days_active"]

    def test_evolution_log_grows(self):
        rotator = PersonaRotator("test")
        rotator.set_current_persona("casual_user")

        initial_log_len = len(rotator._evolution_log)
        rotator.evolve(1)
        rotator.evolve(1)

        assert len(rotator._evolution_log) == initial_log_len + 2


class TestPersonaRotatorReproducibility:
    """Reproducibility tests."""

    def test_same_seed_same_results(self):
        rng = random.Random(42)
        rotator1 = PersonaRotator("test", rng=rng)
        rotator1.set_current_persona("casual_user")

        rng2 = random.Random(42)
        rotator2 = PersonaRotator("test", rng=rng2)
        rotator2.set_current_persona("casual_user")

        # Same initial state
        assert rotator1.get_trait_values() == rotator2.get_trait_values()
