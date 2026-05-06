"""SQL implementation of ``ReflectionVerdictRepository``."""

from __future__ import annotations

import logging
import uuid
from typing import Any, override

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.flow.reflection_verdict import (
    ReflectionAction,
    ReflectionVerdict,
)
from src.domain.ports.repositories.reflection_verdict_repository import (
    ReflectionVerdictRepository,
    StoredReflectionVerdict,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    ReflectionVerdictRecord,
)

logger = logging.getLogger(__name__)


class SqlReflectionVerdictRepository(ReflectionVerdictRepository):
    """PostgreSQL-backed reflection verdict log."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def record(
        self, *, project_id: str, verdict: ReflectionVerdict
    ) -> StoredReflectionVerdict:
        row = ReflectionVerdictRecord(
            id=str(uuid.uuid4()),
            project_id=project_id,
            action=verdict.action.value,
            playbook_id=verdict.playbook_id,
            rationale=verdict.rationale,
            proposed_payload=_payload_to_dict(verdict.proposed_playbook),
        )
        self._session.add(row)
        await self._session.flush()
        return _to_domain(row)

    @override
    async def list_for_project(
        self,
        project_id: str,
        *,
        limit: int = 100,
    ) -> list[StoredReflectionVerdict]:
        stmt = (
            select(ReflectionVerdictRecord)
            .where(ReflectionVerdictRecord.project_id == project_id)
            .order_by(ReflectionVerdictRecord.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(refresh_select_statement(stmt))
        return [_to_domain(row) for row in result.scalars().all()]


def _payload_to_dict(
    payload: dict[str, object] | None,
) -> dict[str, Any] | None:
    if payload is None:
        return None
    return dict(payload)


def _to_domain(row: ReflectionVerdictRecord) -> StoredReflectionVerdict:
    verdict = ReflectionVerdict(
        action=ReflectionAction(row.action),
        playbook_id=row.playbook_id,
        rationale=row.rationale,
        proposed_playbook=row.proposed_payload,
    )
    return StoredReflectionVerdict(
        id=row.id,
        project_id=row.project_id,
        verdict=verdict,
        created_at=row.created_at,
    )


__all__ = ["SqlReflectionVerdictRepository"]
