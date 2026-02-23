"""OpenTelemetry metrics utilities.

This module provides functions for creating and recording metrics
using OpenTelemetry Metrics API.
"""

from typing import Any, Callable, List, Mapping, Optional

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram, ObservableGauge

from src.infrastructure.telemetry.config import get_meter as _get_meter


def get_meter(instrumentation_name: str = "memstack-telemetry") -> Optional[metrics.Meter]:
    """Get a meter for the given instrumentation name.

    Args:
        instrumentation_name: Name of the instrumented module

    Returns:
        Meter instance or None if telemetry is disabled
    """
    return _get_meter(instrumentation_name)


def create_counter(
    name: str,
    description: str,
    unit: str = "",
    attributes: Optional[Mapping[str, Any]] = None,
) -> Optional[Counter]:
    """Create a counter metric.

    Args:
        name: Metric name
        description: Metric description
        unit: Metric unit (e.g., "requests", "bytes")
        attributes: Optional default attributes

    Returns:
        Counter instance or None if telemetry is disabled
    """
    meter = get_meter()
    if meter is None:
        return None

    return meter.create_counter(
        name=name,
        description=description,
        unit=unit,
    )


def create_histogram(
    name: str,
    description: str,
    unit: str = "",
    boundaries: Optional[List[float]] = None,
) -> Optional[Histogram]:
    """Create a histogram metric.

    Args:
        name: Metric name
        description: Metric description
        unit: Metric unit (e.g., "ms", "s")
        boundaries: Optional bucket boundaries

    Returns:
        Histogram instance or None if telemetry is disabled
    """
    meter = get_meter()
    if meter is None:
        return None

    return meter.create_histogram(
        name=name,
        description=description,
        unit=unit,
    )


def create_gauge(
    name: str,
    description: str,
    callbacks: Optional[List[Callable[[metrics.CallbackOptions], metrics.Observation]]] = None,
    unit: str = "",
) -> Optional[ObservableGauge]:
    """Create an observable gauge metric.

    Args:
        name: Metric name
        description: Metric description
        callbacks: List of callback functions that return observations
        unit: Metric unit

    Returns:
        ObservableGauge instance or None if telemetry is disabled
    """
    meter = get_meter()
    if meter is None:
        return None

    if callbacks is None:
        callbacks = []

    return meter.create_observable_gauge(
        name=name,
        description=description,
        callbacks=callbacks,
        unit=unit,
    )


def increment_counter(
    name: str,
    description: str,
    amount: int = 1,
    attributes: Optional[Mapping[str, Any]] = None,
) -> None:
    """Increment a counter metric.

    Args:
        name: Metric name
        description: Metric description
        amount: Amount to increment by
        attributes: Metric attributes
    """
    counter = create_counter(name, description)
    if counter is not None:
        counter.add(amount, attributes or {})


def record_histogram_value(
    name: str,
    description: str,
    value: float,
    attributes: Optional[Mapping[str, Any]] = None,
) -> None:
    """Record a value to a histogram metric.

    Args:
        name: Metric name
        description: Metric description
        value: Value to record
        attributes: Metric attributes
    """
    histogram = create_histogram(name, description)
    if histogram is not None:
        histogram.record(value, attributes or {})


def set_gauge(
    name: str,
    description: str,
    value: float,
    unit: str = "",
) -> None:
    """Set a gauge metric value.

    Note: OpenTelemetry gauges are observable and use callbacks.
    This is a simplified interface for basic use cases.

    Args:
        name: Metric name
        description: Metric description
        value: Current gauge value (will be wrapped in callback)
        unit: Metric unit
    """
    # Store the value in a closure for the callback
    _gauge_state = {"value": value}

    def callback(options: metrics.CallbackOptions) -> metrics.Observation:
        return metrics.Observation(value, {})

    create_gauge(name, description, [callback], unit)
