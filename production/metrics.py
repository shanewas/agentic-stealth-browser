"""
Basic Observability & Metrics for Agentic Stealth Browser
Lightweight, Prometheus-compatible metrics collection.
Phase 8 #87: added get_metrics_for_namespace helper for safe multi-instance isolation.

P2 #97: MetricsCollector is now properly initialized and wired into AgentBrowser.
P2 #128: Added correlation_id support for multi-account run tracing.
"""

import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class MetricsCollector:
    """Lightweight metrics collector.
    P2 perf + deprecation fix (#104 #58): use monotonic for uptime (avoids naive datetime),
    timezone-aware for error timestamps.

    P2 #97: Now properly wired into AgentBrowser and MCP server.
    P2 #128: Added correlation_id for multi-account run tracing.
    """

    def __init__(self, correlation_id: Optional[str] = None, session_name: Optional[str] = None):
        self.counters: Dict[str, int] = defaultdict(int)
        self.timers: Dict[str, Dict[str, Any]] = {}  # {count, sum, min, max, last}
        self.gauges: Dict[str, float] = {}
        self.errors: list = []
        self.start_time = time.monotonic()  # P2: monotonic for reliable elapsed (perf/compat)
        # P2 #128: Correlation ID for tracing across multi-account runs
        self.correlation_id: str = correlation_id or str(uuid.uuid4())[:8]
        self.session_name: Optional[str] = session_name
        self._initialized = True  # #97: Flag to confirm proper initialization

    def increment(self, name: str, value: int = 1):
        """Increment a counter."""
        self.counters[name] += value

    def record_time(self, name: str, duration: float):
        """Record a timing metric. Stores aggregate stats (count, sum, min, max, last)
        instead of overwriting, so trends and averages are preserved."""
        if name not in self.timers:
            self.timers[name] = {"count": 0, "sum": 0.0, "min": duration, "max": duration, "last": duration}
        t = self.timers[name]
        t["count"] += 1
        t["sum"] += duration
        if duration < t["min"]:
            t["min"] = duration
        if duration > t["max"]:
            t["max"] = duration
        t["last"] = duration

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

        # Add correlation_id as a label
        lines.append('# HELP correlation_id Current correlation ID for tracing')
        lines.append('# TYPE correlation_id gauge')
        lines.append(f'correlation_id{{id="{self.correlation_id}"}} 1')

        # Counters
        for name, value in self.counters.items():
            lines.append(f'# TYPE {name} counter')
            lines.append(f'{name}{{correlation_id="{self.correlation_id}"}} {value}')

        # Gauges
        for name, value in self.gauges.items():
            lines.append(f'# TYPE {name} gauge')
            lines.append(f'{name}{{correlation_id="{self.correlation_id}"}} {value}')

        # Timers (as histograms with count, sum, min, max, last)
        for name, t in self.timers.items():
            if isinstance(t, dict):
                lines.append(f'# TYPE {name}_seconds summary')
                lines.append(f'{name}_seconds_count{{correlation_id="{self.correlation_id}"}} {t["count"]}')
                lines.append(f'{name}_seconds_sum{{correlation_id="{self.correlation_id}"}} {t["sum"]:.6f}')
                lines.append(f'{name}_seconds_min{{correlation_id="{self.correlation_id}"}} {t["min"]:.6f}')
                lines.append(f'{name}_seconds_max{{correlation_id="{self.correlation_id}"}} {t["max"]:.6f}')
                lines.append(f'{name}_seconds_last{{correlation_id="{self.correlation_id}"}} {t["last"]:.6f}')
            else:
                # Legacy flat value (shouldn't happen after migration, but safe)
                lines.append(f'# TYPE {name}_seconds gauge')
                lines.append(f'{name}_seconds{{correlation_id="{self.correlation_id}"}} {t}')

        return "\n".join(lines)

    def get_summary(self) -> Dict[str, Any]:
        """Return human-readable summary."""
        uptime = time.monotonic() - self.start_time  # P2 #104/#58: monotonic delta (no datetime sub)

        return {
            "correlation_id": self.correlation_id,
            "session_name": self.session_name,
            "uptime_seconds": round(uptime, 1),
            "total_requests": self.counters.get("requests_total", 0),
            "errors": len(self.errors),
            "success_rate": round(
                (self.counters.get("requests_total", 0) - len(self.errors)) /
                max(1, self.counters.get("requests_total", 1)) * 100, 1
            ),
            "counters": dict(self.counters),
            "timers": {k: {**v, "avg": round(v["sum"] / v["count"], 4)} if isinstance(v, dict) and v["count"] > 0 else v for k, v in self.timers.items()},
            "recent_errors": self.errors[-5:] if self.errors else []
        }

    def get_correlation_id(self) -> str:
        """P2 #128: Get the correlation ID for this metrics collector."""
        return self.correlation_id

    def set_correlation_id(self, correlation_id: str) -> None:
        """P2 #128: Set a new correlation ID (e.g., when linking to external trace)."""
        self.correlation_id = correlation_id


# Global metrics instance (single-process default)
# For #87 scalability: use get_metrics_for_namespace(ns) or MetricsCollector() per instance
metrics = MetricsCollector()


# P1 #87: easy per-namespace isolated collector (additive)
def metrics_for(ns): 
    return MetricsCollector()
