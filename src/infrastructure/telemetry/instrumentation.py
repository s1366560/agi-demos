"""Instrumentation utilities for external libraries.

This module provides automatic tracing for HTTP clients and databases.
"""


from src.infrastructure.telemetry.config import _TRACER_PROVIDER


def instrument_httpx():
    """Instrument httpx for automatic tracing.

    This function should be called once during application startup.
    """
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        instrumentor = HTTPXClientInstrumentor()
        instrumentor.instrument()

        return True
    except ImportError:
        # opentelemetry-instrumentation-httpx not installed
        return False
    except Exception:
        # Already instrumented or other error
        return False


def instrument_sqlalchemy():
    """Instrument SQLAlchemy for automatic tracing.

    This function should be called once during application startup.
    """
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        if _TRACER_PROVIDER is None:
            return False

        # Instrument all SQLAlchemy engines
        SQLAlchemyInstrumentor().instrument(
            tracer_provider=_TRACER_PROVIDER,
            enable_commenter=True,
            capture_parameters=False,  # Don't capture query parameters for privacy
        )

        return True
    except ImportError:
        # opentelemetry-instrumentation-sqlalchemy not installed
        return False
    except Exception:
        # Already instrumented or other error
        return False


def instrument_redis():
    """Instrument Redis for automatic tracing.

    This function should be called once during application startup.
    """
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        if _TRACER_PROVIDER is None:
            return False

        RedisInstrumentor().instrument(
            tracer_provider=_TRACER_PROVIDER,
            capture_statement=False,  # Don't capture Redis commands for privacy
        )

        return True
    except ImportError:
        # opentelemetry-instrumentation-redis not installed
        return False
    except Exception:
        # Already instrumented or other error
        return False


def instrument_fastapi(app):
    """Instrument FastAPI for automatic tracing.

    Args:
        app: FastAPI application instance

    This function should be called once during application startup.
    """
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        from src.infrastructure.telemetry.config import _TRACER_PROVIDER

        if _TRACER_PROVIDER is None:
            return False

        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=_TRACER_PROVIDER,
        )

        return True
    except ImportError:
        # opentelemetry-instrumentation-fastapi not installed
        return False
    except Exception:
        # Already instrumented or other error
        return False


def instrument_all(auto_instrument: bool = True):
    """Instrument all supported libraries.

    Args:
        auto_instrument: Whether to use auto-instrumentation

    Returns:
        Dictionary with instrumentation results
    """
    results = {
        "httpx": False,
        "sqlalchemy": False,
        "redis": False,
        "fastapi": False,
    }

    if not auto_instrument:
        return results

    results["httpx"] = instrument_httpx()
    results["sqlalchemy"] = instrument_sqlalchemy()
    results["redis"] = instrument_redis()

    return results
