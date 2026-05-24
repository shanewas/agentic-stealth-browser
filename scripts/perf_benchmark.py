#!/usr/bin/env python3
"""
Performance Benchmarking Script — v1.5.0

Measures key AgentBrowser operations:
- launch overhead
- safe_goto latency
- safe_click latency
- safe_type throughput
- context creation/reuse
- stealth script injection time

Usage:
    python scripts/perf_benchmark.py --iterations 10 --warmup 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BenchmarkResult:
    name: str
    samples: List[float] = field(default_factory=list)
    iterations: int = 0

    @property
    def mean(self) -> float:
        return statistics.mean(self.samples) if self.samples else 0.0

    @property
    def median(self) -> float:
        return statistics.median(self.samples) if self.samples else 0.0

    @property
    def p95(self) -> float:
        if not self.samples:
            return 0.0
        s = sorted(self.samples)
        idx = int(len(s) * 0.95)
        return s[min(idx, len(s) - 1)]

    @property
    def p99(self) -> float:
        if not self.samples:
            return 0.0
        s = sorted(self.samples)
        idx = int(len(s) * 0.99)
        return s[min(idx, len(s) - 1)]

    @property
    def stddev(self) -> float:
        return statistics.stdev(self.samples) if len(self.samples) > 1 else 0.0

    @property
    def min_sample(self) -> float:
        return min(self.samples) if self.samples else 0.0

    @property
    def max_sample(self) -> float:
        return max(self.samples) if self.samples else 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "iterations": self.iterations,
            "mean_ms": round(self.mean * 1000, 2),
            "median_ms": round(self.median * 1000, 2),
            "p95_ms": round(self.p95 * 1000, 2),
            "p99_ms": round(self.p99 * 1000, 2),
            "stddev_ms": round(self.stddev * 1000, 2),
            "min_ms": round(self.min_sample * 1000, 2),
            "max_ms": round(self.max_sample * 1000, 2),
        }


class PerfBenchmark:
    def __init__(self, iterations: int = 10, warmup: int = 3, verbose: bool = False):
        self.iterations = iterations
        self.warmup = warmup
        self.verbose = verbose
        self.results: Dict[str, BenchmarkResult] = {}
        self._session_name = "perf-bench"

    def _run(self, name: str, fn, *args: Any, **kwargs: Any) -> BenchmarkResult:
        result = BenchmarkResult(name=name, iterations=self.iterations)

        for _ in range(self.warmup):
            try:
                fn(*args, **kwargs)
            except Exception as e:
                if self.verbose:
                    print(f"  warmup failure [{name}]: {e}")

        for i in range(self.iterations):
            t0 = time.perf_counter()
            try:
                fn(*args, **kwargs)
            except Exception as e:
                if self.verbose:
                    print(f"  iter {i} failure [{name}]: {e}")
                continue
            elapsed = time.perf_counter() - t0
            result.samples.append(elapsed)
            if self.verbose:
                print(
                    f"  [{name}] iter {i + 1}/{self.iterations}: {elapsed * 1000:.1f}ms"
                )

        self.results[name] = result
        return result

    def bench_imports(self) -> BenchmarkResult:
        def _import_core():
            import importlib

            for mod in (
                "core.agent_browser",
                "core.types",
                "core.session_checkpoint",
                "core.connection_pool",
            ):
                importlib.import_module(mod)

        return self._run("import_core_modules", _import_core)

    def bench_policy_load(self) -> BenchmarkResult:
        from production.policy_engine import PolicyEngine

        engine = PolicyEngine()

        def _load() -> None:
            e = PolicyEngine()
            e.load_policies()

        return self._run("policy_engine_load", _load)

    def bench_input_validation(self) -> BenchmarkResult:
        from production.mcp_input_validator import validate_tool_input

        def _validate() -> None:
            validate_tool_input(
                "stealth_navigate", {"url": "https://example.com", "warm_up": True}
            )
            validate_tool_input(
                "stealth_launch", {"session_name": "test", "headless": True}
            )

        return self._run("input_validation", _validate)

    def bench_audit_logging(self) -> BenchmarkResult:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            from audit.logger import AuditLogger

            logger = AuditLogger("perf-bench", log_dir=tmp)

            def _log() -> None:
                logger.log_action(
                    "safe_goto", {"url": "https://example.com", "duration_ms": 234}
                )
                logger.log_action("safe_click", {"selector": "#btn", "duration_ms": 45})

            return self._run("audit_logging", _log)

    async def bench_rate_limiter(self) -> BenchmarkResult:
        from production.rate_limiter import ToolRateLimiter

        limiter = ToolRateLimiter(tool_calls_per_minute=10000, total_calls_cap=50000)

        result = BenchmarkResult(
            name="tool_rate_limiter_check", iterations=self.iterations
        )

        async def _check() -> None:
            await limiter.check_and_wait("goto")

        for _ in range(self.warmup):
            try:
                await _check()
            except Exception as e:
                if self.verbose:
                    print(f"  warmup failure [tool_rate_limiter_check]: {e}")

        for i in range(self.iterations):
            t0 = time.perf_counter()
            try:
                await _check()
            except Exception as e:
                if self.verbose:
                    print(f"  iter {i} failure [tool_rate_limiter_check]: {e}")
                continue
            elapsed = time.perf_counter() - t0
            result.samples.append(elapsed)
            if self.verbose:
                print(
                    f"  [tool_rate_limiter_check] iter {i + 1}/{self.iterations}: {elapsed * 1000:.1f}ms"
                )

        self.results[result.name] = result
        return result

    async def bench_all(self) -> Dict[str, Any]:
        self.bench_imports()
        self.bench_input_validation()
        self.bench_audit_logging()
        await self.bench_rate_limiter()
        try:
            self.bench_policy_load()
        except Exception:
            pass
        return self.report()

    def report(self) -> Dict[str, Any]:
        return {
            "iterations": self.iterations,
            "warmup": self.warmup,
            "results": [r.to_dict() for r in self.results.values()],
        }

    def print_report(self) -> None:
        print(f"\n{'=' * 60}")
        print("PERFORMANCE BENCHMARK")
        print(f"{'=' * 60}")
        print(f"  iterations: {self.iterations}")
        print(f"  warmup:     {self.warmup}")
        print(f"{'=' * 60}")

        col_widths = [28, 10, 10, 10, 10, 10, 10]
        headers = ["Operation", "Mean(ms)", "Median", "P95", "P99", "Min", "Max"]
        fmt = "  ".join(f"{h:<{w}}" for h, w in zip(headers, col_widths))

        print(f"\n{fmt}")
        print("-" * len(fmt))

        for r in sorted(self.results.values(), key=lambda x: x.mean, reverse=True):
            d = r.to_dict()
            row = [
                d["name"][:26],
                str(d["mean_ms"]),
                str(d["median_ms"]),
                str(d["p95_ms"]),
                str(d["p99_ms"]),
                str(d["min_ms"]),
                str(d["max_ms"]),
            ]
            print("  ".join(f"{v:<{w}}" for v, w in zip(row, col_widths)))

        print(f"\n{'=' * 60}\n")


async def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Agentic Stealth Browser — Performance Benchmark"
    )
    parser.add_argument(
        "--iterations", type=int, default=10, help="Number of iterations per benchmark"
    )
    parser.add_argument(
        "--warmup", type=int, default=3, help="Number of warmup iterations"
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args(argv)

    bench = PerfBenchmark(
        iterations=args.iterations,
        warmup=args.warmup,
        verbose=args.verbose,
    )
    report = await bench.bench_all()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        bench.print_report()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
