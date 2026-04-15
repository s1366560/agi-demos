"""Workspace task event publication helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import redis.asyncio as redis

from src.domain.events.envelope import EventEnvelope
from src.domain.events.types import AgentEventType
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskPriority
from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
    RedisUnifiedEventBusAdapter,
)


def serialize_workspace_task(task: WorkspaceTask) -> dict[str, Any]:
    """Serialize a workspace task using the router's public payload contract."""

    return {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "title": task.title,
        "description": task.description,
        "created_by": task.created_by,
        "assignee_user_id": task.assignee_user_id,
        "assignee_agent_id": task.assignee_agent_id,
        "status": task.status.value,
        "metadata": dict(task.metadata),
        "created_at": _serialize_datetime(task.created_at),
        "updated_at": _serialize_datetime(task.updated_at),
        "priority": str(task.priority)
        if task.priority != WorkspaceTaskPriority.NONE
        else WorkspaceTaskPriority.NONE.value,
        "estimated_effort": task.estimated_effort,
        "blocker_reason": task.blocker_reason,
        "completed_at": _serialize_datetime(task.completed_at),
        "archived_at": _serialize_datetime(task.archived_at),
    }


@dataclass(frozen=True, slots=True)
class PendingWorkspaceTaskEvent:
    """Canonical workspace task event queued before the request commits."""

    workspace_id: str
    event_type: AgentEventType
    payload: dict[str, Any]


class WorkspaceTaskEventPublisher:
    """Publishes queued workspace task events after a successful commit."""

    def __init__(self, redis_client: redis.Redis | None) -> None:
        self._redis_client = redis_client

    async def publish_pending_events(self, events: Iterable[PendingWorkspaceTaskEvent]) -> None:
        if self._redis_client is None:
            return

        bus = RedisUnifiedEventBusAdapter(self._redis_client)
        for event in events:
            envelope = EventEnvelope.wrap(
                event_type=event.event_type,
                payload=event.payload,
                correlation_id=event.workspace_id,
                metadata={},
            )
            routing_key = f"workspace:{event.workspace_id}:{event.event_type.value}"
            await bus.publish(envelope, routing_key)


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")
