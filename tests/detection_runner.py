#!/usr/bin/env python3
"""
Detection Testing Suite for Agentic Stealth Browser (Phase 3)
Tests stealth effectiveness against real protected sites.

Addresses P1 crash (#100 / related to #256 E2E recovery):
  Previously used `browser.browser.content()` (wrong attr, Context has no content).
  Now uses `browser.page.content()` with safe guards (post naming hygiene).
  Also hardened finally close check.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent_browser import AgentBrowser


class DetectionTester:
    """Automated detection testing framework."""

    TEST_SITES = [
        {
            "name": "Cloudflare Challenge",
            "url": "https://nowsecure.nl",
            "platform": "cloudflare",
            "expected_signals": ["captcha", "challenge"],
        },
        {
            "name": "LinkedIn Profile",
            "url": "https://www.linkedin.com/in/williamhgates",
            "platform": "linkedin",
            "expected_signals": ["unusual activity", "security verification"],
        },
        {
            "name": "Amazon JP",
            "url": "https://www.amazon.co.jp/dp/B08L5V9Y5H",
            "platform": "amazon",
            "expected_signals": ["captcha", "robot"],
        },
        {
            "name": "Upwork Search",
            "url": "https://www.upwork.com/nx/search/jobs/",
            "platform": "upwork",
            "expected_signals": ["captcha", "blocked"],
        },
    ]

    def __init__(self):
        self.results = []
        self.scorecard = {
            "total_tests": 0,
            "detected": 0,
            "passed": 0,
            "signals_found": [],
        }

    async def run_single_test(self, test_case: Dict) -> Dict:
        """Run detection test on a single site."""
        print(f"\n[Testing] {test_case['name']}")
        print(f"  URL: {test_case['url']}")

        browser = AgentBrowser(session_name=f"detection-{test_case['platform']}")
        result = {
            "site": test_case["name"],
            "url": test_case["url"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "detected": False,
            "signals": [],
            "success": False,
            "error": None,
        }

        try:
            await browser.launch(headless=True)

            # Navigate with stealth + recovery (supports #256 E2E recovery scenarios)
            success = await browser.safe_goto(
                test_case["url"], platform=test_case["platform"], warm_up=False
            )

            if not success:
                result["error"] = "Navigation failed"
                return result

            await browser.human.think(1200, 2500)

            # Check for detection signals (fixed P1: use .page not .browser)
            try:
                page = getattr(browser, "page", None)
                if page:
                    content = await page.content()
                    content_lower = content.lower()

                    for signal in test_case["expected_signals"]:
                        if signal.lower() in content_lower:
                            result["signals"].append(signal)
                            result["detected"] = True

                    # Additional generic checks
                    detection_keywords = [
                        "captcha",
                        "challenge",
                        "verify",
                        "unusual activity",
                        "blocked",
                        "robot",
                        "security check",
                        "access denied",
                    ]

                    for keyword in detection_keywords:
                        if (
                            keyword in content_lower
                            and keyword not in result["signals"]
                        ):
                            result["signals"].append(keyword)
                            result["detected"] = True
                else:
                    result["error"] = "No page available for content analysis"

            except Exception as e:
                result["error"] = f"Content analysis failed: {str(e)}"

            result["success"] = True

            if result["detected"]:
                print(f"  ⚠️  DETECTED — Signals: {result['signals']}")
                self.scorecard["detected"] += 1
            else:
                print("  ✅ PASSED — No obvious detection signals")
                self.scorecard["passed"] += 1

        except Exception as e:
            result["error"] = str(e)
            print(f"  ❌ ERROR: {e}")

        finally:
            # Robust close (use .page or direct close; supports context manager too)
            try:
                if getattr(browser, "page", None) or getattr(browser, "browser", None):
                    await browser.close()
            except Exception:
                pass  # best effort close in test runner

        self.scorecard["total_tests"] += 1
        self.results.append(result)
        return result

    async def run_full_suite(self):
        """Run detection tests against all configured sites."""
        print("=" * 60)
        print("AGENTIC STEALTH BROWSER — Detection Testing Suite")
        print("=" * 60)

        for test_case in self.TEST_SITES:
            await self.run_single_test(test_case)
            await asyncio.sleep(2)  # Small delay between tests

        self._print_summary()

    def _print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 60)
        print("DETECTION TEST SUMMARY")
        print("=" * 60)
        print(f"Total Tests     : {self.scorecard['total_tests']}")
        print(f"Detected        : {self.scorecard['detected']}")
        print(f"Passed          : {self.scorecard['passed']}")
        print(
            f"Detection Rate  : {self.scorecard['detected'] / max(1, self.scorecard['total_tests']) * 100:.1f}%"
        )

        if self.scorecard["detected"] > 0:
            print("\n⚠️  Sites with detection signals:")
            for r in self.results:
                if r["detected"]:
                    print(f"  - {r['site']:}: {r['signals']}")

        print("\n" + "=" * 60)

    def save_historical_record(self, filepath: str = "tests/detection_history.json"):
        """Append current results to historical tracking file."""
        history = []

        if Path(filepath).exists():
            try:
                with open(filepath, "r") as f:
                    history = json.load(f)
            except Exception:
                history = []

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scorecard": self.scorecard,
            "results": self.results,
        }

        history.append(record)

        if len(history) > 50:
            history = history[-50:]

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(history, f, indent=2)

        print(f"Historical record saved. Total runs tracked: {len(history)}")
        return filepath

    def save_results(self, filepath: str = None):
        """Save results to JSON file."""
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            filepath = f"tests/detection_results_{timestamp}.json"

        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scorecard": self.scorecard,
            "results": self.results,
        }

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(output, f, indent=2)

        print(f"Results saved to: {filepath}")
        return filepath


async def main():
    tester = DetectionTester()
    await tester.run_full_suite()
    tester.save_results()


if __name__ == "__main__":
    asyncio.run(main())
