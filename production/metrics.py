"""
Basic Observability & Metrics for Agentic Stealth Browser
Lightweight, Prometheus-compatible metrics collection.
Phase 8 #87: added get_metrics_for_namespace helper for safe multi-instance isolation.
"""

import time
from datetime import datetime, timezone
from typing import Dict, Any
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class MetricsCollector:
    """Lightweight metrics collector.
    P2 perf + deprecation fix (#104 #58): use monotonic for uptime (avoids naive datetime),
    timezone-aware for error timestamps.
    """

    def __init__(self):
        self.counters: Dict[str, int] = defaultdict(int)
        self.timers: Dict[str, float] = {}
        self.gauges: Dict[str, float] = {}
        self.errors: list = []
        self.start_time = time.monotonic()  # P2: monotonic for reliable elapsed (perf/compat)

    def increment(self, name: str, value: int = 1):
        """Increment a counter."""
        self.counters[name] += value

    def record_time(self, name: str, duration: float):
        """Record a timing metric."""
        self.timers[name] = duration

    def set_gauge(self, name: str, value: float):
        """Set a gauge value."""
        self.gauges[name] = value

    def record_error(self, error_type: str, message: str):
        """Record an error occurrence."""
        self.errors.append({
            "type": error_type,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat()  # P2 #104: aware utc
        })
        self.increment(f"errors_{error_type}")

    def get_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []

        # Counters
        for name, value in self.counters.items():
            lines.append(f'# TYPE {name} counter')
            lines.append(f'{name} {value}')

        # Gauges
        for name, value in self.gauges.items():
            lines.append(f'# TYPE {name} gauge')
            lines.append(f'{name} {value}')

        # Timers (as gauges for now)
        for name, value in self.timers.items():
            lines.append(f'# TYPE {name}_seconds gauge')
            lines.append(f'{name}_seconds {value}')

        return "\n".join(lines)

    def get_summary(self) -> Dict[str, Any]:
        """Return human-readable summary."""
        uptime = time.monotonic() - self.start_time  # P2 #104/#58: monotonic delta (no datetime sub)

        return {
            "uptime_seconds": round(uptime, 1),
            "total_requests": self.counters.get("requests_total", 0),
            "errors": len(self.errors),
            "success_rate": round(
                (self.counters.get("requests_total", 0) - len(self.errors)) /
                max(1, self.counters.get("requests_total", 1)) * 100, 1
            ),
            "counters": dict(self.counters),
            "recent_errors": self.errors[-5:] if self.errors else []
        }


# Global metrics instance (single-process default)
# For #87 scalability: use get_metrics_for_namespace(ns) or MetricsCollector() per instance
metrics = MetricsCollector()


# P1 #87: easy per-namespace isolated collector (additive)
def metrics_for(ns): 
    return get_metrics_for_namespace(ns) if "get_metrics_for_namespace" in globals() else MetricsCollector()
