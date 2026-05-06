"""Helpers for publishing project-scoped reflection completion events."""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from collections.abc import Sequence
from typing import Literal

import redis.asyncio as redis

from src.domain.events.envelope import EventEnvelope
from src.domain.model.flow.reflection_verdict import ReflectionVerdict
from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
    RedisUnifiedEventBusAdapter,
)

logger = logging.getLogger(__name__)

ReflectionCompleteStatus = Literal["success", "failed", "timeout", "unavailable"]


def build_reflection_complete_payload(
    *,
    project_id: str,
    verdicts: Sequence[ReflectionVerdict],
    status: ReflectionCompleteStatus,
    source: str,
    run_id: str | None = None,
    error: str | None = None,
) -> dict[str, object]:
    """Create a stable payload shape for ``reflection_complete`` events."""
    actions = Counter(v.action.value for v in verdicts)
    payload: dict[str, object] = {
        "project_id": project_id,
        "run_id": run_id or f"refl_{uuid.uuid4().hex[:12]}",
        "status": status,
        "source": source,
        "applied_verdict_count": len(verdicts),
        "applied_actions": dict(actions),
    }
    if error:
        payload["error"] = error
    return payload


async def publish_reflection_complete(
    *,
    redis_client: redis.Redis,
    project_id: str,
    verdicts: Sequence[ReflectionVerdict],
    status: ReflectionCompleteStatus,
    source: str,
    run_id: str | None = None,
    error: str | None = None,
) -> None:
    """Publish ``reflection_complete`` to the project event stream.

    Routing key convention: ``project:{project_id}:reflection_complete``.
    """
    payload = build_reflection_complete_payload(
        project_id=project_id,
        verdicts=verdicts,
        status=status,
        source=source,
        run_id=run_id,
        error=error,
    )
    envelope = EventEnvelope(event_type="reflection_complete", payload=payload)
    routing_key = f"project:{project_id}:reflection_complete"
    try:
        bus = RedisUnifiedEventBusAdapter(redis_client)
        await bus.publish(envelope, routing_key)
    except Exception:
        logger.exception(
            "Failed to publish reflection_complete",
            extra={"project_id": project_id, "status": status, "source": source},
        )


__all__ = [
    "ReflectionCompleteStatus",
    "build_reflection_complete_payload",
    "publish_reflection_complete",
]
