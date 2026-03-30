from __future__ import annotations

from datetime import datetime
from typing import Any

from src.domain.model.tenant.event_log import EventLog
from src.infrastructure.adapters.secondary.persistence.sql_event_log_repository import (
    SqlEventLogRepository,
)


class EventLogService:
    def __init__(self, repo: SqlEventLogRepository) -> None:
        self._repo = repo

    async def record_event(
        self,
        tenant_id: str,
        event_type: str,
        message: str,
        source: str = "system",
        metadata: dict[str, Any] | None = None,
    ) -> EventLog:
        event_log = EventLog(
            tenant_id=tenant_id,
            event_type=event_type,
            message=message,
            source=source,
            metadata=metadata or {},
        )
        await self._repo.save(event_log)
        return event_log

    async def list_events(
        self,
        tenant_id: str,
        event_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[EventLog], int]:
        return await self._repo.find_by_tenant(
            tenant_id=tenant_id,
            event_type=event_type,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )

    async def get_event_types(self, tenant_id: str) -> list[str]:
        return await self._repo.get_event_types(tenant_id)
