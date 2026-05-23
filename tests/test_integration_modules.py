"""
Integration tests for new module wiring in AgentBrowser.
Tests that AccountHealth, AccountWarmer, NavigationHistory, and AdaptiveTuner
are properly initialized and wired into safe_goto.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.agent_browser import AgentBrowser


class TestModuleInitialization:
    """Test that new modules are properly initialized."""

    def test_account_health_initialized(self):
        browser = AgentBrowser(session_name="integration-test")
        assert browser.account_health is not None
        assert browser.account_health.score == 1.0

    def test_account_warming_initialized(self):
        browser = AgentBrowser(session_name="integration-test")
        assert browser.account_warming is not None
        assert browser.account_warming.days_elapsed == 0.0

    def test_connection_pool_initialized(self):
        browser = AgentBrowser(session_name="integration-test")
        assert browser.connection_pool is not None
        assert len(browser.connection_pool._domains) == 0

    def test_adaptive_tuner_initialized(self):
        browser = AgentBrowser(session_name="integration-test")
        assert browser.adaptive_tuner is not None
        assert browser.adaptive_tuner.get_success_rate() == 1.0


class TestModuleIntegration:
    """Test module integration behavior."""

    def test_account_health_tracks_events(self):
        browser = AgentBrowser(session_name="integration-test")
        browser.account_health.record_event("test_event")
        assert browser.account_health.score < 1.0

    def test_account_warming_tracks_sessions(self):
        browser = AgentBrowser(session_name="integration-test")
        browser.account_warming.start_session()
        browser.account_warming.record_action()
        browser.account_warming.record_page_visit("https://example.com")
        assert browser.account_warming._session_actions == 1
        assert browser.account_warming._session_pages == 1

    def test_connection_pool_tracks_domains(self):
        browser = AgentBrowser(session_name="integration-test")
        browser.connection_pool.record_domain("example.com")
        assert browser.connection_pool.should_reuse("https://example.com/page") is True

    def test_adaptive_tuner_records_feedback(self):
        browser = AgentBrowser(session_name="integration-test")
        browser.adaptive_tuner.record_feedback(blocked=False, platform="test")
        assert browser.adaptive_tuner.get_success_rate() == 1.0
        browser.adaptive_tuner.record_feedback(blocked=True, platform="test")
        assert browser.adaptive_tuner.get_success_rate() == 0.5


class TestModuleStatusReporting:
    """Test status reporting from integrated modules."""

    def test_combined_status_report(self):
        browser = AgentBrowser(session_name="integration-test")

        # Get status from all modules
        health_state = browser.account_health.get_state()
        warming_status = browser.account_warming.get_status()
        pool_stats = browser.connection_pool.get_stats()
        tuner_status = browser.adaptive_tuner.get_status()

        # Verify all status reports contain expected fields
        assert hasattr(health_state, "score")
        assert "is_warmed" in warming_status
        assert "active_contexts" in pool_stats
        assert "success_rate" in tuner_status
