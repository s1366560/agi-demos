"""SQL-backed :class:`BlackboardPort` for workspace plan artifacts."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any, override

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.services.blackboard_port import BlackboardEntry, BlackboardPort
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    WorkspacePlanBlackboardEntryModel,
)


class SqlWorkspacePlanBlackboard(BlackboardPort):
    """Append-only artifact blackboard persisted per plan/key/version.

    The :class:`BlackboardPort` contract exposes only the latest value for
    ``get`` and ``list``. This adapter keeps the full version history in SQL so
    future plan-event and audit surfaces can inspect prior artifacts.
    """

    def __init__(self, db: AsyncSession, *, poll_interval_seconds: float = 1.0) -> None:
        super().__init__()
        self._db = db
        self._poll_interval_seconds = poll_interval_seconds

    @override
    async def put(self, entry: BlackboardEntry) -> int:
        next_version = await self._next_version(entry.plan_id, entry.key)
        self._db.add(
            WorkspacePlanBlackboardEntryModel(
                id=str(uuid.uuid4()),
                plan_id=entry.plan_id,
                key=entry.key,
                value_json=entry.value,
                published_by=entry.published_by,
                version=next_version,
                schema_ref=entry.schema_ref,
                metadata_json=dict(entry.metadata),
            )
        )
        await self._db.flush()
        return next_version

    @override
    async def get(self, plan_id: str, key: str) -> BlackboardEntry | None:
        stmt = (
            select(WorkspacePlanBlackboardEntryModel)
            .where(
                WorkspacePlanBlackboardEntryModel.plan_id == plan_id,
                WorkspacePlanBlackboardEntryModel.key == key,
            )
            .order_by(
                WorkspacePlanBlackboardEntryModel.version.desc(),
                WorkspacePlanBlackboardEntryModel.created_at.desc(),
            )
            .limit(1)
        )
        result = await self._db.execute(refresh_select_statement(stmt))
        model = result.scalar_one_or_none()
        return _entry_from_model(model) if model is not None else None

    @override
    async def list(self, plan_id: str) -> list[BlackboardEntry]:
        stmt = (
            select(WorkspacePlanBlackboardEntryModel)
            .where(WorkspacePlanBlackboardEntryModel.plan_id == plan_id)
            .order_by(
                WorkspacePlanBlackboardEntryModel.key.asc(),
                WorkspacePlanBlackboardEntryModel.version.desc(),
                WorkspacePlanBlackboardEntryModel.created_at.desc(),
            )
        )
        result = await self._db.execute(refresh_select_statement(stmt))
        latest_by_key: dict[str, BlackboardEntry] = {}
        for model in result.scalars():
            if model.key not in latest_by_key:
                latest_by_key[model.key] = _entry_from_model(model)
        return list(latest_by_key.values())

    @override
    async def subscribe(
        self,
        plan_id: str,
        keys: tuple[str, ...] | None = None,
    ) -> AsyncIterator[BlackboardEntry]:
        """Poll for committed updates and yield entries newer than subscription start."""
        seen_versions = await self._latest_versions(plan_id, keys)
        while True:
            await asyncio.sleep(self._poll_interval_seconds)
            stmt = (
                select(WorkspacePlanBlackboardEntryModel)
                .where(WorkspacePlanBlackboardEntryModel.plan_id == plan_id)
                .order_by(
                    WorkspacePlanBlackboardEntryModel.created_at.asc(),
                    WorkspacePlanBlackboardEntryModel.version.asc(),
                )
            )
            if keys is not None:
                stmt = stmt.where(WorkspacePlanBlackboardEntryModel.key.in_(keys))
            result = await self._db.execute(refresh_select_statement(stmt))
            for model in result.scalars():
                previous = seen_versions.get(model.key, 0)
                if model.version <= previous:
                    continue
                seen_versions[model.key] = model.version
                yield _entry_from_model(model)

    async def _next_version(self, plan_id: str, key: str) -> int:
        stmt = (
            select(WorkspacePlanBlackboardEntryModel.version)
            .where(
                WorkspacePlanBlackboardEntryModel.plan_id == plan_id,
                WorkspacePlanBlackboardEntryModel.key == key,
            )
            .order_by(WorkspacePlanBlackboardEntryModel.version.desc())
            .limit(1)
        )
        result = await self._db.execute(refresh_select_statement(stmt))
        current = result.scalar_one_or_none()
        return int(current or 0) + 1

    async def _latest_versions(
        self,
        plan_id: str,
        keys: tuple[str, ...] | None,
    ) -> dict[str, int]:
        stmt = select(WorkspacePlanBlackboardEntryModel).where(
            WorkspacePlanBlackboardEntryModel.plan_id == plan_id
        )
        if keys is not None:
            stmt = stmt.where(WorkspacePlanBlackboardEntryModel.key.in_(keys))
        result = await self._db.execute(refresh_select_statement(stmt))
        latest: dict[str, int] = {}
        for model in result.scalars():
            latest[model.key] = max(latest.get(model.key, 0), int(model.version))
        return latest


def _entry_from_model(model: WorkspacePlanBlackboardEntryModel) -> BlackboardEntry:
    value: Any = model.value_json
    return BlackboardEntry(
        plan_id=model.plan_id,
        key=model.key,
        value=value,
        published_by=model.published_by,
        version=model.version,
        schema_ref=model.schema_ref,
        metadata=dict(model.metadata_json or {}),
    )


__all__ = ["SqlWorkspacePlanBlackboard"]
