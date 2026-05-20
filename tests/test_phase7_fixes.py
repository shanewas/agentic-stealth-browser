"""
Phase 7 (Grok 2026 Review) Regression Smoke Tests + Phase 8 extensions
Pure-Python checks for the critical bug fixes — no browser required for most.
Run with: python -m pytest tests/test_phase7_fixes.py -q  or  python tests/test_phase7_fixes.py
"""
import asyncio
import sys
from pathlib import Path

# Ensure repo root on path when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent_browser import AgentBrowser
from production.rate_limiter import domain_limiter, RateLimitConfig
from recovery.anti_block_orchestrator import AntiBlockOrchestrator, BlockType


def test_bug01_rng_and_time_present():
    """BUG-01: AgentBrowser no longer crashes on construction due to missing rng/time."""
    b = AgentBrowser(session_name="phase7-rng-test")
    assert hasattr(b, "rng") and b.rng is not None
    import time
    assert time.time() > 0
    print("✓ BUG-01: rng + time present")


def test_bug03_naming_attributes():
    """BUG-03: Context / Page / browser attributes exist and are documented."""
    b = AgentBrowser(session_name="phase7-naming-test")
    assert hasattr(b, "browser")
    assert hasattr(b, "page")
    assert hasattr(b, "context")
    print("✓ BUG-03: naming attributes (browser, page, context) present")


async def test_bug05_rate_limiter_records_after_wait():
    """BUG-05: wait_if_needed now records the request even on the waited path."""
    domain_limiter.set_limit("phase7.test", RateLimitConfig(requests_per_minute=1, cooldown_seconds=0))
    # clear any prior state
    domain_limiter.request_times["phase7.test"].clear()
    domain_limiter.last_request.pop("phase7.test", None)

    w1 = await domain_limiter.wait_if_needed("phase7.test")
    w2 = await domain_limiter.wait_if_needed("phase7.test")

    assert w1 == 0.0
    assert w2 > 0   # we had to wait
    # After the fix the second request *was* recorded
    assert len(domain_limiter.request_times["phase7.test"]) >= 2
    print("✓ BUG-05: rate limiter records after wait (window populated)")


def test_bug04_recovery_page_getter():
    """BUG-04: AntiBlockOrchestrator accepts and stores page_getter."""
    called = {}
    def fake_getter():
        called["hit"] = True
        return None   # no real page, but the path is exercised

    orch = AntiBlockOrchestrator(page_getter=fake_getter)
    assert orch._get_page is not None
    p = orch._get_page()
    assert "hit" in called
    print("✓ BUG-04: page_getter wiring works")


async def test_recovery_detect_block_does_not_crash_without_page():
    """Even without page, detect_block should return NONE or a type, never explode."""
    orch = AntiBlockOrchestrator(page_getter=None)
    ctx = type("Ctx", (), {"http_status": 200, "response_time": 0.1, "last_error": "", "platform": "test"})()
    bt = await orch.detect_block(ctx)
    assert isinstance(bt, BlockType)
    print("✓ Recovery detect_block safe with no page_getter")


async def test_recovery_detect_block_safe_when_getter_returns_no_page():
    """Page getter set but returns None/ falsy -> must not UnboundLocalError on content_lower (fixes #17, #120)."""
    called = {}
    def fake_getter():
        called["called"] = True
        return None  # simulates early state or closed page
    orch = AntiBlockOrchestrator(page_getter=fake_getter)
    ctx = type("Ctx", (), {"http_status": 200, "response_time": 5.0, "last_error": "slow response", "platform": "linkedin"})()
    bt = await orch.detect_block(ctx)
    assert isinstance(bt, BlockType)
    assert "called" in called
    # Should not crash and likely return NONE or SOFT (but no content to trigger captcha etc)
    print("✓ Recovery detect_block safe when page_getter returns no page (no UnboundLocalError)")


