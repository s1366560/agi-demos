from __future__ import annotations

from datetime import datetime
from typing import override

from sqlalchemy import func, select

from src.domain.model.tenant.event_log import EventLog
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import TenantEventLogModel


class SqlEventLogRepository(BaseRepository[EventLog, TenantEventLogModel]):
    _model_class = TenantEventLogModel

    @override
    def _to_domain(self, db_model: TenantEventLogModel | None) -> EventLog | None:
        if db_model is None:
            return None
        return EventLog(
            id=db_model.id,
            tenant_id=db_model.tenant_id,
            event_type=db_model.event_type,
            message=db_model.message,
            source=db_model.source,
            metadata=db_model.metadata_ or {},
            created_at=db_model.created_at,
        )

    @override
    def _to_db(self, domain_entity: EventLog) -> TenantEventLogModel:
        return TenantEventLogModel(
            id=domain_entity.id,
            tenant_id=domain_entity.tenant_id,
            event_type=domain_entity.event_type,
            message=domain_entity.message,
            source=domain_entity.source,
            metadata_=domain_entity.metadata,
            created_at=domain_entity.created_at,
        )

    async def find_by_tenant(
        self,
        tenant_id: str,
        event_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[EventLog], int]:
        offset = (page - 1) * page_size

        base_stmt = select(TenantEventLogModel).where(TenantEventLogModel.tenant_id == tenant_id)

        if event_type:
            base_stmt = base_stmt.where(TenantEventLogModel.event_type == event_type)
        if date_from:
            base_stmt = base_stmt.where(TenantEventLogModel.created_at >= date_from)
        if date_to:
            base_stmt = base_stmt.where(TenantEventLogModel.created_at <= date_to)

        # Count
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        # Fetch
        stmt = (
            base_stmt.order_by(TenantEventLogModel.created_at.desc())
            .limit(page_size)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        items = [d for row in result.scalars().all() if (d := self._to_domain(row)) is not None]

        return items, total

    async def get_event_types(self, tenant_id: str) -> list[str]:
        stmt = (
            select(TenantEventLogModel.event_type)
            .where(TenantEventLogModel.tenant_id == tenant_id)
            .distinct()
            .order_by(TenantEventLogModel.event_type)
        )
        result = await self._session.execute(stmt)
        return [row[0] for row in result.all()]
