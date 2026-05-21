#!/usr/bin/env python3
"""
Debug script for nowsecure.nl (Cloudflare challenge page)
Inspects response, content, and detection signals.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent_browser import AgentBrowser


async def debug_nowsecure():
    print("=" * 60)
    print("DEBUG: nowsecure.nl Cloudflare Challenge")
    print("=" * 60)

    browser = AgentBrowser(session_name="debug-nowsecure")

    try:
        print("\n[1] Launching browser...")
        await browser.launch(headless=True)
        print("    ✓ Browser launched")

        print("\n[2] Navigating to https://nowsecure.nl ...")
        page = browser.page

        try:
            response = await page.goto("https://nowsecure.nl", wait_until="domcontentloaded", timeout=30000)
            print(f"    Status: {response.status if response else 'No response'}")
        except Exception as e:
            print(f"    Navigation error: {e}")

        await asyncio.sleep(4)  # Wait for challenge to potentially appear

        print("\n[3] Inspecting page content...")

        try:
            title = await page.title()
            print(f"    Title: {title}")
        except Exception as e:
            print(f"    Title error: {e}")

        try:
            content = await page.content()
            content_lower = content.lower()

            # Check for common Cloudflare signals
            signals = []
            if "just a moment" in content_lower:
                signals.append("just a moment")
            if "checking your browser" in content_lower:
                signals.append("checking your browser")
            if "cf-challenge" in content_lower or "cf-ray" in content_lower:
                signals.append("cf-challenge / cf-ray")
            if "captcha" in content_lower:
                signals.append("captcha")
            if "attention required" in content_lower:
                signals.append("attention required")
            if "access denied" in content_lower:
                signals.append("access denied")
            if "ray id" in content_lower:
                signals.append("ray id")

            print(f"    Detected signals: {signals if signals else 'None'}")

            # Show first 800 chars of body
            body_start = content[:800]
            print(f"\n    First 800 chars of page:\n    {body_start[:400]}...")

        except Exception as e:
            print(f"    Content inspection error: {e}")

        print("\n[4] Checking for detection indicators...")

        try:
            # Check for challenge elements
            challenge_selectors = [
                "div.cf-browser-verification",
                "#cf-challenge",
                "form[action*='challenge']",
                "input[name*='cf-challenge']"
            ]

            found_elements = []
            for selector in challenge_selectors:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        found_elements.append(selector)
                except Exception:
                    # Selector may not exist on this page; continue checking others
                    pass

            print(f"    Challenge elements found: {found_elements if found_elements else 'None'}")

        except Exception as e:
            print(f"    Element check error: {e}")

        print("\n" + "=" * 60)
        print("DEBUG COMPLETE")
        print("=" * 60)

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if browser.browser:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(debug_nowsecure())
