"""Tests for Sandbox Monitoring Metrics System.

Tests the metrics collection, storage, and export functionality.
"""

from src.domain.model.sandbox.metrics import (
    HistogramBucket,
    HistogramMetric,
    Metric,
    MetricLabel,
    MetricsCollector,
    MetricType,
    PrometheusExporter,
    SandboxMetricNames,
    SandboxMetrics,
    StatsDExporter,
)


class TestMetric:
    """Tests for Metric dataclass."""

    def test_create_metric(self) -> None:
        """Should create a metric with default values."""
        metric = Metric(name="test_counter", type=MetricType.COUNTER, value=1.0)

        assert metric.name == "test_counter"
        assert metric.type == MetricType.COUNTER
        assert metric.value == 1.0
        assert metric.labels == []
        assert metric.help_text == ""

    def test_create_metric_with_labels(self) -> None:
        """Should create a metric with labels."""
        labels = [MetricLabel("sandbox_id", "sb-123"), MetricLabel("status", "running")]
        metric = Metric(
            name="test_gauge",
            type=MetricType.GAUGE,
            value=42.0,
            labels=labels,
        )

        assert len(metric.labels) == 2
        assert metric.labels[0].name == "sandbox_id"
        assert metric.labels[0].value == "sb-123"

    def test_create_metric_with_help(self) -> None:
        """Should create a metric with help text."""
        metric = Metric(
            name="test_counter",
            type=MetricType.COUNTER,
            value=1.0,
            help_text="Total number of requests",
        )

        assert metric.help_text == "Total number of requests"


class TestPrometheusExporter:
    """Tests for PrometheusExporter."""

    def test_export_counter(self) -> None:
        """Should export a counter metric in Prometheus format."""
        exporter = PrometheusExporter()
        metric = Metric(
            name="sandbox_requests_total",
            type=MetricType.COUNTER,
            value=42.0,
            labels=[MetricLabel("endpoint", "/execute")],
        )

        result = exporter.export([metric])

        assert "# HELP sandbox_requests_total" not in result  # No help text
        assert "sandbox_requests_total" in result
        assert "42" in result
        assert 'endpoint="/execute"' in result

    def test_export_gauge(self) -> None:
        """Should export a gauge metric in Prometheus format."""
        exporter = PrometheusExporter()
        metric = Metric(
            name="sandbox_active_count",
            type=MetricType.GAUGE,
            value=5.0,
        )

        result = exporter.export([metric])

        assert "sandbox_active_count" in result
        assert "5" in result
        assert "GAUGE" in result or "gauge" in result.lower()

    def test_export_histogram(self) -> None:
        """Should export a histogram metric in Prometheus format."""
        exporter = PrometheusExporter()
        histogram = HistogramMetric(
            name="sandbox_execution_duration_ms",
            type=MetricType.HISTOGRAM,
            value=0,
            buckets=[
                HistogramBucket(10.0, 5),
                HistogramBucket(50.0, 8),
                HistogramBucket(100.0, 10),
                HistogramBucket(float("inf"), 10),
            ],
            sum=450.0,
            count=10,
        )

        result = exporter.export([histogram])

        assert "sandbox_execution_duration_ms" in result
        assert "le=" in result  # Prometheus uses le= for bucket labels
        assert "10" in result
        assert "_count" in result
        assert "_sum" in result

    def test_export_multiple_metrics(self) -> None:
        """Should export multiple metrics."""
        exporter = PrometheusExporter()
        metrics = [
            Metric(name="metric1", type=MetricType.COUNTER, value=1.0),
            Metric(name="metric2", type=MetricType.GAUGE, value=2.0),
        ]

        result = exporter.export(metrics)

        assert "metric1" in result
        assert "metric2" in result

    def test_export_with_help_text(self) -> None:
        """Should include HELP line when help text is present."""
        exporter = PrometheusExporter()
        metric = Metric(
            name="test_metric",
            type=MetricType.COUNTER,
            value=1.0,
            help_text="A test metric",
        )

        result = exporter.export([metric])

        assert "# HELP test_metric A test metric" in result


