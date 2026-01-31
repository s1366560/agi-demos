"""Tracing decorators for OpenTelemetry.

This module re-exports tracing decorators for convenience.
"""

from src.infrastructure.telemetry.tracing import (
    async_with_tracer,
    with_tracer,
)

__all__ = ["with_tracer", "async_with_tracer"]
