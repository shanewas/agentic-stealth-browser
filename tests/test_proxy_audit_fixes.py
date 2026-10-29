"""
Audit-fix tests for ProxyManager (Findings 2, 9, 10, 11, 12, 13, 28, 29).

Mirrors the style of tests/test_proxy_manager.py and
tests/test_proxy_config_unit.py: pure logic, no browser, no network.
"""

import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from proxy.proxy_manager import ProxyManager, ProxyConfig


def _non_decodo_config(**overrides):
    cfg = ProxyConfig(
        provider="oxylabs",
        host="pr.oxylabs.io",
        port=7777,
        username="customer-user-session-oldsess",
        password="p@ss:wo/rd",
        country="us",
        session_name="oldsess",
        tier="residential",
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


class TestRotationPreservesProvider:
    """Finding 2: rotation must not rewrite other providers as Decodo."""

    def test_rotate_non_decodo_preserves_provider_endpoint_password(self):
        manager = ProxyManager()
        manager.current_config = _non_decodo_config()

        new_config = manager.rotate_proxy(reason="test")

        assert new_config is not None
        assert new_config.provider == "oxylabs"
        assert new_config.host == "pr.oxylabs.io"
        assert new_config.port == 7777
        assert new_config.password == "p@ss:wo/rd"
        assert new_config.country == "us"
        # Session changed, in both the recorded name and the username.
        assert new_config.session_name != "oldsess"
        assert "oldsess" not in new_config.username
        assert new_config.session_name in new_config.username

    def test_rotate_custom_provider_preserves_provider(self):
        manager = ProxyManager()
        manager.current_config = _non_decodo_config(
            provider="selfhosted", host="proxy.internal", port=1080
        )

        new_config = manager.rotate_proxy()

        assert new_config.provider == "selfhosted"
        assert new_config.host == "proxy.internal"
        assert new_config.port == 1080

    def test_rotate_decodo_still_produces_decodo(self):
        manager = ProxyManager()
        manager.create_decodo_config(
            user="testuser", password="testpass", country="us", session_name="orig"
        )

        new_config = manager.rotate_proxy()

        assert new_config.provider == "decodo"
        assert new_config.host == "gate.decodo.com"
        assert new_config.session_name != "orig"
        assert new_config.password == "testpass"


class TestTierEndpoints:
    """Finding 9: tier selection must change the actual endpoint."""

    def test_endpoints_differ_per_tier(self):
        manager = ProxyManager()
        endpoints = {}
        for tier in ("residential", "datacenter", "mobile", "isp"):
            cfg = manager.create_decodo_config(
                user="u", password="p", country="us", tier=tier
            )
            endpoints[tier] = (cfg.host, cfg.port)
            # Recorded config matches the endpoint in use.
            assert manager.current_config.host == cfg.host
            assert manager.current_config.port == cfg.port
            args = manager.get_playwright_proxy_args()
            assert f"{cfg.host}:{cfg.port}" in args["server"]

        assert endpoints["residential"] == ("gate.decodo.com", 10001)
        assert len(set(endpoints.values())) == 4

    def test_select_tier_changes_endpoint(self):
        manager = ProxyManager()
        cfg = manager.create_decodo_config(
            user="u", password="p", country="us", tier="residential"
        )
        assert (cfg.host, cfg.port) == ("gate.decodo.com", 10001)

        tiered = manager.select_tier("datacenter")

        assert tiered.tier == "datacenter"
        assert (tiered.host, tiered.port) == ProxyManager.get_tier_endpoint(
            "datacenter"
        )
        assert (tiered.host, tiered.port) != ("gate.decodo.com", 10001)
        args = manager.get_playwright_proxy_args()
        assert f"{tiered.host}:{tiered.port}" in args["server"]


class TestHealthCheckUrlQuoting:
    """Finding 10: credential-bearing URLs must be URL-quoted."""

    def test_special_chars_in_password_round_trip(self):
        manager = ProxyManager()
        cfg = _non_decodo_config()
        manager.current_config = cfg

        url = manager.get_proxy_url()
        parsed = urlparse(url)

        assert parsed.hostname == "pr.oxylabs.io"
        assert parsed.port == 7777
        assert unquote(parsed.username) == cfg.username
        assert unquote(parsed.password) == "p@ss:wo/rd"
        assert manager.proxy_url == url

    def test_build_proxy_url_static(self):
        cfg = _non_decodo_config(username="user@name", password="a:b/c@d")
        parsed = urlparse(ProxyManager.build_proxy_url(cfg))
        assert parsed.hostname == cfg.host
        assert parsed.port == cfg.port
        assert unquote(parsed.username) == "user@name"
        assert unquote(parsed.password) == "a:b/c@d"


class TestHttpxRuntimeDependency:
    """Finding 11: the health-check import must not need dev extras."""

    def test_proxy_manager_imports_with_runtime_httpx(self):
        import httpx
        import proxy.proxy_manager as proxy_module

        assert proxy_module.httpx is httpx

    def test_httpx_declared_as_runtime_dependency(self):
        text = (PROJECT_ROOT / "pyproject.toml").read_text()
        try:
            import tomllib

            data = tomllib.loads(text)
            deps = data["project"]["dependencies"]
            assert any(d.startswith("httpx") for d in deps)
        except ModuleNotFoundError:  # Python 3.10 fallback
            runtime_section = text.split("[project.optional-dependencies]")[0]
            assert "httpx" in runtime_section


class TestPerSessionConfigs:
    """Finding 12: concurrent sessions hold distinct configs."""

    def test_two_sessions_hold_distinct_configs(self):
        manager = ProxyManager()
        cfg_a = manager.create_decodo_config(
            user="ua", password="pa", country="us", session_name="sess-a"
        )
        cfg_b = manager.create_decodo_config(
            user="ub", password="pb", country="jp", session_name="sess-b"
        )

        assert manager.get_config("sess-a") is cfg_a
        assert manager.get_proxy_config("sess-b") is cfg_b
        # Backward-compatible current accessor = most recent.
        assert manager.current_config is cfg_b
        args_a = manager.get_playwright_proxy_args(session_name="sess-a")
        assert args_a["password"] == "pa"

    def test_rotating_one_session_does_not_change_other(self):
        manager = ProxyManager()
        manager.create_decodo_config(
            user="ua", password="pa", country="us", session_name="sess-a"
        )
        cfg_b = manager.create_decodo_config(
            user="ub", password="pb", country="jp", session_name="sess-b"
        )

        rotated = manager.rotate_proxy(session_name="sess-a")

        assert rotated is not None
        assert rotated.session_name != "sess-a"
        assert manager.get_config("sess-b") is cfg_b
        assert manager.get_config("sess-b").session_name == "sess-b"
        assert manager.get_config(rotated.session_name) is rotated

    def test_rotate_unknown_session_returns_none(self):
        manager = ProxyManager()
        manager.create_decodo_config(
            user="ua", password="pa", country="us", session_name="sess-a"
        )
        assert manager.rotate_proxy(session_name="nope") is None
        assert manager.current_config.session_name == "sess-a"


class TestSafeExtractBaseUser:
    """Finding 13: hyphenated bases survive generated-grammar parsing."""

    def test_hyphenated_base_before_country(self):
        manager = ProxyManager()
        assert (
            manager._safe_extract_base_user(
                "user-mary-ann-smith-country-us-session-abc-sessionduration-30"
            )
            == "mary-ann-smith"
        )

    def test_hyphenated_base_before_session(self):
        manager = ProxyManager()
        assert (
            manager._safe_extract_base_user("user-mary-ann-session-abc")
            == "mary-ann"
        )
        assert (
            manager._safe_extract_base_user("user-anne-marie-sessionduration-30")
            == "anne-marie"
        )

    def test_fallback_preserved_outside_grammar(self):
        manager = ProxyManager()
        assert manager._safe_extract_base_user("user-foo-bar-baz") == "foo"
        assert manager._safe_extract_base_user("user-justuser") == "justuser"
        assert manager._safe_extract_base_user("something-else") == "default"
        assert manager._safe_extract_base_user("") == "default"
        assert manager._safe_extract_base_user(None) == "default"


class TestUnnamedProxyHealth:
    """Finding 28: unnamed configs get independent health buckets."""

    def test_two_unnamed_configs_keep_independent_failures(self):
        manager = ProxyManager()
        cfg_a = _non_decodo_config(session_name=None, username="user-a")
        cfg_b = _non_decodo_config(session_name=None, username="user-b")

        for _ in range(3):
            manager.record_proxy_result(cfg_a, success=False)
        manager.record_proxy_result(cfg_b, success=True)

        assert manager.should_rotate_proxy(cfg_a, threshold=3) is True
        assert manager.should_rotate_proxy(cfg_b, threshold=3) is False
        assert manager.get_proxy_health(cfg_a)["failed_requests"] == 3
        assert manager.get_proxy_health(cfg_b)["failed_requests"] == 0
        # Generated identities are stored on the configs and distinct.
        assert cfg_a.proxy_id
        assert cfg_b.proxy_id
        assert cfg_a.proxy_id != cfg_b.proxy_id
        assert manager.health_key_for(cfg_a) == cfg_a.proxy_id

    def test_named_config_health_unchanged(self):
        manager = ProxyManager()
        cfg = _non_decodo_config(session_name=None, username="user-a")
        cfg.name = "named-proxy"
        manager.record_proxy_result(cfg, success=False)
        assert manager.health_key_for(cfg) == "named-proxy"
        assert manager.get_proxy_health("named-proxy")["failed_requests"] == 1


class TestSiteSensitivityHostMatching:
    """Finding 29: exact host or dot-boundary suffix matching only."""

    def test_lookalike_hosts_do_not_match(self):
        manager = ProxyManager()
        assert manager.get_site_sensitivity("notgithub.com") == "medium"
        assert manager.get_site_sensitivity("github.com.evil.example") == "medium"
        assert manager.get_site_sensitivity("evil-linkedin.com") == "medium"

    def test_exact_and_legitimate_subdomain_match(self):
        manager = ProxyManager()
        assert manager.get_site_sensitivity("github.com") == "low"
        assert manager.get_site_sensitivity("www.github.com") == "low"
        assert manager.get_site_sensitivity("api.linkedin.com") == "high"
        assert manager.get_site_sensitivity("https://github.com/org/repo") == "low"
