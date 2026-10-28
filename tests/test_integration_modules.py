"""
Integration tests for new module wiring in AgentBrowser.
Tests that AccountHealth, AccountWarmer, ConnectionPool, and AdaptiveTuner
are properly initialized and wired into safe_goto.
"""

import asyncio
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.account_warming import AccountWarmer
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
        assert len(browser.connection_pool._contexts) == 0

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
        browser.connection_pool.get_or_create_context("example.com")
        assert browser.connection_pool.should_reuse("https://example.com/page") is True

    def test_adaptive_tuner_records_feedback(self):
        browser = AgentBrowser(session_name="integration-test")
        browser.adaptive_tuner.record_feedback(blocked=False, platform="test")
        assert browser.adaptive_tuner.get_success_rate() == 1.0
        browser.adaptive_tuner.record_feedback(blocked=True, platform="test")
        assert browser.adaptive_tuner.get_success_rate() == 0.5


class TestWarmingSessionLifecycle:
    """safe_goto must start one warming session per browser lifecycle."""

    def test_navigations_accumulate_and_close_ends_session(self, tmp_path):
        class _Page:
            async def goto(self, url, **kwargs):
                return None

            async def close(self):
                pass

        class _Human:
            async def think(self, *args, **kwargs):
                pass

        class _Recovery:
            async def execute_with_recovery(self, func, **kwargs):
                return await func()

        class _Logger:
            def log_action(self, *args, **kwargs):
                pass

            def log_error(self, *args, **kwargs):
                pass

            def close(self):
                pass

        class _Health:
            is_cooling_off = False

            def record_event(self, *args, **kwargs):
                pass

            def record_success(self):
                pass

            def record_action(self):
                pass

        class _Pool:
            def should_reuse(self, url):
                return False

            def record_navigation(self, url):
                pass

            def release_context(self, domain):
                pass

        class _RateLimiter:
            async def wait_if_needed(self, account, domain):
                return 0

        async def _run():
            browser = AgentBrowser(session_name="warming-lifecycle-test")
            warmer = AccountWarmer("warming-lifecycle-test", data_dir=str(tmp_path))
            warmer.start()
            warmer._started_at = time.time() - 86400  # days_elapsed > 0
            browser.account_warming = warmer
            browser.account_health = _Health()
            browser.connection_pool = _Pool()
            browser.rate_limiter = _RateLimiter()
            browser.browser = object()
            browser.page = _Page()
            browser.human = _Human()
            browser.recovery = _Recovery()
            browser.logger = _Logger()

            assert await browser.safe_goto("https://example.com/a", warm_up=False)
            assert await browser.safe_goto("https://example.com/b", warm_up=False)

            # One session for both navigations; counters accumulate.
            assert warmer.session_active
            assert warmer._total_sessions == 1
            assert warmer._session_pages == 2
            assert warmer._session_actions == 2

            await browser.close()
            assert not warmer.session_active
            assert warmer._session_start is None
            assert warmer._total_actions == 2

        asyncio.run(_run())


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