class TestStatsDExporter:
    """Tests for StatsDExporter."""

    def test_export_counter(self) -> None:
        """Should export a counter in StatsD format."""
        exporter = StatsDExporter()
        metric = Metric(
            name="sandbox.requests",
            type=MetricType.COUNTER,
            value=1.0,
        )

        result = exporter.export([metric])

        # StatsD sanitizes dots to underscores
        assert "sandbox_requests" in result
        assert "|c" in result  # StatsD counter suffix

    def test_export_gauge(self) -> None:
        """Should export a gauge in StatsD format."""
        exporter = StatsDExporter()
        metric = Metric(
            name="sandbox.active",
            type=MetricType.GAUGE,
            value=5.0,
        )

        result = exporter.export([metric])

        # StatsD sanitizes dots to underscores
        assert "sandbox_active" in result
        assert "|g" in result  # StatsD gauge suffix

    def test_export_timing(self) -> None:
        """Should export a timing in StatsD format."""
        exporter = StatsDExporter()
        metric = Metric(
            name="sandbox.execution_time",
            type=MetricType.HISTOGRAM,
            value=123.0,
        )

        result = exporter.export([metric])

        # StatsD sanitizes dots to underscores
        assert "sandbox_execution_time" in result
        assert "|ms" in result  # StatsD timing suffix

    def test_export_with_labels(self) -> None:
        """Should convert labels to StatsD tags."""
        exporter = StatsDExporter()
        metric = Metric(
            name="sandbox.requests",
            type=MetricType.COUNTER,
            value=1.0,
            labels=[MetricLabel("sandbox_id", "sb-123"), MetricLabel("status", "ok")],
        )

        result = exporter.export([metric])

        # StatsD sanitizes dots to underscores
        assert "sandbox_requests" in result
        assert "#sandbox_id:sb-123" in result or "sandbox_id=sb-123" in result


class TestMetricsCollector:
    """Tests for MetricsCollector."""

    def test_increment_counter(self) -> None:
        """Should increment a counter metric."""
        collector = MetricsCollector()

        collector.increment("requests_total")

        metric = collector.get_metric("requests_total")
        assert metric is not None
        assert metric.value == 1.0
        assert metric.type == MetricType.COUNTER

    def test_increment_counter_with_value(self) -> None:
        """Should increment counter by specific value."""
        collector = MetricsCollector()

        collector.increment("bytes_total", value=1024.0)

        metric = collector.get_metric("bytes_total")
        assert metric.value == 1024.0

    def test_increment_counter_accumulates(self) -> None:
        """Should accumulate counter values."""
        collector = MetricsCollector()

        collector.increment("requests_total")
        collector.increment("requests_total", value=2.0)
        collector.increment("requests_total", value=3.0)

        metric = collector.get_metric("requests_total")
        assert metric.value == 6.0

    def test_gauge_set_value(self) -> None:
        """Should set a gauge value."""
        collector = MetricsCollector()

        collector.gauge("active_connections", 42.0)

        metric = collector.get_metric("active_connections")
        assert metric is not None
        assert metric.value == 42.0
        assert metric.type == MetricType.GAUGE

    def test_gauge_overwrites(self) -> None:
        """Should overwrite previous gauge value."""
        collector = MetricsCollector()

        collector.gauge("temperature", 20.0)
        collector.gauge("temperature", 25.0)

        metric = collector.get_metric("temperature")
        assert metric.value == 25.0

    def test_observe_histogram(self) -> None:
        """Should observe values for histogram."""
        collector = MetricsCollector()

        collector.observe("response_time_ms", 10.0)
        collector.observe("response_time_ms", 20.0)
        collector.observe("response_time_ms", 30.0)

        histogram = collector.get_metric("response_time_ms")
        assert histogram is not None
        assert histogram.type == MetricType.HISTOGRAM
        assert histogram.count == 3

    def test_observe_with_labels(self) -> None:
        """Should store metrics with labels."""
        collector = MetricsCollector()

        collector.increment("requests_total", labels={"endpoint": "/api"})

        metric = collector.get_metric("requests_total")
        assert metric is not None
        assert any(l.name == "endpoint" and l.value == "/api" for l in metric.labels)

    def test_timing_records_duration(self) -> None:
        """Should record timing observations."""
        collector = MetricsCollector()

        collector.timing("operation_duration_ms", 123.45)

        histogram = collector.get_metric("operation_duration_ms")
        assert histogram is not None
        assert histogram.count == 1

    def test_get_all_metrics(self) -> None:
        """Should return all collected metrics."""
        collector = MetricsCollector()

        collector.increment("counter1")
        collector.gauge("gauge1", 1.0)
        collector.increment("counter2")

        metrics = collector.get_all_metrics()
        assert len(metrics) == 3

    def test_clear_metrics(self) -> None:
        """Should clear all metrics."""
        collector = MetricsCollector()

        collector.increment("counter1")
        collector.gauge("gauge1", 1.0)

        collector.clear()

        assert collector.get_metric("counter1") is None
        assert collector.get_metric("gauge1") is None
        assert len(collector.get_all_metrics()) == 0

    def test_get_nonexistent_metric(self) -> None:
        """Should return None for nonexistent metric."""
        collector = MetricsCollector()

        metric = collector.get_metric("nonexistent")
        assert metric is None


