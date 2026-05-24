"""
Tests for AccountWarmer.
Addresses #137: Account warming and gradual activity ramp-up.
"""

import time
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.account_warming import AccountWarmer, WarmingPhase, DEFAULT_WARMING_SCHEDULE


class TestAccountWarmerBasic:
    """Basic functionality tests."""

    def test_initial_state(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        assert warmer.days_elapsed == 0.0
        assert warmer.progress == 0.0
        assert not warmer.is_warmed()

    def test_start_initializes_state(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start()
        assert warmer._started_at is not None
        assert warmer.days_elapsed >= 0.0

    def test_start_does_not_restart(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start()
        first_start = warmer._started_at
        warmer.start()
        assert warmer._started_at == first_start

    def test_progress_increases_over_time(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start()
        initial_progress = warmer.progress

        # Simulate time passing
        warmer._started_at = time.time() - (86400 * 7)  # 7 days ago
        assert warmer.progress > initial_progress

    def test_is_warmed_when_complete(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start()
        # Simulate past all phases
        total_days = sum(p.days for p in warmer.schedule)
        warmer._started_at = time.time() - (86400 * (total_days + 1))
        assert warmer.is_warmed()
        assert warmer.progress >= 1.0


class TestAccountWarmerPhases:
    """Phase progression tests."""

    def test_starts_at_phase_0(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start()
        assert warmer.phase_index == 0

    def test_phase_progression(self):
        # Custom short schedule for testing
        schedule = [
            WarmingPhase(0, 1, 5, 3, 200, 5, 1, 8.0, 20.0),
            WarmingPhase(1, 1, 10, 5, 500, 10, 2, 5.0, 15.0),
            WarmingPhase(2, 1, 20, 8, 1000, 15, 3, 3.0, 10.0),
        ]
        warmer = AccountWarmer(
            "test_account", data_dir="/tmp/test_warming", schedule=schedule
        )
        warmer.start()

        assert warmer.phase_index == 0

        # After 1 day
        warmer._started_at = time.time() - 86400
        assert warmer.phase_index == 1

        # After 2 days
        warmer._started_at = time.time() - (86400 * 2)
        assert warmer.phase_index == 2

        # After 3 days (past all phases)
        warmer._started_at = time.time() - (86400 * 3)
        assert warmer.phase_index == 2  # Stays at last phase

    def test_current_phase_limits_increase(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start()

        phase0_limits = warmer.get_session_limits()
        # Simulate progression to later phase
        total_days = sum(p.days for p in warmer.schedule)
        warmer._started_at = time.time() - (86400 * total_days)
        phase_final_limits = warmer.get_session_limits()

        # Later phases should have higher limits
        assert phase_final_limits["max_actions"] >= phase0_limits["max_actions"]
        assert phase_final_limits["max_pages"] >= phase0_limits["max_pages"]


class TestAccountWarmerSessions:
    """Session management tests."""

    def test_start_session_initializes(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start_session()
        assert warmer._session_start is not None
        assert warmer._session_actions == 0
        assert warmer._session_pages == 0

    def test_record_action_increments(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start_session()
        warmer.record_action()
        warmer.record_action()
        assert warmer._session_actions == 2

    def test_record_page_visit_tracks_domains(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start_session()
        warmer.record_page_visit("https://example.com/page1")
        warmer.record_page_visit("https://example.com/page2")
        warmer.record_page_visit("https://google.com")
        assert warmer._session_pages == 3
        assert len(warmer._session_domains) == 2

    def test_record_scroll_tracks_max(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start_session()
        warmer.record_scroll(100)
        warmer.record_scroll(500)
        warmer.record_scroll(300)
        assert warmer._max_scroll_this_session == 500

    def test_end_session_saves_state(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start_session()
        warmer.record_action()
        warmer.record_action()
        warmer.end_session()
        assert warmer._session_start is None
        assert warmer._total_actions == 2


class TestAccountWarmerLimits:
    """Session limit enforcement tests."""

    def test_should_stop_session_when_not_started(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        assert not warmer.should_stop_session()

    def test_should_stop_session_when_time_exceeded(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start_session()
        # Simulate long session
        warmer._session_start = time.time() - (60 * 10)  # 10 minutes ago
        # Phase 0 has max_session_minutes=5
        assert warmer.should_stop_session()

    def test_should_stop_session_when_actions_exceeded(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start_session()
        # Phase 0 has max_actions=5
        for _ in range(6):
            warmer.record_action()
        assert warmer.should_stop_session()

    def test_should_stop_session_when_pages_exceeded(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start_session()
        # Phase 0 has max_pages=3
        for i in range(4):
            warmer.record_page_visit(f"https://example.com/{i}")
        assert warmer.should_stop_session()

    def test_get_reason_to_stop(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start_session()
        assert warmer.get_reason_to_stop() is None

        # Exceed action limit
        for _ in range(6):
            warmer.record_action()
        reason = warmer.get_reason_to_stop()
        assert reason is not None
        assert "Action limit" in reason


class TestAccountWarmerPersistence:
    """State persistence tests."""

    def test_save_and_load_state(self, tmp_path):
        warmer = AccountWarmer("test_account", data_dir=str(tmp_path))
        warmer.start()
        warmer.start_session()
        warmer.record_action()
        warmer.record_action()
        warmer.end_session()

        # Create new instance and load
        warmer2 = AccountWarmer("test_account", data_dir=str(tmp_path))
        warmer2._load_state()
        assert warmer2._total_sessions == 1
        assert warmer2._total_actions == 2

    def test_state_file_created(self, tmp_path):
        warmer = AccountWarmer("test_account", data_dir=str(tmp_path))
        warmer.start()
        state_file = tmp_path / "test_account.json"
        assert state_file.exists()

        with open(state_file) as f:
            state = json.load(f)
        assert state["account_id"] == "test_account"


class TestAccountWarmerStatus:
    """Status reporting tests."""

    def test_get_status_contains_required_fields(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start()
        status = warmer.get_status()

        assert "account_id" in status
        assert "started_at" in status
        assert "days_elapsed" in status
        assert "current_phase" in status
        assert "progress" in status
        assert "is_warmed" in status
        assert "total_sessions" in status
        assert "total_actions" in status
        assert "session_limits" in status

    def test_reset_clears_state(self):
        warmer = AccountWarmer("test_account", data_dir="/tmp/test_warming")
        warmer.start()
        warmer.start_session()
        warmer.record_action()
        warmer.end_session()

        warmer.reset()
        assert warmer._started_at is None
        assert warmer._total_sessions == 0
        assert warmer._total_actions == 0


class TestAccountWarmerDefaultSchedule:
    """Default schedule validation."""

    def test_schedule_has_multiple_phases(self):
        assert len(DEFAULT_WARMING_SCHEDULE) >= 3

    def test_schedule_limits_increase(self):
        for i in range(len(DEFAULT_WARMING_SCHEDULE) - 1):
            current = DEFAULT_WARMING_SCHEDULE[i]
            next_phase = DEFAULT_WARMING_SCHEDULE[i + 1]
            assert next_phase.max_actions >= current.max_actions
            assert next_phase.max_pages >= current.max_pages

    def test_schedule_delays_decrease(self):
        for i in range(len(DEFAULT_WARMING_SCHEDULE) - 1):
            current = DEFAULT_WARMING_SCHEDULE[i]
            next_phase = DEFAULT_WARMING_SCHEDULE[i + 1]
            assert next_phase.action_delay_min <= current.action_delay_min
            assert next_phase.action_delay_max <= current.action_delay_max
