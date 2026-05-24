"""
Contract tests for AgentBrowser public API.
Addresses #152: Add contract tests that assert the public API of AgentBrowser never regresses.

These tests verify:
- All expected public methods exist with correct signatures
- Return types are consistent
- Error handling follows expected patterns
- Async/await contracts are correct
"""

import pytest
import inspect
import asyncio
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.agent_browser import (
    AgentBrowser,
    StealthBrowserError,
    LaunchError,
    RecoveryError,
    BlockDetectedError,
    RateLimitError,
)


class TestAgentBrowserContract:
    """Contract tests for AgentBrowser class."""

    def test_class_exists(self):
        assert AgentBrowser is not None

    def test_constructor_accepts_session_name(self):
        browser = AgentBrowser(session_name="test-contract")
        assert browser is not None

    def test_constructor_accepts_anonymous(self):
        browser = AgentBrowser(anonymous=True)
        assert browser is not None

    def test_constructor_accepts_ephemeral(self):
        browser = AgentBrowser(ephemeral=True)
        assert browser is not None

    def test_constructor_accepts_light_mode(self):
        browser = AgentBrowser(light_mode=True)
        assert browser.light_mode is True

    def test_constructor_accepts_use_pooled_context(self):
        browser = AgentBrowser(use_pooled_context=True)
        assert browser.use_pooled_context is True

    def test_constructor_accepts_persona(self):
        from stealth.profiles import DEFAULT_PERSONA

        browser = AgentBrowser(persona=DEFAULT_PERSONA)
        assert browser.persona is not None

    def test_constructor_accepts_rate_limits(self):
        browser = AgentBrowser(rate_limits={"tool_calls_per_minute": 30})
        assert browser._rate_limiter is not None

    def test_has_launch_method(self):
        assert hasattr(AgentBrowser, "launch")
        assert inspect.iscoroutinefunction(AgentBrowser.launch)

    def test_launch_signature(self):
        sig = inspect.signature(AgentBrowser.launch)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "headless" in params
        assert "slow_mo" in params
        assert "persona" in params
        assert "light_mode" in params
        assert "use_pooled_context" in params
        assert "debug" in params
        assert "preset" in params
        assert "region" in params
        assert "launch_options" in params

    def test_has_close_method(self):
        assert hasattr(AgentBrowser, "close")
        assert inspect.iscoroutinefunction(AgentBrowser.close)

    def test_has_safe_goto_method(self):
        assert hasattr(AgentBrowser, "safe_goto")
        assert inspect.iscoroutinefunction(AgentBrowser.safe_goto)

    def test_safe_goto_signature(self):
        sig = inspect.signature(AgentBrowser.safe_goto)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "url" in params
        assert "warm_up" in params
        assert "platform" in params

    def test_has_goto_method(self):
        assert hasattr(AgentBrowser, "goto")
        assert inspect.iscoroutinefunction(AgentBrowser.goto)

    def test_has_safe_click_method(self):
        assert hasattr(AgentBrowser, "safe_click")
        assert inspect.iscoroutinefunction(AgentBrowser.safe_click)

    def test_has_safe_type_method(self):
        assert hasattr(AgentBrowser, "safe_type")
        assert inspect.iscoroutinefunction(AgentBrowser.safe_type)

    def test_has_load_cookies_from_file_method(self):
        assert hasattr(AgentBrowser, "load_cookies_from_file")
        assert inspect.iscoroutinefunction(AgentBrowser.load_cookies_from_file)

    def test_has_save_cookies_to_file_method(self):
        assert hasattr(AgentBrowser, "save_cookies_to_file")
        assert inspect.iscoroutinefunction(AgentBrowser.save_cookies_to_file)

    def test_has_warm_up_before_work_method(self):
        assert hasattr(AgentBrowser, "warm_up_before_work")
        assert inspect.iscoroutinefunction(AgentBrowser.warm_up_before_work)

    def test_has_ensure_cookies_fresh_method(self):
        assert hasattr(AgentBrowser, "ensure_cookies_fresh")
        assert inspect.iscoroutinefunction(AgentBrowser.ensure_cookies_fresh)

    def test_has_cleanup_compromised_session_method(self):
        assert hasattr(AgentBrowser, "cleanup_compromised_session")
        assert inspect.iscoroutinefunction(AgentBrowser.cleanup_compromised_session)

    def test_has_get_health_status_method(self):
        assert hasattr(AgentBrowser, "get_health_status")
        assert inspect.iscoroutinefunction(AgentBrowser.get_health_status)

    def test_has_debug_report_method(self):
        assert hasattr(AgentBrowser, "debug_report")
        assert inspect.iscoroutinefunction(AgentBrowser.debug_report)

    def test_has_apply_preset_method(self):
        assert hasattr(AgentBrowser, "apply_preset")
        assert inspect.iscoroutinefunction(AgentBrowser.apply_preset)

    def test_has_switch_region_method(self):
        assert hasattr(AgentBrowser, "switch_region")
        assert inspect.iscoroutinefunction(AgentBrowser.switch_region)

    def test_has_get_stealth_score_method(self):
        assert hasattr(AgentBrowser, "get_stealth_score")
        # This is a sync method
        assert not inspect.iscoroutinefunction(AgentBrowser.get_stealth_score)

    def test_has_new_page_method(self):
        assert hasattr(AgentBrowser, "new_page")
        assert inspect.iscoroutinefunction(AgentBrowser.new_page)

    def test_has_get_pages_method(self):
        assert hasattr(AgentBrowser, "get_pages")
        # This is a sync method (returns list of pages)
        assert not inspect.iscoroutinefunction(AgentBrowser.get_pages)

    def test_has_switch_to_page_method(self):
        assert hasattr(AgentBrowser, "switch_to_page")
        assert inspect.iscoroutinefunction(AgentBrowser.switch_to_page)

    def test_has_screenshot_on_error_method(self):
        assert hasattr(AgentBrowser, "screenshot_on_error")
        assert inspect.iscoroutinefunction(AgentBrowser.screenshot_on_error)

    def test_has_safe_goto_with_rate_limit_method(self):
        assert hasattr(AgentBrowser, "safe_goto_with_rate_limit")
        assert inspect.iscoroutinefunction(AgentBrowser.safe_goto_with_rate_limit)

    def test_has_set_rate_limit_method(self):
        assert hasattr(AgentBrowser, "set_rate_limit")

    def test_has_human_scroll_and_read_method(self):
        assert hasattr(AgentBrowser, "human_scroll_and_read")
        assert inspect.iscoroutinefunction(AgentBrowser.human_scroll_and_read)

    def test_has_profile_action_method(self):
        assert hasattr(AgentBrowser, "profile_action")
        assert inspect.iscoroutinefunction(AgentBrowser.profile_action)

    def test_has_page_getter_property(self):
        assert hasattr(AgentBrowser, "page_getter")
        # page_getter is a property (defined with @property decorator)
        assert isinstance(inspect.getattr_static(AgentBrowser, "page_getter"), property)

    def test_async_context_manager_protocol(self):
        """Verify AgentBrowser supports async with."""
        assert hasattr(AgentBrowser, "__aenter__")
        assert hasattr(AgentBrowser, "__aexit__")
        assert inspect.iscoroutinefunction(AgentBrowser.__aenter__)
        assert inspect.iscoroutinefunction(AgentBrowser.__aexit__)

    def test_raises_runtime_error_when_not_launched(self):
        """Verify that methods raise RuntimeError when browser is not launched."""
        browser = AgentBrowser(session_name="test-not-launched")
        with pytest.raises(RuntimeError, match="Browser not launched"):
            asyncio.run(browser.goto("https://example.com"))

    def test_session_manager_initialized(self):
        browser = AgentBrowser(session_name="test-session-mgr")
        assert browser.session_manager is not None

    def test_proxy_manager_initialized(self):
        browser = AgentBrowser(session_name="test-proxy-mgr")
        assert browser.proxy_manager is not None

    def test_rate_limiter_initialized(self):
        browser = AgentBrowser(session_name="test-rate-limiter")
        assert browser.rate_limiter is not None

    def test_metrics_initialized(self):
        browser = AgentBrowser(session_name="test-metrics")
        assert browser.metrics is not None

    def test_persona_default_value(self):
        browser = AgentBrowser(session_name="test-persona")
        assert browser.persona is not None

    def test_light_mode_default_false(self):
        browser = AgentBrowser(session_name="test-light-mode")
        assert browser.light_mode is False

    def test_use_pooled_context_default_false(self):
        browser = AgentBrowser(session_name="test-pooled")
        assert browser.use_pooled_context is False