class TestSandboxMetrics:
    """Tests for SandboxMetrics."""

    def test_record_sandbox_created(self) -> None:
        """Should record sandbox creation."""
        collector = MetricsCollector()
        sandbox_metrics = SandboxMetrics(collector)

        sandbox_metrics.record_sandbox_created("sb-123")

        metric = collector.get_metric(SandboxMetricNames.CREATED_TOTAL)
        assert metric is not None
        assert metric.value == 1.0

    def test_record_sandbox_started(self) -> None:
        """Should record sandbox start with timing."""
        collector = MetricsCollector()
        sandbox_metrics = SandboxMetrics(collector)

        sandbox_metrics.record_sandbox_started("sb-123", 150.5)

        # Check startup time histogram
        histogram = collector.get_metric(SandboxMetricNames.STARTUP_TIME_MS)
        assert histogram is not None
        assert histogram.count == 1

        # Check active count gauge
        gauge = collector.get_metric(SandboxMetricNames.ACTIVE_COUNT)
        assert gauge is not None
        assert gauge.value == 1.0

    def test_record_sandbox_stopped(self) -> None:
        """Should record sandbox stop with uptime."""
        collector = MetricsCollector()
        sandbox_metrics = SandboxMetrics(collector)

        sandbox_metrics.record_sandbox_stopped("sb-123", 5000.0)

        # Check uptime histogram
        histogram = collector.get_metric(SandboxMetricNames.UPTIME_MS)
        assert histogram is not None
        assert histogram.count == 1

    def test_record_sandbox_error(self) -> None:
        """Should record sandbox error."""
        collector = MetricsCollector()
        sandbox_metrics = SandboxMetrics(collector)

        sandbox_metrics.record_sandbox_error("sb-123", "timeout")

        metric = collector.get_metric(SandboxMetricNames.ERRORS_TOTAL)
        assert metric is not None
        # Check labels contain error type
        assert any(l.name == "error_type" and l.value == "timeout" for l in metric.labels)

    def test_record_execution_time(self) -> None:
        """Should record operation execution time."""
        collector = MetricsCollector()
        sandbox_metrics = SandboxMetrics(collector)

        sandbox_metrics.record_execution_time("sb-123", "execute_code", 45.2)

        histogram = collector.get_metric(SandboxMetricNames.OPERATION_DURATION_MS)
        assert histogram is not None
        assert histogram.count == 1

    def test_record_resource_usage(self) -> None:
        """Should record resource usage."""
        collector = MetricsCollector()
        sandbox_metrics = SandboxMetrics(collector)

        sandbox_metrics.record_resource_usage("sb-123", cpu_percent=75.5, memory_mb=512.0)

        cpu_gauge = collector.get_metric(SandboxMetricNames.CPU_PERCENT)
        assert cpu_gauge is not None
        assert cpu_gauge.value == 75.5

        memory_gauge = collector.get_metric(SandboxMetricNames.MEMORY_MB)
        assert memory_gauge is not None
        assert memory_gauge.value == 512.0

    def test_multiple_sandboxes_tracked(self) -> None:
        """Should track metrics for multiple sandboxes."""
        collector = MetricsCollector()
        sandbox_metrics = SandboxMetrics(collector)

        sandbox_metrics.record_sandbox_started("sb-1", 100.0)
        sandbox_metrics.record_sandbox_started("sb-2", 150.0)

        gauge = collector.get_metric(SandboxMetricNames.ACTIVE_COUNT)
        assert gauge.value == 2.0

        sandbox_metrics.record_sandbox_stopped("sb-1", 1000.0)

        gauge = collector.get_metric(SandboxMetricNames.ACTIVE_COUNT)
        assert gauge.value == 1.0


class TestMetricsIntegration:
    """Integration tests for metrics system."""

    def test_export_to_prometheus(self) -> None:
        """Should export collected metrics to Prometheus format."""
        collector = MetricsCollector()
        exporter = PrometheusExporter()

        collector.increment("requests_total", labels={"endpoint": "/api"})
        collector.gauge("active_count", 5.0)

        metrics = collector.get_all_metrics()
        result = exporter.export(metrics)

        assert "requests_total" in result
        assert "active_count" in result
        assert "/api" in result

    def test_export_to_statsd(self) -> None:
        """Should export collected metrics to StatsD format."""
        collector = MetricsCollector()
        exporter = StatsDExporter()

        collector.increment("requests_total")
        collector.gauge("active_count", 5.0)

        metrics = collector.get_all_metrics()
        result = exporter.export(metrics)

        assert "|c" in result  # Counter
        assert "|g" in result  # Gauge
