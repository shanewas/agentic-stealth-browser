"""
Unit tests for MetricsCollector: timers, counters, redaction, Prometheus export.

Covers:
- Counter increment
- Timer aggregate stats
- Gauge setting
- Error recording
- Prometheus text format export
- Summary and correlation ID
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from production.metrics import MetricsCollector, metrics_for


class TestCounters:
    def test_increment_default(self):
        m = MetricsCollector()
        m.increment("requests")
        assert m.counters["requests"] == 1

    def test_increment_custom_value(self):
        m = MetricsCollector()
        m.increment("bytes", 1024)
        assert m.counters["bytes"] == 1024

    def test_increment_multiple(self):
        m = MetricsCollector()
        m.increment("errors")
        m.increment("errors")
        m.increment("errors")
        assert m.counters["errors"] == 3


class TestTimers:
    def test_record_time_basic(self):
        m = MetricsCollector()
        m.record_time("request", 0.5)
        t = m.timers["request"]
        assert t["count"] == 1
        assert t["sum"] == 0.5
        assert t["min"] == 0.5
        assert t["max"] == 0.5
        assert t["last"] == 0.5

    def test_record_time_aggregation(self):
        m = MetricsCollector()
        m.record_time("request", 1.0)
        m.record_time("request", 0.2)
        m.record_time("request", 3.0)
        t = m.timers["request"]
        assert t["count"] == 3
        assert t["sum"] == 4.2
        assert t["min"] == 0.2
        assert t["max"] == 3.0
        assert t["last"] == 3.0

    def test_multiple_timers_independent(self):
        m = MetricsCollector()
        m.record_time("a", 1.0)
        m.record_time("b", 2.0)
        assert m.timers["a"]["count"] == 1
        assert m.timers["b"]["count"] == 1


class TestGauges:
    def test_set_gauge(self):
        m = MetricsCollector()
        m.set_gauge("memory_mb", 256.5)
        assert m.gauges["memory_mb"] == 256.5

    def test_set_gauge_overwrites(self):
        m = MetricsCollector()
        m.set_gauge("cpu", 0.5)
        m.set_gauge("cpu", 0.8)
        assert m.gauges["cpu"] == 0.8


class TestErrors:
    def test_record_error(self):
        m = MetricsCollector()
        m.record_error("timeout", "connection timed out after 30s")
        assert len(m.errors) == 1
        assert m.errors[0]["type"] == "timeout"
        assert "connection timed out" in m.errors[0]["message"]
        assert "timestamp" in m.errors[0]

    def test_error_increments_counter(self):
        m = MetricsCollector()
        m.record_error("timeout", "msg")
        m.record_error("timeout", "msg")
        m.record_error("crash", "msg")
        assert m.counters["errors_timeout"] == 2
        assert m.counters["errors_crash"] == 1


class TestPrometheusExport:
    def test_export_has_correlation_id(self):
        m = MetricsCollector(correlation_id="abc123")
        output = m.get_prometheus_metrics()
        assert "abc123" in output
        assert "correlation_id" in output

    def test_export_includes_counters(self):
        m = MetricsCollector()
        m.increment("requests_total", 42)
        output = m.get_prometheus_metrics()
        assert "requests_total" in output
        assert "42" in output

    def test_export_includes_timers(self):
        m = MetricsCollector()
        m.record_time("request", 1.5)
        output = m.get_prometheus_metrics()
        assert "request_seconds_count" in output
        assert "request_seconds_sum" in output
        assert "1.5" in output

    def test_export_includes_gauges(self):
        m = MetricsCollector()
        m.set_gauge("memory_mb", 512.0)
        output = m.get_prometheus_metrics()
        assert "memory_mb" in output
        assert "512" in output


class TestSummary:
    def test_summary_includes_basic_fields(self):
        m = MetricsCollector(session_name="test-session")
        m.increment("requests_total", 10)
        m.record_error("timeout", "err")
        summary = m.get_summary()
        assert summary["session_name"] == "test-session"
        assert summary["total_requests"] == 10
        assert summary["errors"] == 1
        assert "uptime_seconds" in summary

    def test_summary_timer_averages(self):
        m = MetricsCollector()
        m.record_time("req", 1.0)
        m.record_time("req", 3.0)
        summary = m.get_summary()
        timers = summary["timers"]
        assert timers["req"]["avg"] == 2.0

    def test_summary_recent_errors(self):
        m = MetricsCollector()
        for i in range(10):
            m.record_error("type", f"error-{i}")
        summary = m.get_summary()
        assert len(summary["recent_errors"]) == 5  # last 5


class TestCorrelationId:
    def test_default_correlation_id(self):
        m = MetricsCollector()
        cid = m.get_correlation_id()
        assert isinstance(cid, str)
        assert len(cid) == 8

    def test_custom_correlation_id(self):
        m = MetricsCollector(correlation_id="fixed-id")
        assert m.get_correlation_id() == "fixed-id"
        assert m.correlation_id == "fixed-id"

    def test_set_correlation_id(self):
        m = MetricsCollector()
        m.set_correlation_id("new-id")
        assert m.get_correlation_id() == "new-id"


class TestMetricsForHelper:
    def test_metrics_for_creates_new_instance(self):
        a = metrics_for("ns-a")
        b = metrics_for("ns-b")
        assert a is not b
        a.increment("req")
        assert a.counters["req"] == 1
        assert b.counters.get("req", 0) == 0


class TestRedactionInSummary:
    def test_summary_no_sensitive_data(self):
        m = MetricsCollector()
        m.increment("requests_total", 5)
        summary = m.get_summary()
        assert "password" not in str(summary).lower()
