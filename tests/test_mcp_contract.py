"""
MCP Contract / Integration Tests (#280)
Validates core components used by stealth-playwright-mcp.
Headless-friendly pure logic + session tests. Uses asyncio.run for compatibility.
Run: python3 -m pytest tests/test_mcp_contract.py -q
or: python3 -c 'import asyncio; from tests.test_mcp_contract import *; asyncio.run(test_xxx())'
"""

import asyncio
import json
import tempfile
from pathlib import Path

from core.agent_browser import AgentBrowser
from proxy.proxy_manager import ProxyManager
from sessions.cookie_manager import CookieManager, SessionOrchestrator
from sessions.session_manager import SessionManager
from production.rate_limiter import domain_limiter, RateLimitConfig


def test_proxy_wiring_and_tier_selection():
    """Proxy integration and tier selection (#119)"""
    pm = ProxyManager()
    cfg = pm.create_decodo_config("testuser", "pass", country="us", tier="residential")
    assert cfg.tier == "residential"
    info = pm.get_current_proxy_info()
    assert info["tier"] == "residential"

    tiered = pm.select_tier("mobile", country="jp")
    assert tiered.tier == "mobile"

    args = pm.get_playwright_proxy_args()
    assert "server" in args and "socks5" in args.get("server", "")


def test_session_orchestrator_mcp_friendly():
    """SessionOrchestrator after duplication cleanup (#134)"""
    main_sm = SessionManager()
    orch = SessionOrchestrator(session_manager=main_sm)
    sess = orch.create_resilient_session("mcp-sess-1")
    assert "mcp-sess-1" in orch.sessions
    assert orch.main_session_manager is main_sm


def test_rate_limiter_mcp_safe_path():
    """Rate limiter usable from MCP paths (#148)"""
    domain_limiter.set_limit("mcp.test", RateLimitConfig(requests_per_minute=100, cooldown_seconds=0))
    # sync check
    assert hasattr(domain_limiter, 'wait_if_needed')


def test_cookie_manager_contract():
    """CookieManager load + health contract"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump([{"name": "t", "value": "1", "domain": ".ex.com", "path": "/", "sameSite": "None"}], f)
        path = f.name

    async def _run():
        cm = CookieManager()
        res = await cm.load_cookies(path)
        assert res["status"] == "success"
        health = await cm.get_cookie_health()
        assert health["total"] > 0
        Path(path).unlink()
    asyncio.run(_run())


def test_agentbrowser_session_and_bundle_contract():
    """MCP persist/resume + distributed bundle (#236 #298) - logic only"""
    async def _run():
        with tempfile.TemporaryDirectory() as tmp:
            bundle_path = str(Path(tmp) / "bundle.json")
            session_name = "mcp-contract-test"

            # Use orchestrator directly for bundle (no browser needed for this contract test)
            main_sm = SessionManager()
            orch = SessionOrchestrator(session_manager=main_sm)
            orch.create_resilient_session(session_name)

            cm = CookieManager()
            cm.cookies = [{"name": "sim", "value": "v", "domain": "ex.com"}]
            orch.cookie_managers[session_name] = cm

            export_res = await orch.export_session_bundle(session_name, bundle_path)
            assert export_res["status"] == "success"
            assert Path(bundle_path).exists()

            import_res = await orch.import_session_bundle(bundle_path, "imported-contract")
            assert import_res["status"] == "success"
    asyncio.run(_run())


def test_tls_profile_selection_contract():
    """Critical testing gap: TLSFingerprintManager region/profile selection shapes (#P2 TLS)"""
    from stealth.tls_fingerprint import get_tls_manager, Region
    mgr = get_tls_manager("us")
    assert mgr.region == Region.US
    prof = mgr.get_profile()
    assert isinstance(prof, dict)
    assert "name" in prof and "ciphers" in prof and "extensions" in prof
    args = mgr.get_launch_args()
    assert isinstance(args, list)
    assert any("disable-blink" in str(a) for a in args)


def test_health_status_contract_shape():
    """Critical testing gap: MCP/CLI health status return shape contract (#281) + preset wiring"""
    async def _run():
        # Use ephemeral anonymous browser (no real net if possible, but launch needs pw)
        b = AgentBrowser(session_name="health-contract-test", anonymous=True, ephemeral=True)
        await b.launch(headless=True, preset="linkedin_2026", region="us", debug=False)
        try:
            health = await b.get_health_status()
            # Contract shape assertions (what MCP and CLI rely on)
            assert isinstance(health, dict)
            assert "status" in health
            assert "launched" in health
            assert "preset" in health
            assert health.get("preset") == "linkedin_2026"
            assert "region" in health
            assert "tls_profile" in health
            assert "proxy" in health
            assert "cookies" in health
            assert "recovery" in health
            assert "block_rate_pct" in health
            assert "account_state" in health
            assert "metrics_sample" in health
            # Also test apply_preset shape
            pres = await b.apply_preset("amazon_2026")
            assert pres["status"] in ("success", "error")
            # debug_report shape
            dr = await b.debug_report()
            assert dr["status"] == "success"
            assert "report" in dr
        finally:
            await b.close()
    asyncio.run(_run())


if __name__ == "__main__":
    # Allow direct run
    test_proxy_wiring_and_tier_selection()
    test_session_orchestrator_mcp_friendly()
    test_rate_limiter_mcp_safe_path()
    test_cookie_manager_contract()
    test_agentbrowser_session_and_bundle_contract()
    test_tls_profile_selection_contract()
    test_health_status_contract_shape()
    print("All MCP contract tests passed (logic level) + TLS + health shape contracts.")
