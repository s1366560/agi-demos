from __future__ import annotations

import logging
from datetime import datetime

from src.domain.model.audit.audit_entry import AuditEntry
from src.domain.ports.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)


class AuditQueryService:
    def __init__(self, audit_repo: AuditRepository) -> None:
        self._repo = audit_repo

    async def list_entries(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditEntry], int]:
        items = await self._repo.find_by_tenant(tenant_id, limit=limit, offset=offset)
        total = await self._repo.count_by_tenant(tenant_id)
        return items, total

    async def list_entries_filtered(
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
    ) -> tuple[list[AuditEntry], int]:
        items = await self._repo.find_by_tenant_filtered(
            tenant_id,
            action=action,
            resource_type=resource_type,
            actor=actor,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )
        total = await self._repo.count_by_tenant_filtered(
            tenant_id,
            action=action,
            resource_type=resource_type,
            actor=actor,
            start_time=start_time,
            end_time=end_time,
        )
        return items, total
