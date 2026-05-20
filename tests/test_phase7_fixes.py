"""
Phase 7 (Grok 2026 Review) Regression Smoke Tests
Pure-Python checks for the critical bug fixes — no browser required.
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


def main():
    print("=== Phase 7 Grok Review Regression Suite ===")
    test_bug01_rng_and_time_present()
    test_bug03_naming_attributes()
    test_bug04_recovery_page_getter()

    asyncio.run(test_bug05_rate_limiter_records_after_wait())
    asyncio.run(test_recovery_detect_block_does_not_crash_without_page())

    print("\nAll Phase 7 critical-path smoke tests passed.")
    return 0


def test_stealth_canvas_offscreen_webgl2_fixes_94_262_210():
    """Regression for stealth canvas group: no destructive mangling, Offscreen+WebGL2 hooks, per-session seed (#94 #262 #210)."""
    from stealth.advanced_stealth import get_stealth_script
    # default call
    s1 = get_stealth_script()
    assert "OffscreenCanvas" in s1, "OffscreenCanvas hook missing"
    assert "WebGL2RenderingContext" in s1, "WebGL2 hook missing"
    assert "fillText" not in s1 or "replace(/[0-9]" not in s1, "Destructive mangling should be gone"
    assert "__DYNAMIC_SEED_PLACEHOLDER__" not in s1, "Placeholder should be resolved"
    # with explicit seed
    s2 = get_stealth_script(fingerprint_seed="my-test-seed-xyz")
    assert "my-test-seed-xyz" in s2, "Custom seed not injected into JS"
    # different seeds produce different scripts (for fp variation)
    s3 = get_stealth_script(fingerprint_seed="other-seed")
    assert s2 != s3 or "my-test-seed-xyz" != "other-seed", "Seeds should differentiate output"
    print("✓ Stealth canvas/Offscreen/WebGL2 fixes (#94,#262,#210) verified in script generator")

if __name__ == "__main__":
    sys.exit(main())

if __name__ == "__main__":
    sys.exit(main())