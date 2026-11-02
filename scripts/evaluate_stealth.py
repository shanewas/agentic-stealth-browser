#!/usr/bin/env python3
"""
Stealth Evaluation Harness — compares warm vs cold navigation.

H4 note: AgentBrowser has no supported stealth-disable switch (no
constructor/launch parameter and no env switch honoured by launch();
launch() injects the stealth init-script unconditionally). This script
therefore does NOT compare stealth vs no-stealth and reports no stealth
delta. Both conditions run with stealth enabled; they differ only in
safe_goto(warm_up=...), so the delta measures the warm-up effect only.

Generates comparative reports on:
  - Success rate (navigation without blocking)
  - Detection rate (fingerprint checks triggered)
  - Timing (load times, response latency)

Reproducibility gate: same seed = same results.

Usage:
    python scripts/evaluate_stealth.py [--seed 42] [--iterations 10] [--report report.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class StealthMetric:
    name: str
    value: float
    unit: str = ""
    category: str = ""


@dataclass
class EvalResult:
    run_id: int
    mode: str  # "warm" | "cold" (both stealth-enabled)
    url: str
    success: bool
    load_time_ms: float
    block_detected: bool
    block_type: str = ""
    fingerprint_checks: int = 0
    metrics: List[StealthMetric] = field(default_factory=list)
    error: str = ""


class StealthEvaluator:
    """Compares warm vs cold navigation; both conditions use stealth.

    There is no supported way to disable AgentBrowser's stealth injection,
    so this never claims a stealth-vs-no-stealth effect.

    Reproducibility gate: setting the same seed guarantees the same execution sequence
    (same URLs, same behavior parameters, same timing distributions).
    """

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
        self.warm_results: List[EvalResult] = []
        self.cold_results: List[EvalResult] = []

    async def run_cold_navigate(self, url: str) -> EvalResult:
        """Navigate with stealth enabled but without warm-up (cold)."""
        from core.agent_browser import AgentBrowser

        browser = None
        start = time.monotonic()
        try:
            browser = AgentBrowser(
                session_name=f"eval_cold_{time.time_ns()}",
                anonymous=True,
                ephemeral=True,
                light_mode=True,
            )
            await browser.launch(headless=True)
            ok = await browser.safe_goto(str(url), warm_up=False, platform="eval")
            elapsed = (time.monotonic() - start) * 1000
            block = not ok
            return EvalResult(
                run_id=0,
                mode="cold",
                url=url,
                success=ok,
                load_time_ms=elapsed,
                block_detected=block,
                block_type="navigation_failed" if block else "",
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return EvalResult(
                run_id=0,
                mode="cold",
                url=url,
                success=False,
                load_time_ms=elapsed,
                block_detected=True,
                block_type="exception",
                error=str(exc),
            )
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def run_warm_navigate(self, url: str) -> EvalResult:
        """Navigate with stealth enabled and with warm-up (warm)."""
        from core.agent_browser import AgentBrowser

        browser = None
        start = time.monotonic()
        try:
            browser = AgentBrowser(
                session_name=f"eval_warm_{time.time_ns()}",
                anonymous=True,
                ephemeral=True,
                light_mode=True,
            )
            await browser.launch(headless=True)
            ok = await browser.safe_goto(str(url), warm_up=True, platform="eval")
            elapsed = (time.monotonic() - start) * 1000
            block = not ok
            return EvalResult(
                run_id=0,
                mode="warm",
                url=url,
                success=ok,
                load_time_ms=elapsed,
                block_detected=block,
                block_type="navigation_failed" if block else "",
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return EvalResult(
                run_id=0,
                mode="warm",
                url=url,
                success=False,
                load_time_ms=elapsed,
                block_detected=True,
                block_type="exception",
                error=str(exc),
            )
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def evaluate(self, urls: List[str], iterations: int = 3) -> Dict[str, Any]:
        """Run warm vs cold evaluation on a set of URLs (both stealth-enabled)."""
        for i in range(iterations):
            for url in urls:
                # Shuffle order but use seeded random
                order = self.rng.choice(["warm", "cold"])
                if order == "warm":
                    self.warm_results.append(await self.run_warm_navigate(url))
                    self.cold_results.append(await self.run_cold_navigate(url))
                else:
                    self.cold_results.append(await self.run_cold_navigate(url))
                    self.warm_results.append(await self.run_warm_navigate(url))

        return self.generate_report()

    def generate_report(self) -> Dict[str, Any]:
        def _stats(results: List[EvalResult]) -> Dict[str, Any]:
            if not results:
                return {
                    "count": 0,
                    "success_rate": 0.0,
                    "detection_rate": 0.0,
                    "avg_load_time_ms": 0.0,
                    "min_load_time_ms": 0.0,
                    "max_load_time_ms": 0.0,
                }
            successes = sum(1 for r in results if r.success)
            load_times = [r.load_time_ms for r in results]
            blocks = sum(1 for r in results if r.block_detected)
            return {
                "count": len(results),
                "success_rate": successes / len(results),
                "detection_rate": blocks / len(results),
                "avg_load_time_ms": sum(load_times) / len(load_times)
                if load_times
                else 0,
                "min_load_time_ms": min(load_times) if load_times else 0,
                "max_load_time_ms": max(load_times) if load_times else 0,
            }

        warm_stats = _stats(self.warm_results)
        cold_stats = _stats(self.cold_results)

        delta = warm_stats["success_rate"] - cold_stats["success_rate"]

        return {
            "seed": self.seed,
            "conditions": {
                "warm": "stealth enabled, safe_goto(warm_up=True)",
                "cold": "stealth enabled, safe_goto(warm_up=False)",
            },
            "stealth_comparison_claimed": False,
            "warm": warm_stats,
            "cold": cold_stats,
            "comparison": {
                "note": (
                    "Warm-minus-cold only: both conditions run with stealth "
                    "injection enabled, so this delta measures the warm-up "
                    "effect, not stealth effectiveness."
                ),
                "success_rate_delta_warm_minus_cold": delta,
                "detection_rate_delta_warm_minus_cold": (
                    warm_stats["detection_rate"] - cold_stats["detection_rate"]
                ),
                "load_time_overhead_ms_warm_minus_cold": (
                    warm_stats["avg_load_time_ms"] - cold_stats["avg_load_time_ms"]
                ),
            },
            "raw_results": {
                "warm": [
                    {
                        "run_id": r.run_id,
                        "url": r.url,
                        "success": r.success,
                        "load_time_ms": r.load_time_ms,
                        "block_detected": r.block_detected,
                        "block_type": r.block_type,
                        "error": r.error,
                    }
                    for r in self.warm_results[-20:]
                ],
                "cold": [
                    {
                        "run_id": r.run_id,
                        "url": r.url,
                        "success": r.success,
                        "load_time_ms": r.load_time_ms,
                        "block_detected": r.block_detected,
                        "block_type": r.block_type,
                        "error": r.error,
                    }
                    for r in self.cold_results[-20:]
                ],
            },
        }


def _default_test_urls() -> List[str]:
    """Safe default URLs for evaluation (no real-world sites)."""
    return [
        "https://httpbin.org/html",
        "https://httpbin.org/get",
        "https://httpbin.org/headers",
    ]


async def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate warm vs cold navigation (both stealth-enabled)",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducibility"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Number of evaluation iterations per URL",
    )
    parser.add_argument(
        "--urls", nargs="*", help="URLs to evaluate (default: httpbin test URLs)"
    )
    parser.add_argument(
        "--report", type=str, default="", help="Path to write JSON report"
    )
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    args = parser.parse_args(argv)
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")

    urls = args.urls if args.urls else _default_test_urls()
    evaluator = StealthEvaluator(seed=args.seed)
    report = await evaluator.evaluate(urls, iterations=args.iterations)

    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2, default=str))
        print(f"Report written to {args.report}", file=sys.stderr)

    if args.json or not args.report:
        print(json.dumps(report, indent=2, default=str))

    results = evaluator.warm_results + evaluator.cold_results
    if not results or not any(r.success for r in results):
        print("All navigations failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
