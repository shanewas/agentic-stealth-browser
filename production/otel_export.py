"""
Prometheus & OpenTelemetry Export Examples (#159)

This module provides examples and utilities for exporting metrics
to Prometheus and OpenTelemetry for production monitoring.
"""

from production.metrics import MetricsCollector


def get_prometheus_metrics_text(metrics: MetricsCollector) -> str:
    """Export metrics in Prometheus text exposition format.

    This is already implemented in MetricsCollector.get_prometheus_metrics().
    This function provides a more complete example with additional labels.

    Usage:
        from production.otel_export import get_prometheus_metrics_text
        text = get_prometheus_metrics_text(browser.metrics)
        # Serve via HTTP at /metrics endpoint
    """
    return metrics.get_prometheus_metrics()


class PrometheusExporter:
    """Helper for serving metrics to Prometheus.

    Example usage:
        from production.otel_export import PrometheusExporter

        exporter = PrometheusExporter(metrics_collector)
        exporter.start_http_server(port=9090)
    """

    def __init__(self, metrics: MetricsCollector, port: int = 9090):
        self.metrics = metrics
        self.port = port
        self._server = None

    def start_http_server(self) -> None:
        """Start a simple HTTP server to serve Prometheus metrics."""
        try:
            from http.server import HTTPServer, BaseHTTPRequestHandler

            metrics = self.metrics

            class MetricsHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path == "/metrics":
                        self.send_response(200)
                        self.send_header("Content-Type", "text/plain")
                        self.end_headers()
                        self.wfile.write(metrics.get_prometheus_metrics().encode())
                    elif self.path == "/health":
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        summary = metrics.get_summary()
                        import json

                        self.wfile.write(json.dumps(summary).encode())
                    else:
                        self.send_response(404)
                        self.end_headers()

                def log_message(self, format, *args):
                    pass  # Suppress request logs

            self._server = HTTPServer(("0.0.0.0", self.port), MetricsHandler)
            print(f"Prometheus metrics server started on port {self.port}")
            print(f"  Metrics: http://localhost:{self.port}/metrics")
            print(f"  Health:  http://localhost:{self.port}/health")

            # Run in a thread
            import threading

            thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            thread.start()

        except ImportError:
            print("http.server not available, cannot start Prometheus server")
        except Exception as e:
            print(f"Failed to start Prometheus server: {e}")

    def stop(self) -> None:
        """Stop the HTTP server."""
        if self._server:
            self._server.shutdown()
            self._server = None


class OpenTelemetryExporter:
    """Helper for exporting metrics to OpenTelemetry.

    Requires: pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-prometheus

    Example usage:
        from production.otel_export import OpenTelemetryExporter

        exporter = OpenTelemetryExporter(metrics_collector)
        exporter.export()
    """

    def __init__(self, metrics: MetricsCollector):
        self.metrics = metrics
        self._initialized = False

    def _ensure_initialized(self) -> bool:
        """Initialize OpenTelemetry if not already done."""
        if self._initialized:
            return True

        try:
            from opentelemetry import metrics as otel_metrics
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.exporter.prometheus import PrometheusMetricReader

            # Create a meter provider with Prometheus reader
            reader = PrometheusMetricReader()
            provider = MeterProvider(metric_readers=[reader])
            otel_metrics.set_meter_provider(provider)

            self._meter = otel_metrics.get_meter("agentic_stealth_browser")
            self._initialized = True
            return True

        except ImportError:
            print("OpenTelemetry packages not installed.")
            print(
                "Install with: pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-prometheus"
            )
            return False
        except Exception as e:
            print(f"Failed to initialize OpenTelemetry: {e}")
            return False

    def export(self) -> bool:
        """Export current metrics to OpenTelemetry."""
        if not self._ensure_initialized():
            return False

        try:
            summary = self.metrics.get_summary()

            # Create/Update gauges
            uptime_gauge = self._meter.create_gauge("browser.uptime_seconds")
            uptime_gauge.set(summary["uptime_seconds"])

            success_rate_gauge = self._meter.create_gauge(
                "browser.success_rate_percent"
            )
            success_rate_gauge.set(summary["success_rate"])

            error_count_gauge = self._meter.create_gauge("browser.errors_total")
            error_count_gauge.set(summary["errors"])

            # Create counters
            requests_counter = self._meter.create_counter("browser.requests_total")
            requests_counter.add(summary["total_requests"])

            return True

        except Exception as e:
            print(f"Failed to export metrics: {e}")
            return False


# === Docker Compose Example ===

DOCKER_COMPOSE_EXAMPLE = """
# docker-compose.yml for running with Prometheus + Grafana
version: '3.8'

services:
  stealth-browser:
    build: .
    ports:
      - "9090:9090"  # Prometheus metrics endpoint
    environment:
      - STEALTH_HEADLESS=true
      - STEALTH_REGION=us

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9091:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana-storage:/var/lib/grafana

volumes:
  grafana-storage:
"""

PROMETHEUS_CONFIG = """
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'stealth-browser'
    static_configs:
      - targets: ['stealth-browser:9090']
"""
