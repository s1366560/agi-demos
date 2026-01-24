"""
Agent execution metrics (T131).

This module provides metrics collection for agent operations,
tracking performance, usage patterns, and error rates.
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class MetricData:
    """Single metric data point."""

    value: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    labels: dict[str, str] = field(default_factory=dict)


class AgentMetrics:
    """
    Metrics collector for agent execution.

    Tracks:
    - Execution times
    - Success/failure rates
    - Tool usage patterns
    - Error frequencies
    """

    def __init__(self):
        """Initialize metrics collector."""
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._gauges: defaultdict[str, list[float]] = defaultdict(list)
        self._histograms: defaultdict[str, list[float]] = defaultdict(list)
        self._labels: dict[str, dict[str, str]] = {}

    def increment(self, name: str, value: int = 1, labels: dict[str, str] | None = None):
        """
        Increment a counter metric.

        Args:
            name: Metric name
            value: Value to increment by
            labels: Optional labels for the metric
        """
        key = self._make_key(name, labels)
        self._counters[key] += value
        self._labels[key] = labels or {}

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None):
        """
        Set a gauge metric.

        Args:
            name: Metric name
            value: Value to set
            labels: Optional labels for the metric
        """
        key = self._make_key(name, labels)
        self._gauges[key].append(value)
        self._labels[key] = labels or {}

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None):
        """
        Observe a value for a histogram metric.

        Args:
            name: Metric name
            value: Value to observe
            labels: Optional labels for the metric
        """
        key = self._make_key(name, labels)
        self._histograms[key].append(value)
        self._labels[key] = labels or {}

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> int:
        """Get counter value."""
        key = self._make_key(name, labels)
        return self._counters.get(key, 0)

    def get_gauge(self, name: str, labels: dict[str, str] | None = None) -> float:
        """Get latest gauge value."""
        key = self._make_key(name, labels)
        values = self._gauges.get(key, [])
        return values[-1] if values else 0.0

    def get_histogram_stats(
        self, name: str, labels: dict[str, str] | None = None
    ) -> dict[str, float] | None:
        """Get histogram statistics."""
        key = self._make_key(name, labels)
        values = self._histograms.get(key, [])
        if not values:
            return None

        sorted_values = sorted(values)
        count = len(sorted_values)
        total = sum(sorted_values)

        return {
            "count": count,
            "sum": total,
            "avg": total / count if count > 0 else 0,
            "min": sorted_values[0] if count > 0 else 0,
            "max": sorted_values[-1] if count > 0 else 0,
            "p50": sorted_values[int(count * 0.5)] if count > 0 else 0,
            "p95": sorted_values[int(count * 0.95)] if count > 0 else 0,
            "p99": sorted_values[int(count * 0.99)] if count > 0 else 0,
        }

    def _make_key(self, name: str, labels: dict[str, str] | None = None) -> str:
        """Create a key for a metric with labels."""
        if not labels:
            return name

        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def get_all_metrics(self) -> dict[str, Any]:
        """Get all metrics as a dictionary."""
        return {
            "counters": dict(self._counters),
            "gauges": {k: v[-1] if v else 0 for k, v in self._gauges.items()},
            "histograms": {k: self.get_histogram_stats(k) for k in self._histograms.keys()},
        }

    def reset(self):
        """Reset all metrics."""
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()
        self._labels.clear()


# Global metrics instance
agent_metrics = AgentMetrics()


def track_execution(operation_name: str):
    """
    Decorator to track execution time and success/failure.

    Args:
        operation_name: Name of the operation being tracked

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            success = True

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                logger.error(f"Error in {operation_name}: {e}")
                raise
            finally:
                duration = time.time() - start_time

                # Record metrics
                agent_metrics.observe(f"{operation_name}_duration", duration)
                agent_metrics.increment(f"{operation_name}_total")

                if success:
                    agent_metrics.increment(f"{operation_name}_success")
                else:
                    agent_metrics.increment(f"{operation_name}_failure")

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            success = True

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                logger.error(f"Error in {operation_name}: {e}")
                raise
            finally:
                duration = time.time() - start_time

                # Record metrics
                agent_metrics.observe(f"{operation_name}_duration", duration)
                agent_metrics.increment(f"{operation_name}_total")

                if success:
                    agent_metrics.increment(f"{operation_name}_success")
                else:
                    agent_metrics.increment(f"{operation_name}_failure")

        # Return appropriate wrapper based on function type
        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def get_metrics_summary() -> dict[str, Any]:
    """
    Get a summary of all collected metrics.

    Returns:
        Dictionary containing metrics summary
    """
    return agent_metrics.get_all_metrics()


def export_metrics() -> str:
    """
    Export metrics in Prometheus format.

    Returns:
        Metrics in Prometheus text format
    """
    lines = []

    # Export counters
    for key, value in agent_metrics._counters.items():
        labels = agent_metrics._labels.get(key, {})
        label_str = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}" if labels else ""
        lines.append(f"agent_counter_{key}{label_str} {value}")

    # Export gauges
    for key, values in agent_metrics._gauges.items():
        if values:
            labels = agent_metrics._labels.get(key, {})
            label_str = (
                "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}" if labels else ""
            )
            lines.append(f"agent_gauge_{key}{label_str} {values[-1]}")

    # Export histogram stats
    for key in agent_metrics._histograms.keys():
        stats = agent_metrics.get_histogram_stats(key)
        if stats:
            labels = agent_metrics._labels.get(key, {})
            label_str = (
                "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}" if labels else ""
            )

            lines.append(f"agent_histogram_{key}_count{label_str} {stats['count']}")
            lines.append(f"agent_histogram_{key}_sum{label_str} {stats['sum']}")
            lines.append(f"agent_histogram_{key}_avg{label_str} {stats['avg']}")

    return "\n".join(lines)


def get_metric_help() -> dict[str, str]:
    """
    Get help text for all metrics.

    Returns:
        Dictionary mapping metric names to descriptions
    """
    return {
        "work_plan_duration": "Time taken to generate work plans",
        "work_plan_success": "Number of successful work plan generations",
        "work_plan_failure": "Number of failed work plan generations",
        "tool_execution_duration": "Time taken to execute tools",
        "tool_execution_success": "Number of successful tool executions",
        "tool_execution_failure": "Number of failed tool executions",
        "agent_execution_duration": "Total time for agent execution",
        "agent_execution_success": "Number of successful agent executions",
        "agent_execution_failure": "Number of failed agent executions",
        "sse_connections_active": "Number of active SSE connections",
        "sse_messages_sent": "Number of SSE messages sent",
        "sse_errors": "Number of SSE errors",
    }
