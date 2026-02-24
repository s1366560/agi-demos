"""Sandbox Monitoring Metrics System.

This module provides a comprehensive metrics collection and export system
for sandbox operations, supporting Prometheus and StatsD formats.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


# Metric name constants for SandboxMetrics
class SandboxMetricNames:
    """Constants for sandbox metric names."""

    CREATED_TOTAL = "sandbox_created_total"
    STARTUP_TIME_MS = "sandbox_startup_time_ms"
    ACTIVE_COUNT = "sandbox_active_count"
    UPTIME_MS = "sandbox_uptime_ms"
    ERRORS_TOTAL = "sandbox_errors_total"
    OPERATION_DURATION_MS = "sandbox_operation_duration_ms"
    CPU_PERCENT = "sandbox_cpu_percent"
    MEMORY_MB = "sandbox_memory_mb"

    LABEL_SANDBOX_ID = "sandbox_id"
    LABEL_ERROR_TYPE = "error_type"
    LABEL_OPERATION = "operation"


# Default histogram buckets
DEFAULT_LATENCY_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
LATENCY_MS_BUCKETS: list[float] = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]


class MetricType(Enum):
    """Types of metrics."""

    COUNTER = "counter"  # Monotonically increasing value
    GAUGE = "gauge"  # Value that can go up or down
    HISTOGRAM = "histogram"  # Distribution of values
    SUMMARY = "summary"  # Similar to histogram with quantiles


@dataclass
class MetricLabel:
    """A label/dimension for a metric."""

    name: str
    value: str


@dataclass
class Metric:
    """A single metric data point."""

    name: str
    type: MetricType
    value: float
    labels: list[MetricLabel] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    help_text: str = ""


@dataclass
class HistogramBucket:
    """A histogram bucket."""

    upper_bound: float
    count: int


@dataclass
class HistogramMetric(Metric):
    """A histogram metric with buckets."""

    buckets: list[HistogramBucket] = field(default_factory=list)
    sum: float = 0.0
    count: int = 0


class MetricsExporter(ABC):
    """Abstract base for metrics exporters."""

    @abstractmethod
    def export(self, metrics: list[Metric]) -> str:
        """Export metrics to a specific format."""


class PrometheusExporter(MetricsExporter):
    """Export metrics in Prometheus text format."""

    # Default histogram buckets for latency metrics
    DEFAULT_BUCKETS = DEFAULT_LATENCY_BUCKETS

    def export(self, metrics: list[Metric]) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        processed_names = set()

        for metric in metrics:
            # Add HELP line if help text exists
            if metric.help_text and metric.name not in processed_names:
                lines.append(f"# HELP {metric.name} {metric.help_text}")

            # Add TYPE line
            if metric.name not in processed_names:
                type_str = metric.type.value.lower()
                if metric.type == MetricType.HISTOGRAM:
                    type_str = "histogram"
                lines.append(f"# TYPE {metric.name} {type_str}")
                processed_names.add(metric.name)

            # Format labels
            label_str = self._format_labels(metric.labels)

            if isinstance(metric, HistogramMetric):
                # Export histogram buckets
                for bucket in metric.buckets:
                    bucket_label = label_str.replace("}", ',le="' + str(bucket.upper_bound) + '"}')
                    if bucket_label == "":
                        bucket_label = '{le="' + str(bucket.upper_bound) + '"}'
                    lines.append(f"{metric.name}_bucket{bucket_label} {bucket.count}")

                # Add +Inf bucket
                inf_label = label_str.replace("}", ',le="+Inf"}')
                if inf_label == "":
                    inf_label = '{le="+Inf"}'
                lines.append(f"{metric.name}_bucket{inf_label} {metric.count}")
                lines.append(f"{metric.name}_sum{label_str} {metric.sum}")
                lines.append(f"{metric.name}_count{label_str} {metric.count}")
            else:
                lines.append(f"{metric.name}{label_str} {metric.value}")

        return "\n".join(lines) + "\n"

    def _format_labels(self, labels: list[MetricLabel]) -> str:
        """Format labels for Prometheus format."""
        if not labels:
            return ""
        label_pairs = [f'{label.name}="{label.value}"' for label in labels]
        return "{" + ",".join(label_pairs) + "}"


class StatsDExporter(MetricsExporter):
    """Export metrics in StatsD format."""

    def export(self, metrics: list[Metric]) -> str:
        """Export metrics in StatsD format."""
        lines = []

        for metric in metrics:
            # Determine metric type suffix
            if metric.type == MetricType.COUNTER:
                suffix = "|c"
            elif metric.type == MetricType.GAUGE:
                suffix = "|g"
            elif metric.type == MetricType.HISTOGRAM:
                suffix = "|ms"
            else:
                suffix = "|g"

            # Format tags/labels
            tag_str = ""
            if metric.labels:
                tags = [f"{label.name}:{label.value}" for label in metric.labels]
                # Datadog style tags
                tag_str = "|#" + ",".join(tags)

            # Sanitize metric name (replace dots with underscores)
            sanitized_name = metric.name.replace(".", "_").replace(":", "_")

            lines.append(f"{sanitized_name}:{metric.value}{suffix}{tag_str}")

        return "\n".join(lines) + "\n"


class MetricsCollector:
    """Collects and stores sandbox metrics."""

    def __init__(self) -> None:
        """Initialize the metrics collector."""
        self._metrics: dict[str, Metric] = {}
        self._histograms: dict[str, HistogramMetric] = {}
        self._histogram_buckets: dict[str, list[float]] = {
            "default": DEFAULT_LATENCY_BUCKETS,
            "latency_ms": LATENCY_MS_BUCKETS,
        }

    def _make_key(self, name: str, labels: dict[str, str] | None) -> str:
        """Create a unique key for a metric with labels."""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def _labels_to_list(self, labels: dict[str, str] | None) -> list[MetricLabel]:
        """Convert label dict to list of MetricLabel objects."""
        if not labels:
            return []
        return [MetricLabel(k, v) for k, v in sorted(labels.items())]

    def increment(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ) -> None:
        """Increment a counter metric."""
        key = self._make_key(name, labels)
        current = self._metrics.get(key)

        if current:
            current.value += value
        else:
            self._metrics[key] = Metric(
                name=name,
                type=MetricType.COUNTER,
                value=value,
                labels=self._labels_to_list(labels),
            )

    def gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Set a gauge metric value."""
        key = self._make_key(name, labels)

        self._metrics[key] = Metric(
            name=name,
            type=MetricType.GAUGE,
            value=value,
            labels=self._labels_to_list(labels),
        )

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Observe a value for a histogram/summary."""
        key = self._make_key(name, labels)
        histogram = self._histograms.get(key)

        if histogram is None:
            # Get buckets for this metric
            bucket_values = self._histogram_buckets.get(name, self._histogram_buckets["default"])
            buckets = [HistogramBucket(b, 0) for b in bucket_values]

            histogram = HistogramMetric(
                name=name,
                type=MetricType.HISTOGRAM,
                value=0,
                labels=self._labels_to_list(labels),
                buckets=buckets,
            )
            self._histograms[key] = histogram

        # Update histogram
        histogram.count += 1
        histogram.sum += value

        # Update bucket counts
        for bucket in histogram.buckets:
            if value <= bucket.upper_bound:
                bucket.count += 1

    def timing(self, name: str, duration_ms: float, labels: dict[str, str] | None = None) -> None:
        """Record a timing observation."""
        self.observe(name, duration_ms, labels)

    def get_metric(self, name: str, labels: dict[str, str] | None = None) -> Metric | None:
        """Get a metric by name."""
        key = self._make_key(name, labels)

        # Check regular metrics
        if key in self._metrics:
            return self._metrics[key]

        # Check histograms
        if key in self._histograms:
            return self._histograms[key]

        # If no labels specified, try to find any metric with this name
        if labels is None:
            # Check regular metrics
            for _metric_key, metric in self._metrics.items():
                if metric.name == name:
                    return metric

            # Check histograms
            for _metric_key, histogram in self._histograms.items():
                if histogram.name == name:
                    return histogram

        return None

    def get_all_metrics(self) -> list[Metric]:
        """Get all collected metrics."""
        all_metrics = list(self._metrics.values())

        # Convert histograms to plain metrics for export
        for histogram in self._histograms.values():
            all_metrics.append(histogram)

        return all_metrics

    def clear(self) -> None:
        """Clear all metrics."""
        self._metrics.clear()
        self._histograms.clear()


class SandboxMetrics:
    """Pre-defined metrics for sandbox operations."""

    def __init__(self, collector: MetricsCollector | None = None) -> None:
        """Initialize sandbox metrics with a collector."""
        self._collector = collector or MetricsCollector()

    def record_sandbox_created(self, sandbox_id: str) -> None:
        """Record a sandbox creation event."""
        self._collector.increment(
            SandboxMetricNames.CREATED_TOTAL,
            labels={SandboxMetricNames.LABEL_SANDBOX_ID: sandbox_id},
        )

    def record_sandbox_started(self, sandbox_id: str, startup_time_ms: float) -> None:
        """Record a sandbox start event."""
        self._collector.timing(
            SandboxMetricNames.STARTUP_TIME_MS,
            startup_time_ms,
            labels={SandboxMetricNames.LABEL_SANDBOX_ID: sandbox_id},
        )

        # Track active count
        current = self._collector.get_metric(SandboxMetricNames.ACTIVE_COUNT)
        current_value = current.value if current else 0
        self._collector.gauge(SandboxMetricNames.ACTIVE_COUNT, current_value + 1)

    def record_sandbox_stopped(self, sandbox_id: str, uptime_ms: float) -> None:
        """Record a sandbox stop event."""
        self._collector.timing(
            SandboxMetricNames.UPTIME_MS,
            uptime_ms,
            labels={SandboxMetricNames.LABEL_SANDBOX_ID: sandbox_id},
        )

        # Decrement active count
        current = self._collector.get_metric(SandboxMetricNames.ACTIVE_COUNT)
        current_value = current.value if current else 0
        self._collector.gauge(SandboxMetricNames.ACTIVE_COUNT, max(0, current_value - 1))

    def record_sandbox_error(self, sandbox_id: str, error_type: str) -> None:
        """Record a sandbox error."""
        self._collector.increment(
            SandboxMetricNames.ERRORS_TOTAL,
            labels={
                SandboxMetricNames.LABEL_SANDBOX_ID: sandbox_id,
                SandboxMetricNames.LABEL_ERROR_TYPE: error_type,
            },
        )

    def record_execution_time(self, sandbox_id: str, operation: str, duration_ms: float) -> None:
        """Record an operation execution time."""
        self._collector.timing(
            SandboxMetricNames.OPERATION_DURATION_MS,
            duration_ms,
            labels={
                SandboxMetricNames.LABEL_SANDBOX_ID: sandbox_id,
                SandboxMetricNames.LABEL_OPERATION: operation,
            },
        )

    def record_resource_usage(self, sandbox_id: str, cpu_percent: float, memory_mb: float) -> None:
        """Record resource usage."""
        self._collector.gauge(
            SandboxMetricNames.CPU_PERCENT,
            cpu_percent,
            labels={SandboxMetricNames.LABEL_SANDBOX_ID: sandbox_id},
        )
        self._collector.gauge(
            SandboxMetricNames.MEMORY_MB,
            memory_mb,
            labels={SandboxMetricNames.LABEL_SANDBOX_ID: sandbox_id},
        )

    @property
    def collector(self) -> MetricsCollector:
        """Get the underlying collector."""
        return self._collector
