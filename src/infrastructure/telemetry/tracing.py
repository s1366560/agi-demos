"""OpenTelemetry tracing utilities.

This module provides decorators and helper functions for creating
and managing distributed traces.
"""

import functools
from collections.abc import Callable, Mapping
from typing import Any

from opentelemetry.trace import (
    NonRecordingSpan,
    Span,
    SpanContext,
    Status,
    StatusCode,
    get_current_span as _get_current_span,
)

from src.infrastructure.telemetry.config import get_tracer


def get_current_span() -> Span:
    """Get the current span.

    Returns:
        Current span (non-recording span if none exists)
    """
    try:
        span = _get_current_span()
        if span is None:
            # Return a non-recording span if there's no current span
            return NonRecordingSpan(SpanContext())
        return span
    except Exception:
        # Return a non-recording span if there's an error
        return NonRecordingSpan(SpanContext())


def get_trace_id() -> str | None:
    """Get the trace ID from the current span context.

    Returns:
        Trace ID as hex string or None if no active span
    """
    span = get_current_span()
    if isinstance(span, NonRecordingSpan):
        return None

    try:
        context = span.get_span_context()
        if context is None or context.trace_id == 0:
            return None
        return format(context.trace_id, "032x")
    except Exception:
        return None


def add_span_attributes(attributes: Mapping[str, Any]) -> None:
    """Add attributes to the current span.

    Args:
        attributes: Key-value pairs to add as span attributes
    """
    span = get_current_span()
    if not isinstance(span, NonRecordingSpan):
        for key, value in attributes.items():
            span.set_attribute(key, value)


def add_span_event(name: str, attributes: Mapping[str, Any] | None = None) -> None:
    """Add an event to the current span.

    Args:
        name: Event name
        attributes: Optional event attributes
    """
    span = get_current_span()
    if not isinstance(span, NonRecordingSpan):
        span.add_event(name, attributes or {})


def set_span_error(exception: Exception) -> None:
    """Record an exception and set the span status to error.

    Args:
        exception: The exception to record
    """
    span = get_current_span()
    if not isinstance(span, NonRecordingSpan):
        span.record_exception(exception)
        span.set_status(Status(StatusCode.ERROR, str(exception)))


def with_tracer(component_name: str, attributes: dict[str, Any] | None = None):
    """Decorator to add tracing to synchronous functions.

    Args:
        component_name: Name of the component/module
        attributes: Optional static attributes to add to the span

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer(component_name)
            if tracer is None:
                return func(*args, **kwargs)

            span_name = f"{component_name}.{func.__name__}"

            with tracer.start_as_current_span(span_name) as span:
                # Add static attributes
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)

                # Add function name
                span.set_attribute("function.name", func.__name__)

                try:
                    result = func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        return wrapper

    return decorator


def async_with_tracer(component_name: str, attributes: dict[str, Any] | None = None):
    """Decorator to add tracing to asynchronous functions.

    Args:
        component_name: Name of the component/module
        attributes: Optional static attributes to add to the span

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer(component_name)
            if tracer is None:
                return await func(*args, **kwargs)

            span_name = f"{component_name}.{func.__name__}"

            with tracer.start_as_current_span(span_name) as span:
                # Add static attributes
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)

                # Add function name
                span.set_attribute("function.name", func.__name__)

                try:
                    result = await func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        return wrapper

    return decorator