def test_safe_extract_base_user_robust():
    """Test the defensive proxy username parser (fixes #99, #10 brittle split)."""
    from recovery.anti_block_orchestrator import AntiBlockOrchestrator
    orch = AntiBlockOrchestrator()
    # Typical Decodo format
    assert orch._safe_extract_base_user("user-myaccount-country-jp-session-foo-...") == "myaccount"
    assert orch._safe_extract_base_user("user-foo-bar-baz") == "foo"
    # Edge cases that used to crash
    assert orch._safe_extract_base_user("no-dashes-here") == "default"
    assert orch._safe_extract_base_user("user-onlyonepart") == "onlyonepart"
    assert orch._safe_extract_base_user(None) == "default"
    assert orch._safe_extract_base_user("") == "default"
    assert orch._safe_extract_base_user(12345) == "default"
    print("✓ _safe_extract_base_user handles normal + malformed inputs without crashing")


async def test_292_context_manager():
    """Test async context manager support for AgentBrowser (#292).
    
    Guarantees cleanup on normal exit and on exceptions inside the block.
    This is a high-value reliability improvement.
    """
    print("Testing context manager for #292...")

    # Case 1: Normal usage and exit
    b1 = AgentBrowser(session_name="cm-test-normal", anonymous=True)
    assert b1.browser is None
    async with b1:
        assert b1.browser is not None, "browser should be launched in __aenter__"
        assert b1.page is not None
        assert b1.context is not None
        # quick sanity: page url is about:blank initially
        assert "about:blank" in (b1.page.url or "")
    # After exit, must be cleaned
    assert b1.browser is None
    assert b1.page is None
    print("  ✓ Normal async with + auto-close works")

    # Case 2: Exception inside block still triggers cleanup
    b2 = AgentBrowser(session_name="cm-test-exception", anonymous=True)
    try:
        async with b2:
            assert b2.browser is not None
            raise RuntimeError("intentional for cleanup test")
    except RuntimeError:
        pass
    assert b2.browser is None
    assert b2.page is None
    print("  ✓ Exception path still cleans up")

    # Case 3: Pre-launched still works
    b3 = AgentBrowser(session_name="cm-test-pre", anonymous=True)
    await b3.launch(headless=True)
    async with b3:
        assert b3.browser is not None
        # no re-launch
    assert b3.browser is None
    print("  ✓ Pre-launched browser also cleans via context manager")

    print("✓ #292: async context manager delivers reliable cleanup (normal + exceptional paths)")


# --- Additional Phase 8+ smoke extensions (added by Testing Agent) ---

def test_presets_import_and_basic_diversity():
    """Presets module loads and produces differentiated personas (supports #240)."""
    from stealth.presets import get_preset, list_presets
    presets = list_presets()
    assert len(presets) >= 5
    li = get_preset("linkedin")
    cf = get_preset("cloudflare")
    assert li.tls_region != cf.tls_region or li.behavior_intensity != cf.behavior_intensity
    print("✓ Presets loaded and show persona differentiation")


def test_tls_manager_basic_selection():
    """TLS profile manager basic contract (supports #264)."""
    from stealth.tls_fingerprint import get_tls_manager, Region
    for r in ["us", "japan", "global"]:
        m = get_tls_manager(r)
        p = m.get_profile()
        assert "ciphers" in p and len(p["ciphers"]) > 3
    print("✓ TLS manager profile selection works")


async def test_rate_limiter_concurrent_smoke():
    """Minimal concurrent recording check (supports #248)."""
    from production.rate_limiter import DomainRateLimiter, RateLimitConfig
    lim = DomainRateLimiter()
    lim.set_limit("phase8.smoke", RateLimitConfig(50, 0))
    lim.request_times["phase8.smoke"].clear()

    async def hit():
        return await lim.wait_if_needed("phase8.smoke")

    results = await asyncio.gather(*[hit() for _ in range(8)])
    assert len(lim.request_times["phase8.smoke"]) >= 8
    print("✓ Rate limiter concurrent smoke passes")


def main():
    print("=== Phase 7+ Core Reliability Regression Suite ===")
    test_bug01_rng_and_time_present()
    test_bug03_naming_attributes()
    test_bug04_recovery_page_getter()
    test_presets_import_and_basic_diversity()
    test_tls_manager_basic_selection()

    asyncio.run(test_bug05_rate_limiter_records_after_wait())
    asyncio.run(test_recovery_detect_block_does_not_crash_without_page())
    asyncio.run(test_recovery_detect_block_safe_when_getter_returns_no_page())
    test_safe_extract_base_user_robust()
    asyncio.run(test_292_context_manager())
    asyncio.run(test_rate_limiter_concurrent_smoke())

    print("\nAll Phase 7+ critical-path smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