class TestExceptionHierarchy:
    """Contract tests for exception hierarchy."""

    def test_stealth_browser_error_is_exception(self):
        assert issubclass(StealthBrowserError, Exception)

    def test_launch_error_is_stealth_browser_error(self):
        assert issubclass(LaunchError, StealthBrowserError)

    def test_recovery_error_is_stealth_browser_error(self):
        assert issubclass(RecoveryError, StealthBrowserError)

    def test_block_detected_error_is_stealth_browser_error(self):
        assert issubclass(BlockDetectedError, StealthBrowserError)

    def test_rate_limit_error_is_stealth_browser_error(self):
        assert issubclass(RateLimitError, StealthBrowserError)

    def test_block_detected_error_has_block_type(self):
        err = BlockDetectedError(block_type="captcha", platform="linkedin")
        assert err.block_type == "captcha"
        assert err.platform == "linkedin"

    def test_block_detected_error_message_format(self):
        err = BlockDetectedError(block_type="captcha", platform="linkedin")
        assert "captcha" in str(err)
        assert "linkedin" in str(err)


class TestBrowserPoolContract:
    """Contract tests for _BrowserPool internal class."""

    def test_browser_pool_exists(self):
        from core.agent_browser import _BrowserPool

        assert _BrowserPool is not None

    def test_browser_pool_has_ensure_browser(self):
        from core.agent_browser import _BrowserPool

        assert hasattr(_BrowserPool, "ensure_browser")

    def test_browser_pool_has_create_context(self):
        from core.agent_browser import _BrowserPool

        assert hasattr(_BrowserPool, "create_context")

    def test_browser_pool_has_release_context(self):
        from core.agent_browser import _BrowserPool

        assert hasattr(_BrowserPool, "release_context")

    def test_browser_pool_has_shutdown(self):
        from core.agent_browser import _BrowserPool

        assert hasattr(_BrowserPool, "shutdown")
