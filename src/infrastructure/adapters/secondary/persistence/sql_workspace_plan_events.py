"""SQL repository for durable workspace plan events."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace_plan import WorkspacePlanEvent
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import WorkspacePlanEventModel


class SqlWorkspacePlanEventRepository:
    """Append and query plan event timeline entries."""

    def __init__(self, db: AsyncSession) -> None:
        super().__init__()
        self._db = db

    async def append(
        self,
        *,
        plan_id: str,
        workspace_id: str,
        event_type: str,
        node_id: str | None = None,
        attempt_id: str | None = None,
        actor_id: str | None = None,
        source: str = "system",
        payload: dict[str, Any] | None = None,
    ) -> WorkspacePlanEvent:
        event = WorkspacePlanEvent(
            id=str(uuid.uuid4()),
            plan_id=plan_id,
            workspace_id=workspace_id,
            node_id=node_id,
            attempt_id=attempt_id,
            actor_id=actor_id,
            event_type=event_type,
            source=source,
            payload=dict(payload or {}),
        )
        self._db.add(_event_to_model(event))
        await self._db.flush()
        return event

    async def list_recent(self, plan_id: str, *, limit: int = 50) -> list[WorkspacePlanEvent]:
        if limit <= 0:
            return []
        result = await self._db.execute(
            refresh_select_statement(
                select(WorkspacePlanEventModel)
                .where(WorkspacePlanEventModel.plan_id == plan_id)
                .order_by(
                    WorkspacePlanEventModel.created_at.desc(), WorkspacePlanEventModel.id.desc()
                )
                .limit(limit)
            )
        )
        return [_event_from_model(model) for model in result.scalars().all()]


def _event_to_model(event: WorkspacePlanEvent) -> WorkspacePlanEventModel:
    return WorkspacePlanEventModel(
        id=event.id,
        plan_id=event.plan_id,
        workspace_id=event.workspace_id,
        node_id=event.node_id,
        attempt_id=event.attempt_id,
        actor_id=event.actor_id,
        event_type=event.event_type,
        source=event.source,
        payload_json=dict(event.payload),
        created_at=event.created_at,
    )


def _event_from_model(model: WorkspacePlanEventModel) -> WorkspacePlanEvent:
    return WorkspacePlanEvent(
        id=model.id,
        plan_id=model.plan_id,
        workspace_id=model.workspace_id,
        node_id=model.node_id,
        attempt_id=model.attempt_id,
        actor_id=model.actor_id,
        event_type=model.event_type,
        source=model.source,
        payload=dict(model.payload_json or {}),
        created_at=model.created_at,
    )


__all__ = ["SqlWorkspacePlanEventRepository"]
