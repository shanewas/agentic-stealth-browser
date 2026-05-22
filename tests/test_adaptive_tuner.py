"""
Tests for adaptive/ML behavior tuning.
Addresses #71: Adaptive/ML-driven behavior tuning.
"""

import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from behavior.adaptive_tuner import BehaviorTuner


class TestBehaviorTunerBasic:
    """Basic functionality tests."""

    def test_initial_state(self):
        tuner = BehaviorTuner()
        assert tuner.get_success_rate() == 1.0
        assert len(tuner._feedback_history) == 0

    def test_record_feedback_successful(self):
        tuner = BehaviorTuner()
        tuner.record_feedback(blocked=False, behavior_params={"typing_speed": 0.4})
        assert len(tuner._feedback_history) == 1
        assert len(tuner._successful_params) == 1

    def test_record_feedback_blocked(self):
        tuner = BehaviorTuner()
        tuner.record_feedback(blocked=True, block_type="captcha")
        assert len(tuner._failed_params) == 1

    def test_get_optimized_params_without_data(self):
        tuner = BehaviorTuner()
        params = tuner.get_optimized_params()
        assert params == tuner._current_params


class TestBehaviorTunerOptimization:
    """Optimization tests."""

    def test_auto_tune_after_enough_data(self):
        tuner = BehaviorTuner()
        # Record successful sessions with low typing speed
        for _ in range(5):
            tuner.record_feedback(
                blocked=False,
                behavior_params={"typing_speed": 0.3, "mouse_precision": 0.7}
            )
        # Record failed sessions with high typing speed
        for _ in range(3):
            tuner.record_feedback(
                blocked=True,
                behavior_params={"typing_speed": 0.9, "mouse_precision": 0.2}
            )

        optimized = tuner.get_optimized_params()
        # Optimized typing speed should be closer to successful (0.3) than failed (0.9)
        assert optimized["typing_speed"] < 0.6

    def test_success_rate_calculation(self):
        tuner = BehaviorTuner()
        for _ in range(7):
            tuner.record_feedback(blocked=False)
        for _ in range(3):
            tuner.record_feedback(blocked=True)

        assert tuner.get_success_rate() == 0.7

    def test_platform_success_rates(self):
        tuner = BehaviorTuner()
        tuner.record_feedback(blocked=False, platform="linkedin")
        tuner.record_feedback(blocked=False, platform="linkedin")
        tuner.record_feedback(blocked=True, platform="linkedin")
        tuner.record_feedback(blocked=False, platform="amazon")

        rates = tuner.get_platform_success_rates()
        assert rates["linkedin"] == pytest.approx(2/3)
        assert rates["amazon"] == 1.0

    def test_block_type_distribution(self):
        tuner = BehaviorTuner()
        tuner.record_feedback(blocked=True, block_type="captcha")
        tuner.record_feedback(blocked=True, block_type="captcha")
        tuner.record_feedback(blocked=True, block_type="rate_limit")

        dist = tuner.get_block_type_distribution()
        assert dist["captcha"] == 2
        assert dist["rate_limit"] == 1


class TestBehaviorTunerStatus:
    """Status reporting tests."""

    def test_get_status_contains_required_fields(self):
        tuner = BehaviorTuner()
        tuner.record_feedback(blocked=False)
        status = tuner.get_status()

        assert "total_sessions" in status
        assert "success_rate" in status
        assert "current_params" in status
        assert "optimized_params" in status

    def test_reset_clears_all_data(self):
        tuner = BehaviorTuner()
        tuner.record_feedback(blocked=False)
        tuner.record_feedback(blocked=True)
        tuner.reset()

        assert len(tuner._feedback_history) == 0
        assert len(tuner._successful_params) == 0
        assert len(tuner._failed_params) == 0
