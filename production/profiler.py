"""
Performance Profiling Instrumentation — v1.5.0

Low-overhead timing decorators and context managers for profiling
safe_goto, safe_click, safe_type, and other hot paths.

Integrates with MetricsCollector.record_time().
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import time
from typing import Any, Callable, Optional


class TimingContext:
    """Collects timing samples with percentiles."""

    def __init__(self, max_samples: int = 1000):
        self.name: str = ""
        self._samples: list[float] = []
        self._max_samples = max_samples
        self._count: int = 0
        self._sum: float = 0.0
        self._min: float = float("inf")
        self._max: float = 0.0

    def record(self, duration: float) -> None:
        self._count += 1
        self._sum += duration
        if duration < self._min:
            self._min = duration
        if duration > self._max:
            self._max = duration
        if len(self._samples) < self._max_samples:
            self._samples.append(duration)

    @property
    def avg(self) -> float:
        if self._count == 0:
            return 0.0
        return self._sum / self._count

    def percentile(self, pct: float) -> float:
        if not self._samples:
            return 0.0
        sorted_samples = sorted(self._samples)
        idx = int(len(sorted_samples) * pct / 100.0)
        idx = min(idx, len(sorted_samples) - 1)
        return sorted_samples[idx]

    @property
    def p50(self) -> float:
        return self.percentile(50)

    @property
    def p95(self) -> float:
        return self.percentile(95)

    @property
    def p99(self) -> float:
        return self.percentile(99)

    def summary(self) -> dict:
        return {
            "count": self._count,
            "avg": round(self.avg, 4),
            "p50": round(self.p50, 4),
            "p95": round(self.p95, 4),
            "p99": round(self.p99, 4),
            "min": round(self._min, 4) if self._count else 0,
            "max": round(self._max, 4),
        }


class Profiler:
    """Collects timing data for named operations across multiple profiles."""

    def __init__(self, metrics_collector: Any = None):
        self._profiles: dict[str, TimingContext] = {}
        self._metrics = metrics_collector

    def profile(self, name: str) -> TimingContext:
        if name not in self._profiles:
            self._profiles[name] = TimingContext()
            self._profiles[name].name = name
        return self._profiles[name]

    @contextlib.contextmanager
    def measure(self, name: str):
        t0 = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - t0
            self.profile(name).record(elapsed)
            if self._metrics and hasattr(self._metrics, "record_time"):
                self._metrics.record_time(name, elapsed)

    async def aio_measure(self, name: str, coro):
        t0 = time.monotonic()
        try:
            return await coro
        finally:
            elapsed = time.monotonic() - t0
            self.profile(name).record(elapsed)
            if self._metrics and hasattr(self._metrics, "record_time"):
                self._metrics.record_time(name, elapsed)

    def get_summary(self) -> dict:
        return {name: ctx.summary() for name, ctx in sorted(self._profiles.items())}


def timing_decorator(profiler: Optional[Profiler] = None, name: Optional[str] = None):
    """Decorator to time a function and record to a Profiler."""

    def wrapper(func: Callable):
        op_name = name or func.__qualname__

        @functools.wraps(func)
        def sync_wrapped(*args: Any, **kwargs: Any):
            t0 = time.monotonic()
            result = func(*args, **kwargs)
            elapsed = time.monotonic() - t0
            if profiler:
                profiler.profile(op_name).record(elapsed)
            return result

        @functools.wraps(func)
        async def async_wrapped(*args: Any, **kwargs: Any):
            t0 = time.monotonic()
            result = await func(*args, **kwargs)
            elapsed = time.monotonic() - t0
            if profiler:
                profiler.profile(op_name).record(elapsed)
            return result

        if asyncio.iscoroutinefunction(func):
            return async_wrapped
        return sync_wrapped

    return wrapper
