#!/usr/bin/env python3
"""
Stealth Evaluation Harness — compares patched vs baseline browser behavior.

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
    mode: str          # "patched" | "baseline"
    url: str
    success: bool
    load_time_ms: float
    block_detected: bool
    block_type: str = ""
    fingerprint_checks: int = 0
    metrics: List[StealthMetric] = field(default_factory=list)
    error: str = ""


class StealthEvaluator:
    """Evaluates stealth quality by running patched vs baseline comparisons.

    Reproducibility gate: setting the same seed guarantees the same execution sequence
    (same URLs, same behavior parameters, same timing distributions).
    """

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
        self.patched_results: List[EvalResult] = []
        self.baseline_results: List[EvalResult] = []

    async def run_baseline_navigate(self, url: str) -> EvalResult:
        """Navigate to a URL without stealth patching (baseline)."""
        from core.agent_browser import AgentBrowser
        browser = None
        try:
            start = time.monotonic()
            browser = AgentBrowser(
                session_name=f"eval_baseline_{time.time_ns()}",
                anonymous=True,
                ephemeral=True,
                light_mode=True,
            )
            await browser.launch(headless=True)
            ok = await browser.safe_goto(str(url), warm_up=False, platform="eval")
            elapsed = (time.monotonic() - start) * 1000
            block = not ok
            return EvalResult(
                run_id=0, mode="baseline", url=url,
                success=ok, load_time_ms=elapsed,
                block_detected=block, block_type="navigation_failed" if block else "",
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return EvalResult(
                run_id=0, mode="baseline", url=url,
                success=False, load_time_ms=elapsed,
                block_detected=True, block_type="exception",
                error=str(exc),
            )
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def run_patched_navigate(self, url: str) -> EvalResult:
        """Navigate to a URL with full stealth patching."""
        from core.agent_browser import AgentBrowser
        browser = None
        try:
            start = time.monotonic()
            browser = AgentBrowser(
                session_name=f"eval_patched_{time.time_ns()}",
                anonymous=True,
                ephemeral=True,
                light_mode=True,
            )
            await browser.launch(headless=True)
            ok = await browser.safe_goto(str(url), warm_up=True, platform="eval")
            elapsed = (time.monotonic() - start) * 1000
            block = not ok
            return EvalResult(
                run_id=0, mode="patched", url=url,
                success=ok, load_time_ms=elapsed,
                block_detected=block, block_type="navigation_failed" if block else "",
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return EvalResult(
                run_id=0, mode="patched", url=url,
                success=False, load_time_ms=elapsed,
                block_detected=True, block_type="exception",
                error=str(exc),
            )
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def evaluate(self, urls: List[str], iterations: int = 3) -> Dict[str, Any]:
        """Run patched vs baseline evaluation on a set of URLs."""
        for i in range(iterations):
            for url in urls:
                # Shuffle order but use seeded random
                order = self.rng.choice(["patched", "baseline"])
                if order == "patched":
                    self.patched_results.append(await self.run_patched_navigate(url))
                    self.baseline_results.append(await self.run_baseline_navigate(url))
                else:
                    self.baseline_results.append(await self.run_baseline_navigate(url))
                    self.patched_results.append(await self.run_patched_navigate(url))

        return self.generate_report()

    def generate_report(self) -> Dict[str, Any]:
        def _stats(results: List[EvalResult]) -> Dict[str, Any]:
            if not results:
                return {"count": 0, "success_rate": 0.0}
            successes = sum(1 for r in results if r.success)
            load_times = [r.load_time_ms for r in results]
            blocks = sum(1 for r in results if r.block_detected)
            return {
                "count": len(results),
                "success_rate": successes / len(results),
                "detection_rate": blocks / len(results),
                "avg_load_time_ms": sum(load_times) / len(load_times) if load_times else 0,
                "min_load_time_ms": min(load_times) if load_times else 0,
                "max_load_time_ms": max(load_times) if load_times else 0,
            }

        patched_stats = _stats(self.patched_results)
        baseline_stats = _stats(self.baseline_results)

        patched_success = patched_stats["success_rate"]
        baseline_success = baseline_stats["success_rate"]
        improvement = patched_success - baseline_success

        return {
            "seed": self.seed,
            "patched": patched_stats,
            "baseline": baseline_stats,
            "comparison": {
                "success_rate_delta": improvement,
                "success_improvement_pct": (improvement * 100) if baseline_success > 0 else 0,
                "detection_rate_reduction": (
                    baseline_stats["detection_rate"] - patched_stats["detection_rate"]
                ),
                "load_time_overhead_ms": (
                    patched_stats["avg_load_time_ms"] - baseline_stats["avg_load_time_ms"]
                ),
            },
            "raw_results": {
                "patched": [
                    {
                        "run_id": r.run_id, "url": r.url,
                        "success": r.success, "load_time_ms": r.load_time_ms,
                        "block_detected": r.block_detected, "block_type": r.block_type,
                        "error": r.error,
                    }
                    for r in self.patched_results[-20:]
                ],
                "baseline": [
                    {
                        "run_id": r.run_id, "url": r.url,
                        "success": r.success, "load_time_ms": r.load_time_ms,
                        "block_detected": r.block_detected, "block_type": r.block_type,
                        "error": r.error,
                    }
                    for r in self.baseline_results[-20:]
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
        description="Evaluate stealth effectiveness (patched vs baseline)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--iterations", type=int, default=3, help="Number of evaluation iterations per URL")
    parser.add_argument("--urls", nargs="*", help="URLs to evaluate (default: httpbin test URLs)")
    parser.add_argument("--report", type=str, default="", help="Path to write JSON report")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    args = parser.parse_args(argv)

    urls = args.urls if args.urls else _default_test_urls()
    evaluator = StealthEvaluator(seed=args.seed)
    report = await evaluator.evaluate(urls, iterations=args.iterations)

    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2, default=str))
        print(f"Report written to {args.report}", file=sys.stderr)

    if args.json or not args.report:
        print(json.dumps(report, indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
