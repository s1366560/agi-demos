"""SQL implementation of ``PlaybookRepository``.

Persists reflection-distilled playbooks to PostgreSQL. The ``trigger`` and
``steps`` columns are JSON blobs holding structured records (not regexes
or executable code) so semantic matching stays an agent decision later.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, override

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.flow.playbook import (
    Playbook,
    PlaybookStatus,
    PlaybookStep,
    TriggerPattern,
)
from src.domain.ports.repositories.playbook_repository import PlaybookRepository
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Playbook as DBPlaybook,
)

logger = logging.getLogger(__name__)


class SqlPlaybookRepository(PlaybookRepository):
    """PostgreSQL-backed playbook repository (upsert-by-id semantics)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def save(self, playbook: Playbook) -> Playbook:
        existing = await self._session.get(DBPlaybook, playbook.id)
        if existing is None:
            self._session.add(self._to_db(playbook))
        else:
            existing.project_id = playbook.project_id
            existing.name = playbook.name
            existing.status = playbook.status.value
            existing.trigger = _trigger_to_dict(playbook.trigger)
            existing.steps = [_step_to_dict(s) for s in playbook.steps]
            existing.hit_count = playbook.hit_count
            existing.last_used_at = playbook.last_used_at
            existing.updated_at = datetime.now(UTC)
        await self._session.flush()
        return playbook

    @override
    async def find_by_id(self, playbook_id: str) -> Playbook | None:
        row = await self._session.get(DBPlaybook, playbook_id)
        return _to_domain(row) if row is not None else None

    @override
    async def find_by_project(
        self,
        project_id: str,
        *,
        status: PlaybookStatus | None = None,
        limit: int = 100,
    ) -> list[Playbook]:
        stmt = (
            select(DBPlaybook)
            .where(DBPlaybook.project_id == project_id)
            .order_by(DBPlaybook.created_at.desc())
            .limit(limit)
        )
        if status is not None:
            stmt = stmt.where(DBPlaybook.status == status.value)
        result = await self._session.execute(refresh_select_statement(stmt))
        rows = result.scalars().all()
        return [_to_domain(r) for r in rows]

    @override
    async def record_hit(self, playbook_id: str) -> None:
        now = datetime.now(UTC)
        stmt = (
            update(DBPlaybook)
            .where(DBPlaybook.id == playbook_id)
            .values(
                hit_count=DBPlaybook.hit_count + 1,
                last_used_at=now,
                updated_at=now,
            )
        )
        await self._session.execute(stmt)

    # === conversion ===

    def _to_db(self, playbook: Playbook) -> DBPlaybook:
        return DBPlaybook(
            id=playbook.id,
            project_id=playbook.project_id,
            name=playbook.name,
            status=playbook.status.value,
            trigger=_trigger_to_dict(playbook.trigger),
            steps=[_step_to_dict(s) for s in playbook.steps],
            hit_count=playbook.hit_count,
            last_used_at=playbook.last_used_at,
            created_at=playbook.created_at,
            updated_at=playbook.updated_at,
        )


def _trigger_to_dict(trigger: TriggerPattern) -> dict[str, Any]:
    return {
        "description": trigger.description,
        "friction_kinds": list(trigger.friction_kinds),
        "lane_transitions": [list(pair) for pair in trigger.lane_transitions],
    }


def _step_to_dict(step: PlaybookStep) -> dict[str, Any]:
    return {
        "order": step.order,
        "instruction": step.instruction,
        "rationale": step.rationale,
    }


def _trigger_from_dict(data: dict[str, Any] | None) -> TriggerPattern:
    if not data:
        return TriggerPattern(description="")
    transitions = data.get("lane_transitions") or ()
    return TriggerPattern(
        description=str(data.get("description", "")),
        friction_kinds=tuple(str(k) for k in data.get("friction_kinds") or ()),
        lane_transitions=tuple(
            (str(pair[0]), str(pair[1])) for pair in transitions if len(pair) == 2
        ),
    )


def _step_from_dict(data: dict[str, Any]) -> PlaybookStep:
    return PlaybookStep(
        order=int(data.get("order", 0)),
        instruction=str(data.get("instruction", "")),
        rationale=data.get("rationale"),
    )


def _to_domain(row: DBPlaybook) -> Playbook:
    return Playbook(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        status=PlaybookStatus(row.status),
        trigger=_trigger_from_dict(row.trigger),
        steps=tuple(_step_from_dict(s) for s in (row.steps or ())),
        hit_count=row.hit_count,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


__all__ = ["SqlPlaybookRepository"]
