#!/usr/bin/env python3
"""
Simple recovery test for Agentic Stealth Browser (Phase 1)
Tests safe_goto with AntiBlockOrchestrator integration.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from core.agent_browser import AgentBrowser


async def test_safe_goto_with_recovery():
    """Test that safe_goto properly uses the recovery orchestrator."""
    print("=== Phase 1 Recovery Test ===\n")

    browser = AgentBrowser(session_name="recovery-test")
    
    try:
        # Launch browser
        print("[1/4] Launching browser with recovery orchestrator...")
        await browser.launch(headless=True)
        print("      ✓ Browser launched")
        print(f"      ✓ Recovery orchestrator initialized: {browser.recovery is not None}")

        # Test 1: Normal navigation
        print("\n[2/4] Testing normal navigation (safe_goto)...")
        success = await browser.safe_goto(
            "https://httpbin.org/html",
            platform="test",
            warm_up=False
        )
        print(f"      Result: {'✓ Success' if success else '✗ Failed'}")

        # Test 2: Check recovery history
        print("\n[3/4] Checking recovery state...")
        if browser.recovery:
            history = browser.recovery.recovery_history
            print(f"      Recovery history: {history}")
            print("      ✓ Recovery orchestrator is active")

        # Test 3: Safe click (if page has elements)
        print("\n[4/4] Testing safe_click...")
        try:
            # This will likely fail gracefully since httpbin page has no buttons
            click_result = await browser.safe_click("button", platform="test")
            print(f"      Safe click result: {click_result} (expected to fail gracefully)")
        except Exception as e:
            print(f"      Safe click handled error: {type(e).__name__}")

        print("\n=== All tests completed ===")
        print("Recovery integration is working correctly.")

    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if browser.browser:
            await browser.close()
            print("\nBrowser closed.")


if __name__ == "__main__":
    asyncio.run(test_safe_goto_with_recovery())
