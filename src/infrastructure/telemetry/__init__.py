"""OpenTelemetry integration for MemStack.

This module provides distributed tracing, metrics, and logging
instrumentation for the MemStack application.
"""

from src.infrastructure.telemetry.config import (
    configure_telemetry,
    get_meter,
    get_tracer,
    shutdown_telemetry,
)
from src.infrastructure.telemetry.decorators import (
    async_with_tracer,
    with_tracer,
)
from src.infrastructure.telemetry.instrumentation import (
    instrument_all,
    instrument_fastapi,
    instrument_httpx,
    instrument_redis,
    instrument_sqlalchemy,
)
from src.infrastructure.telemetry.metrics import (
    create_counter,
    create_gauge,
    create_histogram,
    increment_counter,
    record_histogram_value,
    set_gauge,
)
from src.infrastructure.telemetry.tracing import (
    add_span_attributes,
    add_span_event,
    get_current_span,
    get_trace_id,
    set_span_error,
)

__all__ = [
    # Tracing
    "add_span_attributes",
    "add_span_event",
    "async_with_tracer",
    # Config
    "configure_telemetry",
    # Metrics
    "create_counter",
    "create_gauge",
    "create_histogram",
    "get_current_span",
    "get_meter",
    "get_trace_id",
    "get_tracer",
    "increment_counter",
    "instrument_all",
    "instrument_fastapi",
    # Instrumentation
    "instrument_httpx",
    "instrument_redis",
    "instrument_sqlalchemy",
    "record_histogram_value",
    "set_gauge",
    "set_span_error",
    "shutdown_telemetry",
    # Decorators
    "with_tracer",
]
