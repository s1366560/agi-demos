"""Read-only SQLAlchemy repository for audit log entries."""

from __future__ import annotations

from datetime import datetime
from typing import Any, override

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.audit.audit_entry import AuditEntry
from src.domain.ports.repositories.audit_repository import AuditRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    AuditLog,
)


class SqlAuditRepository(AuditRepository):
    """Standalone read-only repository -- not extending BaseRepository."""

    def __init__(self, db: AsyncSession) -> None:
        self._session = db

    @override
    async def find_by_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEntry]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    @override
    async def count_by_tenant(self, tenant_id: str) -> int:
        stmt = select(func.count()).select_from(AuditLog).where(AuditLog.tenant_id == tenant_id)
        result = await self._session.execute(stmt)
        count: Any = result.scalar_one()
        return int(count)

    @override
    async def find_by_tenant_filtered(
        self,
        tenant_id: str,
        *,
        action: str | None = None,
        resource_type: str | None = None,
        actor: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEntry]:
        base: Select[Any] = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
        filtered = self._apply_filters(
            base,
            action=action,
            resource_type=resource_type,
            actor=actor,
            start_time=start_time,
            end_time=end_time,
        )
        filtered = filtered.order_by(AuditLog.timestamp.desc()).limit(limit).offset(offset)
        result = await self._session.execute(filtered)
        return [self._to_domain(row) for row in result.scalars().all()]

    @override
    async def count_by_tenant_filtered(
        self,
        tenant_id: str,
        *,
        action: str | None = None,
        resource_type: str | None = None,
        actor: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> int:
        base: Select[Any] = (
            select(func.count()).select_from(AuditLog).where(AuditLog.tenant_id == tenant_id)
        )
        filtered = self._apply_filters(
            base,
            action=action,
            resource_type=resource_type,
            actor=actor,
            start_time=start_time,
            end_time=end_time,
        )
        result = await self._session.execute(filtered)
        count: Any = result.scalar_one()
        return int(count)

    @staticmethod
    def _apply_filters(
        stmt: Select[Any],
        *,
        action: str | None,
        resource_type: str | None,
        actor: str | None,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> Select[Any]:
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if resource_type is not None:
            stmt = stmt.where(AuditLog.resource_type == resource_type)
        if actor is not None:
            stmt = stmt.where(AuditLog.actor == actor)
        if start_time is not None:
            stmt = stmt.where(AuditLog.timestamp >= start_time)
        if end_time is not None:
            stmt = stmt.where(AuditLog.timestamp <= end_time)
        return stmt

    @staticmethod
    def _to_domain(row: AuditLog) -> AuditEntry:
        return AuditEntry(
            id=row.id,
            timestamp=row.timestamp,
            actor=row.actor,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            tenant_id=row.tenant_id,
            details=dict(row.details) if row.details else {},
            ip_address=row.ip_address,
            user_agent=row.user_agent,
        )
