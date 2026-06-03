"""Read-only SQLAlchemy repository for audit log entries."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, override

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from src.domain.model.audit.audit_entry import AuditEntry
from src.domain.ports.repositories.audit_repository import AuditRepository
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
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
            .where(self._tenant_scope(tenant_id))
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(refresh_select_statement(stmt))
        return [self._to_domain(row) for row in result.scalars().all()]

    @override
    async def count_by_tenant(self, tenant_id: str) -> int:
        stmt = select(func.count()).select_from(AuditLog).where(self._tenant_scope(tenant_id))
        result = await self._session.execute(refresh_select_statement(stmt))
        count: Any = result.scalar_one()
        return int(count)

    @override
    async def find_by_tenant_filtered(
        self,
        tenant_id: str,
        *,
        action: str | None = None,
        action_prefix: str | None = None,
        resource_type: str | None = None,
        actor: str | None = None,
        detail_filters: dict[str, str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEntry]:
        base: Select[Any] = select(AuditLog).where(self._tenant_scope(tenant_id))
        filtered = self._apply_filters(
            base,
            action=action,
            action_prefix=action_prefix,
            resource_type=resource_type,
            actor=actor,
            detail_filters=detail_filters,
            start_time=start_time,
            end_time=end_time,
        )
        filtered = filtered.order_by(AuditLog.timestamp.desc()).limit(limit).offset(offset)
        result = await self._session.execute(refresh_select_statement(filtered))
        return [self._to_domain(row) for row in result.scalars().all()]

    @override
    async def count_by_tenant_filtered(
        self,
        tenant_id: str,
        *,
        action: str | None = None,
        action_prefix: str | None = None,
        resource_type: str | None = None,
        actor: str | None = None,
        detail_filters: dict[str, str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> int:
        base: Select[Any] = (
            select(func.count()).select_from(AuditLog).where(self._tenant_scope(tenant_id))
        )
        filtered = self._apply_filters(
            base,
            action=action,
            action_prefix=action_prefix,
            resource_type=resource_type,
            actor=actor,
            detail_filters=detail_filters,
            start_time=start_time,
            end_time=end_time,
        )
        result = await self._session.execute(refresh_select_statement(filtered))
        count: Any = result.scalar_one()
        return int(count)

    @override
    async def summarize_by_tenant_filtered(
        self,
        tenant_id: str,
        *,
        action: str | None = None,
        action_prefix: str | None = None,
        resource_type: str | None = None,
        actor: str | None = None,
        detail_filters: dict[str, str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, object]:
        """Return aggregate counts for audit entries matching the filters."""
        base: Select[Any] = select(AuditLog).where(self._tenant_scope(tenant_id))
        filtered = self._apply_filters(
            base,
            action=action,
            action_prefix=action_prefix,
            resource_type=resource_type,
            actor=actor,
            detail_filters=detail_filters,
            start_time=start_time,
            end_time=end_time,
        )
        result = await self._session.execute(refresh_select_statement(filtered))
        rows = result.scalars().all()
        action_counts = Counter(row.action for row in rows)
        executor_counts = Counter(
            str((row.details or {}).get("executor_kind", "unknown")) for row in rows
        )
        family_counts = Counter(
            str((row.details or {}).get("hook_family", "unknown")) for row in rows
        )
        isolation_counts = Counter(
            str((row.details or {}).get("isolation_mode", "unknown")) for row in rows
        )
        return {
            "total": len(rows),
            "action_counts": dict(action_counts),
            "executor_counts": dict(executor_counts),
            "family_counts": dict(family_counts),
            "isolation_mode_counts": dict(isolation_counts),
            "latest_timestamp": max((row.timestamp for row in rows), default=None),
        }

    @staticmethod
    def _apply_filters(
        stmt: Select[Any],
        *,
        action: str | None,
        action_prefix: str | None,
        resource_type: str | None,
        actor: str | None,
        detail_filters: dict[str, str] | None,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> Select[Any]:
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if action_prefix is not None:
            stmt = stmt.where(AuditLog.action.startswith(action_prefix))
        if resource_type is not None:
            stmt = stmt.where(AuditLog.resource_type == resource_type)
        if actor is not None:
            stmt = stmt.where(AuditLog.actor == actor)
        for detail_key, detail_value in (detail_filters or {}).items():
            stmt = stmt.where(AuditLog.details[detail_key].as_string() == detail_value)
        if start_time is not None:
            stmt = stmt.where(AuditLog.timestamp >= start_time)
        if end_time is not None:
            stmt = stmt.where(AuditLog.timestamp <= end_time)
        return stmt

    @staticmethod
    def _tenant_scope(tenant_id: str) -> ColumnElement[bool]:
        """Include tenant-owned rows and legacy system rows without tenant scope."""
        return or_(AuditLog.tenant_id == tenant_id, AuditLog.tenant_id.is_(None))

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
