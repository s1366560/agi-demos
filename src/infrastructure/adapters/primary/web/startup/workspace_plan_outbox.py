"""Workspace Plan V2 durable outbox worker startup."""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any, cast

from src.domain.events.types import AgentEventType
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.agent.workspace_plan.orchestrator import OrchestratorConfig
from src.infrastructure.agent.workspace_plan.outbox_handlers import (
    ATTEMPT_RETRY_EVENT,
    HANDOFF_RESUME_EVENT,
    PIPELINE_RUN_REQUESTED_EVENT,
    SUPERVISOR_TICK_EVENT,
    WORKER_LAUNCH_EVENT,
    make_attempt_retry_handler,
    make_handoff_resume_handler,
    make_pipeline_run_requested_handler,
    make_supervisor_tick_handler,
    make_worker_launch_handler,
)
from src.infrastructure.agent.workspace_plan.outbox_worker import WorkspacePlanOutboxWorker

logger = logging.getLogger(__name__)

_ENABLED_ENV = "WORKSPACE_PLAN_OUTBOX_ENABLED"
_POLL_ENV = "WORKSPACE_PLAN_OUTBOX_POLL_SECONDS"
_BATCH_ENV = "WORKSPACE_PLAN_OUTBOX_BATCH_SIZE"
_LEASE_ENV = "WORKSPACE_PLAN_OUTBOX_LEASE_SECONDS"

_worker: WorkspacePlanOutboxWorker | None = None


def _enabled() -> bool:
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


async def initialize_workspace_plan_outbox_worker(
    *, redis_client: object | None = None
) -> WorkspacePlanOutboxWorker | None:
    """Start the durable Workspace Plan V2 outbox worker and publish UI refresh events."""
    global _worker

    config = OrchestratorConfig.from_env()
    if not _enabled():
        logger.info(
            "workspace_plan_outbox.disabled",
            extra={"event": "workspace_plan_outbox.disabled"},
        )
        return None
    if _worker is not None and _worker.is_running:
        return _worker
    if _worker is not None:
        logger.warning(
            "workspace_plan_outbox.stale_worker_replaced",
            extra={
                "event": "workspace_plan_outbox.stale_worker_replaced",
                "worker_id": _worker.worker_id,
            },
        )
        _worker = None

    try:
        _worker = WorkspacePlanOutboxWorker(
            session_factory=async_session_factory,
            handlers={
                SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(config=config),
                WORKER_LAUNCH_EVENT: make_worker_launch_handler(),
                HANDOFF_RESUME_EVENT: make_handoff_resume_handler(),
                ATTEMPT_RETRY_EVENT: make_attempt_retry_handler(),
                PIPELINE_RUN_REQUESTED_EVENT: make_pipeline_run_requested_handler(),
            },
            poll_interval_seconds=_float_env(_POLL_ENV, 2.0),
            batch_size=_int_env(_BATCH_ENV, 10),
            lease_seconds=_int_env(_LEASE_ENV, 60),
            event_publisher=(
                _make_plan_update_publisher(redis_client) if redis_client is not None else None
            ),
        )
        _worker.start()
        logger.info(
            "workspace_plan_outbox.started",
            extra={"event": "workspace_plan_outbox.started", "worker_id": _worker.worker_id},
        )
        return _worker
    except Exception:
        logger.warning(
            "workspace_plan_outbox.start_failed",
            exc_info=True,
            extra={"event": "workspace_plan_outbox.start_failed"},
        )
        _worker = None
        return None


def _make_plan_update_publisher(
    redis_client: object,
) -> Callable[[dict[str, Any]], Awaitable[None]]:
    async def _publish(payload: dict[str, Any]) -> None:
        from src.infrastructure.adapters.primary.web.routers.workspace_events import (
            publish_workspace_event,
        )

        workspace_id = payload.get("workspace_id")
        if not isinstance(workspace_id, str) or not workspace_id:
            return
        await publish_workspace_event(
            cast(Any, redis_client),
            workspace_id=workspace_id,
            event_type=AgentEventType.WORKSPACE_PLAN_UPDATED,
            payload=payload,
            metadata={"source": "workspace_plan_outbox_worker"},
            correlation_id=str(payload.get("plan_id") or workspace_id),
        )

    return _publish


async def shutdown_workspace_plan_outbox_worker() -> None:
    """Stop the durable Workspace Plan V2 outbox worker."""
    global _worker
    if _worker is None:
        return
    try:
        await _worker.stop()
    except Exception:
        logger.warning(
            "workspace_plan_outbox.stop_failed",
            exc_info=True,
            extra={"event": "workspace_plan_outbox.stop_failed"},
        )
    finally:
        _worker = None


__all__ = [
    "initialize_workspace_plan_outbox_worker",
    "shutdown_workspace_plan_outbox_worker",
]
