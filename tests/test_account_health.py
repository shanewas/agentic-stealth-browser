"""
Tests for AccountHealth scoring and cooling off.
Addresses #154: Account health scoring + automatic cooling off.
"""

import time
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.account_health import AccountHealth, RiskLevel, RiskEvent


class TestAccountHealthBasic:
    """Basic functionality tests."""

    def test_initial_state_is_healthy(self):
        health = AccountHealth("test_account")
        assert health.score == 1.0
        assert health.risk_level == RiskLevel.LOW
        assert not health.is_cooling_off

    def test_record_event_decreases_score(self):
        health = AccountHealth("test_account")
        health.record_event("rate_limit_hit")
        assert health.score < 1.0

    def test_record_action_increases_total(self):
        health = AccountHealth("test_account")
        initial = health._state.total_actions
        health.record_action()
        assert health._state.total_actions == initial + 1

    def test_record_success_improves_score(self):
        health = AccountHealth("test_account")
        health.record_event("rate_limit_hit")
        score_before = health.score
        health.record_success(10)
        assert health.score >= score_before

    def test_risk_level_transitions(self):
        health = AccountHealth("test_account")
        assert health.risk_level == RiskLevel.LOW

        # Add events to degrade health
        for _ in range(5):
            health.record_event("block_detected")

        assert health.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_reset_restores_health(self):
        health = AccountHealth("test_account")
        health.record_event("block_detected")
        health.record_event("captcha_detected")
        assert health.score < 1.0

        health.reset()
        assert health.score == 1.0
        assert health.risk_level == RiskLevel.LOW


class TestAccountHealthCoolingOff:
    """Cooling off period tests."""

    def test_cooling_off_triggered_by_low_score(self):
        health = AccountHealth("test_account")
        # Multiple severe events should trigger cooling off
        for _ in range(8):
            health.record_event("block_detected")

        assert health.should_cool_off()

    def test_cooling_off_duration_increases_with_count(self):
        health = AccountHealth("test_account")
        first_duration = health.cooling_off_duration()

        health._cooling_off_count = 3
        health._state.score = 0.3
        third_duration = health.cooling_off_duration()

        # Duration should be longer for lower scores
        assert third_duration >= first_duration

    def test_cooling_off_remaining_when_not_cooling(self):
        health = AccountHealth("test_account")
        assert health.cooling_off_remaining == 0.0

    def test_start_cooling_off_sets_state(self):
        health = AccountHealth("test_account")
        health.start_cooling_off()
        assert health.is_cooling_off
        assert health.cooling_off_remaining > 0

    def test_recommended_delay_increases_with_risk(self):
        health = AccountHealth("test_account")
        healthy_delay = health.get_recommended_delay()
        assert healthy_delay == 0.0

        # Add events to degrade health
        for _ in range(3):
            health.record_event("block_detected")
        medium_delay = health.get_recommended_delay()
        assert medium_delay >= healthy_delay

        # More events for critical state
        for _ in range(10):
            health.record_event("block_detected")
        critical_delay = health.get_recommended_delay()
        assert critical_delay >= medium_delay


class TestAccountHealthEvents:
    """Risk event tests."""

    def test_known_event_severities(self):
        health = AccountHealth("test_account")
        health.record_event("rate_limit_hit")
        health.record_event("captcha_detected")
        health.record_event("block_detected")

        events = health.get_events()
        assert len(events) == 3

    def test_custom_event_severity(self):
        health = AccountHealth("test_account")
        health.record_event("custom_event", severity=0.75)
        events = health.get_events()
        assert events[0].severity == 0.75

    def test_events_decay_over_time(self):
        health = AccountHealth("test_account")
        health.record_event("rate_limit_hit")
        score_after = health.score

        # Simulate time passing by modifying event timestamp
        for event in health._events:
            event.timestamp = time.time() - (48 * 3600)  # 48 hours ago

        health._recalculate()
        assert health.score > score_after  # Score should recover

    def test_get_events_filters_by_hours(self):
        health = AccountHealth("test_account")
        health.record_event("recent_event")

        # Add old event
        old_event = RiskEvent(
            event_type="old_event",
            severity=0.5,
            timestamp=time.time() - (48 * 3600),
        )
        health._events.append(old_event)

        recent = health.get_events(hours=24)
        assert len(recent) == 1
        assert recent[0].event_type == "recent_event"


class TestAccountHealthSerialization:
    """Checkpoint/restore tests."""

    def test_to_dict_contains_required_fields(self):
        health = AccountHealth("test_account")
        health.record_event("rate_limit_hit")
        data = health.to_dict()

        assert "account_id" in data
        assert "score" in data
        assert "risk_level" in data
        assert "events" in data

    def test_from_dict_restores_state(self):
        health = AccountHealth("test_account")
        health.record_event("block_detected")
        health.record_event("captcha_detected")
        data = health.to_dict()

        restored = AccountHealth.from_dict(data)
        assert restored.account_id == health.account_id
        assert len(restored._events) == len(health._events)

    def test_round_trip_preserves_events(self):
        health = AccountHealth("test_account")
        for event_type in ["rate_limit_hit", "block_detected", "captcha_detected"]:
            health.record_event(event_type)

        data = health.to_dict()
        restored = AccountHealth.from_dict(data)

        restored_events = [e.event_type for e in restored._events]
        original_events = [e.event_type for e in health._events]
        assert restored_events == original_events


class TestAccountHealthProperties:
    """Property-based invariants."""

    def test_score_never_below_minimum(self):
        health = AccountHealth("test_account")
        for _ in range(100):
            health.record_event("block_detected")
        assert health.score >= health.MINIMUM_SCORE

    def test_score_never_above_one(self):
        health = AccountHealth("test_account")
        health.record_success(1000)
        assert health.score <= 1.0

    def test_cooling_off_count_never_decreases(self):
        health = AccountHealth("test_account")
        initial_count = health._cooling_off_count
        health.start_cooling_off()
        assert health._cooling_off_count > initial_count

    def test_risk_level_consistent_with_score(self):
        health = AccountHealth("test_account")
        # Test by adding events to reach different risk levels
        assert health.risk_level == RiskLevel.LOW

        # Add some events to degrade health
        for _ in range(3):
            health.record_event("rate_limit_hit")
        # Score drops significantly with 3 events
        assert health.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)

        # Add more events to reach CRITICAL
        for _ in range(10):
            health.record_event("block_detected")
        assert health.risk_level == RiskLevel.CRITICAL

    def test_total_actions_monotonic(self):
        health = AccountHealth("test_account")
        for i in range(10):
            health.record_action()
            assert health._state.total_actions == i + 1
