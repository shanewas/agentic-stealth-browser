"""
Unit tests for ProxyManager: config validation, site sensitivity, health tracking.

Covers:
- ProxyConfig.validate() for all error types
- ProxyManager.get_site_sensitivity() and tier recommendation
- ProxyManager.record_proxy_result() health tracking
- ProxyManager.should_rotate_proxy()
- ProxyManager.get_current_proxy_info()
- ProxyManager._safe_extract_base_user()
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from proxy.proxy_manager import ProxyManager, ProxyConfig


class TestProxyConfigValidation:
    def test_valid_config(self):
        cfg = ProxyConfig(
            provider="decodo",
            host="gate.decodo.com",
            port=10001,
            username="user",
            password="pass",
            country="jp",
        )
        assert cfg.validate() == []

    def test_invalid_port(self):
        cfg = ProxyConfig(
            provider="decodo",
            host="gate.decodo.com",
            port=99999,
            username="user",
            password="pass",
            country="jp",
        )
        errors = cfg.validate()
        assert any("port" in e for e in errors)

    def test_invalid_port_zero(self):
        cfg = ProxyConfig(
            provider="decodo",
            host="gate.decodo.com",
            port=0,
            username="user",
            password="pass",
            country="jp",
        )
        errors = cfg.validate()
        assert any("port" in e for e in errors)

    def test_invalid_country_length(self):
        cfg = ProxyConfig(
            provider="decodo",
            host="gate.decodo.com",
            port=10001,
            username="user",
            password="pass",
            country="japan",
        )
        errors = cfg.validate()
        assert any("country" in e for e in errors)

    def test_invalid_country_non_alpha(self):
        cfg = ProxyConfig(
            provider="decodo",
            host="gate.decodo.com",
            port=10001,
            username="user",
            password="pass",
            country="12",
        )
        errors = cfg.validate()
        assert any("country" in e for e in errors)

    def test_invalid_provider(self):
        cfg = ProxyConfig(
            provider="badprovider",
            host="gate.decodo.com",
            port=10001,
            username="user",
            password="pass",
            country="jp",
        )
        errors = cfg.validate()
        assert any("provider" in e for e in errors)

    def test_invalid_host_empty(self):
        cfg = ProxyConfig(
            provider="decodo",
            host="",
            port=10001,
            username="user",
            password="pass",
            country="jp",
        )
        errors = cfg.validate()
        assert any("host" in e for e in errors)

    def test_invalid_host_with_spaces(self):
        cfg = ProxyConfig(
            provider="decodo",
            host="host with spaces",
            port=10001,
            username="user",
            password="pass",
            country="jp",
        )
        errors = cfg.validate()
        assert any("host" in e for e in errors)

    def test_invalid_host_with_slash(self):
        cfg = ProxyConfig(
            provider="decodo",
            host="host/with/slash",
            port=10001,
            username="user",
            password="pass",
            country="jp",
        )
        errors = cfg.validate()
        assert any("host" in e for e in errors)

    def test_username_control_chars(self):
        cfg = ProxyConfig(
            provider="decodo",
            host="gate.decodo.com",
            port=10001,
            username="user\nname",
            password="pass",
            country="jp",
        )
        errors = cfg.validate()
        assert any("username" in e for e in errors)

    def test_username_newline(self):
        cfg = ProxyConfig(
            provider="decodo",
            host="gate.decodo.com",
            port=10001,
            username="user\rname",
            password="pass",
            country="jp",
        )
        errors = cfg.validate()
        assert any("username" in e for e in errors)

    def test_password_newline(self):
        cfg = ProxyConfig(
            provider="decodo",
            host="gate.decodo.com",
            port=10001,
            username="user",
            password="pass\nword",
            country="jp",
        )
        errors = cfg.validate()
        assert any("password" in e for e in errors)


class TestSiteSensitivity:
    def test_known_critical_sites(self):
        mgr = ProxyManager()
        assert mgr.get_site_sensitivity("google.com") == "critical"
        assert mgr.get_site_sensitivity("cloudflare.com") == "critical"
        assert mgr.get_site_sensitivity("datadome.co") == "critical"

    def test_known_high_sites(self):
        mgr = ProxyManager()
        assert mgr.get_site_sensitivity("linkedin.com") == "high"
        assert mgr.get_site_sensitivity("amazon.com") == "high"
        assert mgr.get_site_sensitivity("upwork.com") == "high"

    def test_known_medium_sites(self):
        mgr = ProxyManager()
        assert mgr.get_site_sensitivity("reddit.com") == "medium"
        assert mgr.get_site_sensitivity("twitter.com") == "medium"
        assert mgr.get_site_sensitivity("facebook.com") == "medium"

    def test_known_low_sites(self):
        mgr = ProxyManager()
        assert mgr.get_site_sensitivity("example.com") == "low"
        assert mgr.get_site_sensitivity("wikipedia.org") == "low"
        assert mgr.get_site_sensitivity("github.com") == "low"

    def test_unknown_defaults_to_medium(self):
        mgr = ProxyManager()
        assert mgr.get_site_sensitivity("totally-unknown-site.com") == "medium"

    def test_sensitivity_cache(self):
        mgr = ProxyManager()
        mgr.get_site_sensitivity("google.com")
        assert "google.com" in mgr._site_sensitivity_cache

    def test_subdomain_matches(self):
        mgr = ProxyManager()
        assert mgr.get_site_sensitivity("sub.linkedin.com") == "high"
        assert mgr.get_site_sensitivity("www.amazon.com") == "high"


class TestTierRecommendation:
    def test_critical_gets_mobile(self):
        mgr = ProxyManager()
        assert mgr.get_recommended_tier("google.com") == "mobile"

    def test_high_gets_residential(self):
        mgr = ProxyManager()
        assert mgr.get_recommended_tier("linkedin.com") == "residential"

    def test_medium_gets_residential(self):
        mgr = ProxyManager()
        assert mgr.get_recommended_tier("reddit.com") == "residential"

    def test_low_gets_datacenter(self):
        mgr = ProxyManager()
        assert mgr.get_recommended_tier("example.com") == "datacenter"


class TestProxyHealthTracking:
    def test_initial_health_unknown(self):
        mgr = ProxyManager()
        health = mgr.get_proxy_health("nonexistent")
        assert health == {"status": "unknown"}

    def test_record_success(self):
        mgr = ProxyManager()
        mgr.record_proxy_result("sess1", success=True, response_time=0.5)
        health = mgr.get_proxy_health("sess1")
        assert health["total_requests"] == 1
        assert health["successful_requests"] == 1
        assert health["consecutive_failures"] == 0

    def test_record_failure(self):
        mgr = ProxyManager()
        mgr.record_proxy_result("sess1", success=False)
        health = mgr.get_proxy_health("sess1")
        assert health["failed_requests"] == 1
        assert health["consecutive_failures"] == 1

    def test_consecutive_failures_accumulate(self):
        mgr = ProxyManager()
        for _ in range(5):
            mgr.record_proxy_result("sess1", success=False)
        health = mgr.get_proxy_health("sess1")
        assert health["consecutive_failures"] == 5

    def test_success_resets_consecutive_failures(self):
        mgr = ProxyManager()
        mgr.record_proxy_result("sess1", success=False)
        mgr.record_proxy_result("sess1", success=False)
        mgr.record_proxy_result("sess1", success=True)
        health = mgr.get_proxy_health("sess1")
        assert health["consecutive_failures"] == 0

    def test_should_rotate_proxy_below_threshold(self):
        mgr = ProxyManager()
        mgr.record_proxy_result("sess1", success=False)
        mgr.record_proxy_result("sess1", success=False)
        assert mgr.should_rotate_proxy("sess1", threshold=3) is False

    def test_should_rotate_proxy_at_threshold(self):
        mgr = ProxyManager()
        for _ in range(3):
            mgr.record_proxy_result("sess1", success=False)
        assert mgr.should_rotate_proxy("sess1", threshold=3) is True

    def test_should_rotate_proxy_no_session(self):
        mgr = ProxyManager()
        assert mgr.should_rotate_proxy("unknown", threshold=1) is False

    def test_proxy_health_summary(self):
        mgr = ProxyManager()
        mgr.record_proxy_result("sess1", success=True, response_time=0.1)
        mgr.record_proxy_result("sess1", success=False, response_time=0.5)
        summary = mgr.get_proxy_health()
        assert "sess1" in summary
        assert summary["sess1"]["total_requests"] == 2
        assert summary["sess1"]["success_rate_pct"] == 50.0


class TestSafeExtractBaseUser:
    def test_standard_format(self):
        mgr = ProxyManager()
        assert mgr._safe_extract_base_user("user-realuser-country-us-session-abc") == "realuser"

    def test_empty_string(self):
        mgr = ProxyManager()
        assert mgr._safe_extract_base_user("") == "default"

    def test_none_input(self):
        mgr = ProxyManager()
        assert mgr._safe_extract_base_user(None) == "default"

    def test_non_standard_format(self):
        mgr = ProxyManager()
        assert mgr._safe_extract_base_user("something-else") == "default"

    def test_user_prefix_only(self):
        mgr = ProxyManager()
        assert mgr._safe_extract_base_user("user-justuser") == "justuser"


class TestProxyInfo:
    def test_no_config(self):
        mgr = ProxyManager()
        info = mgr.get_current_proxy_info()
        assert info["configured"] is False

    def test_with_config(self):
        mgr = ProxyManager()
        mgr.create_decodo_config(
            user="testuser",
            password="testpass",
            country="gb",
            session_name="my-session",
            tier="mobile",
        )
        info = mgr.get_current_proxy_info()
        assert info["configured"] is True
        assert info["provider"] == "decodo"
        assert info["country"] == "gb"
        assert info["tier"] == "mobile"
        assert info["session_name"] == "my-session"
