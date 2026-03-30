from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.domain.model.audit.audit_entry import AuditEntry


class AuditRepository(ABC):
    """Read-only repository interface for audit log entries."""

    @abstractmethod
    async def find_by_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEntry]:
        """List audit entries for a tenant, newest first."""

    @abstractmethod
    async def count_by_tenant(self, tenant_id: str) -> int:
        """Return total number of audit entries for a tenant."""

    @abstractmethod
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
        """List audit entries matching optional filters, newest first."""

    @abstractmethod
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
        """Count audit entries matching optional filters."""
