"""Startup/shutdown wiring for the blackboard outbox dispatcher."""

from __future__ import annotations

import logging
import os

import redis.asyncio as redis_async

from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.agent.workspace_plan.blackboard_event_port_impl import (
    build_blackboard_event_port,
    get_blackboard_event_transport,
)
from src.infrastructure.agent.workspace_plan.blackboard_outbox_dispatcher import (
    BlackboardOutboxDispatcher,
)

logger = logging.getLogger(__name__)

_ENABLED_ENV = "BLACKBOARD_OUTBOX_ENABLED"
_POLL_ENV = "BLACKBOARD_OUTBOX_POLL_SECONDS"
_BATCH_ENV = "BLACKBOARD_OUTBOX_BATCH_SIZE"

_dispatcher: BlackboardOutboxDispatcher | None = None


def is_outbox_enabled() -> bool:
    """Return whether the blackboard outbox feature flag is on.

    Default ``true``; set ``BLACKBOARD_OUTBOX_ENABLED=false`` to fall
    back to the legacy best-effort post-commit publish path.
    """
    raw = os.environ.get(_ENABLED_ENV)
    if raw is None:
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value > 0 else default


async def initialize_blackboard_outbox_dispatcher(
    *, redis_client: redis_async.Redis | None = None
) -> BlackboardOutboxDispatcher | None:
    """Start the durable blackboard outbox dispatcher.

    Returns ``None`` when the feature flag is off so callers can no-op
    cleanly. Failures are logged and swallowed so the API still boots.
    """
    global _dispatcher

    if not is_outbox_enabled():
        logger.info(
            "blackboard_outbox.disabled",
            extra={"event": "blackboard_outbox.disabled"},
        )
        return None
    if _dispatcher is not None and _dispatcher.is_running:
        return _dispatcher

    try:
        event_port = build_blackboard_event_port(redis_client)
        _dispatcher = BlackboardOutboxDispatcher(
            session_factory=async_session_factory,
            redis_client=redis_client,
            poll_interval_seconds=_float_env(_POLL_ENV, 0.5),
            batch_size=_int_env(_BATCH_ENV, 32),
            event_port=event_port,
        )
        _dispatcher.start()
        logger.info(
            "blackboard_outbox.started",
            extra={
                "event": "blackboard_outbox.started",
                "transport": get_blackboard_event_transport(),
            },
        )
        return _dispatcher
    except Exception:
        logger.warning(
            "blackboard_outbox.start_failed",
            exc_info=True,
            extra={"event": "blackboard_outbox.start_failed"},
        )
        _dispatcher = None
        return None


async def shutdown_blackboard_outbox_dispatcher() -> None:
    """Stop the blackboard outbox dispatcher."""
    global _dispatcher
    if _dispatcher is None:
        return
    try:
        await _dispatcher.stop()
    except Exception:
        logger.warning(
            "blackboard_outbox.stop_failed",
            exc_info=True,
            extra={"event": "blackboard_outbox.stop_failed"},
        )
    finally:
        _dispatcher = None


__all__ = [
    "initialize_blackboard_outbox_dispatcher",
    "is_outbox_enabled",
    "shutdown_blackboard_outbox_dispatcher",
]
