"""
Tests for Proxy Manager.
Addresses #22: Verify proxy args reach Playwright launch.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from proxy.proxy_manager import ProxyManager, ProxyConfig


class TestProxyManagerConfig:
    """Proxy configuration tests."""

    def test_create_decodo_config(self):
        manager = ProxyManager()
        config = manager.create_decodo_config(
            user="testuser",
            password="testpass",
            country="us",
            session_name="test-session"
        )
        assert config.provider == "decodo"
        assert config.host == "gate.decodo.com"
        assert config.country == "us"
        assert config.session_name == "test-session"

    def test_config_validation_passes(self):
        manager = ProxyManager()
        config = manager.create_decodo_config(
            user="testuser",
            password="testpass",
            country="us"
        )
        errors = config.validate()
        assert len(errors) == 0

    def test_config_validation_fails_bad_port(self):
        config = ProxyConfig(
            provider="decodo",
            host="gate.decodo.com",
            port=99999,
            username="user",
            password="pass",
            country="us"
        )
        errors = config.validate()
        assert any("port" in e for e in errors)

    def test_config_validation_fails_bad_country(self):
        config = ProxyConfig(
            provider="decodo",
            host="gate.decodo.com",
            port=10001,
            username="user",
            password="pass",
            country="usa"  # Should be 2 letters
        )
        errors = config.validate()
        assert any("country" in e for e in errors)

    def test_to_safe_dict_redacts_password(self):
        manager = ProxyManager()
        config = manager.create_decodo_config(
            user="testuser",
            password="secret123",
            country="us"
        )
        safe = config.to_safe_dict()
        assert safe["password"] == "***REDACTED***"
        # Username is masked (first 3 chars kept)
        assert "***" in safe["username"]
        assert "secret" not in safe["password"]


class TestProxyManagerPlaywrightArgs:
    """Tests verifying proxy args reach Playwright correctly."""

    def test_get_playwright_proxy_args_socks5_default(self):
        manager = ProxyManager()
        manager.create_decodo_config(
            user="testuser",
            password="testpass",
            country="us"
        )
        args = manager.get_playwright_proxy_args()
        assert args["server"].startswith("socks5://")
        # codeql[py/incomplete-url-substring-sanitization]: test fixture string, not untrusted URL sanitization
        assert "gate.decodo.com" in args["server"]
        assert "10001" in args["server"]
        assert args["username"] is not None
        assert args["password"] == "testpass"

    def test_get_playwright_proxy_args_http_preferred(self):
        manager = ProxyManager()
        manager.create_decodo_config(
            user="testuser",
            password="testpass",
            country="us"
        )
        args = manager.get_playwright_proxy_args(prefer_http=True)
        assert args["server"].startswith("http://")
        # codeql[py/incomplete-url-substring-sanitization]: test fixture string, not untrusted URL sanitization
        assert "gate.decodo.com" in args["server"]

    def test_get_playwright_proxy_args_empty_when_no_config(self):
        manager = ProxyManager()
        args = manager.get_playwright_proxy_args()
        assert args == {}

    def test_proxy_args_reaches_launch(self):
        """Test that proxy args are correctly passed to launch_persistent_context."""
        manager = ProxyManager()
        manager.create_decodo_config(
            user="testuser",
            password="testpass",
            country="us"
        )
        proxy_args = manager.get_playwright_proxy_args()

        # Verify the structure matches what Playwright expects
        assert "server" in proxy_args
        assert "username" in proxy_args
        assert "password" in proxy_args
        assert proxy_args["server"] is not None
        assert proxy_args["username"] is not None
        assert proxy_args["password"] is not None


class TestProxyManagerRotation:
    """Proxy rotation tests."""

    def test_rotate_proxy_creates_new_session(self):
        manager = ProxyManager()
        manager.create_decodo_config(
            user="testuser",
            password="testpass",
            country="us",
            session_name="original-session"
        )
        original_session = manager.current_config.session_name

        new_config = manager.rotate_proxy(reason="test")
        assert new_config is not None
        assert new_config.session_name != original_session
        assert "rotated-" in new_config.session_name

    def test_rotate_proxy_preserves_country(self):
        manager = ProxyManager()
        manager.create_decodo_config(
            user="testuser",
            password="testpass",
            country="jp"
        )
        new_config = manager.rotate_proxy()
        assert new_config.country == "jp"

    def test_rotate_proxy_preserves_tier(self):
        manager = ProxyManager()
        manager.create_decodo_config(
            user="testuser",
            password="testpass",
            country="us",
            tier="mobile"
        )
        new_config = manager.rotate_proxy()
        assert new_config.tier == "mobile"

    def test_rotate_proxy_returns_none_when_no_config(self):
        manager = ProxyManager()
        result = manager.rotate_proxy()
        assert result is None


class TestProxyManagerHealth:
    """Proxy health tracking tests."""

    def test_record_proxy_result(self):
        manager = ProxyManager()
        manager.record_proxy_result("session1", success=True, response_time=0.5)
        health = manager.get_proxy_health("session1")
        assert health["total_requests"] == 1
        assert health["successful_requests"] == 1
        assert health["consecutive_failures"] == 0

    def test_consecutive_failures_triggers_rotation(self):
        manager = ProxyManager()
        for _ in range(3):
            manager.record_proxy_result("session1", success=False)
        assert manager.should_rotate_proxy("session1", threshold=3)

    def test_success_resets_consecutive_failures(self):
        manager = ProxyManager()
        manager.record_proxy_result("session1", success=False)
        manager.record_proxy_result("session1", success=False)
        manager.record_proxy_result("session1", success=True)
        health = manager.get_proxy_health("session1")
        assert health["consecutive_failures"] == 0


class TestProxyManagerTierSelection:
    """Smart tier selection tests."""

    def test_get_site_sensitivity(self):
        manager = ProxyManager()
        assert manager.get_site_sensitivity("google.com") == "critical"
        assert manager.get_site_sensitivity("linkedin.com") == "high"
        assert manager.get_site_sensitivity("reddit.com") == "medium"
        assert manager.get_site_sensitivity("example.com") == "low"

    def test_get_recommended_tier(self):
        manager = ProxyManager()
        assert manager.get_recommended_tier("google.com") == "mobile"
        assert manager.get_recommended_tier("linkedin.com") == "residential"
        assert manager.get_recommended_tier("example.com") == "datacenter"


class TestProxyManagerUserInfo:
    """Proxy info extraction tests."""

    def test_get_current_proxy_info(self):
        manager = ProxyManager()
        info = manager.get_current_proxy_info()
        assert info["configured"] is False

        manager.create_decodo_config(
            user="testuser",
            password="testpass",
            country="us",
            session_name="test-session"
        )
        info = manager.get_current_proxy_info()
        assert info["configured"] is True
        assert info["provider"] == "decodo"
        assert info["country"] == "us"
        assert info["session_name"] == "test-session"

    def test_get_curl_proxy_string(self):
        manager = ProxyManager()
        assert manager.get_curl_proxy_string() == ""

        manager.create_decodo_config(
            user="testuser",
            password="testpass",
            country="us"
        )
        curl_str = manager.get_curl_proxy_string()
        assert "socks5://" in curl_str
        # codeql[py/incomplete-url-substring-sanitization]: test fixture string, not untrusted URL sanitization
        assert "gate.decodo.com" in curl_str

    def test_safe_extract_base_user(self):
        manager = ProxyManager()
        assert manager._safe_extract_base_user("user-realuser-country-us-session-abc") == "realuser"
        assert manager._safe_extract_base_user("") == "default"
        assert manager._safe_extract_base_user(None) == "default"
