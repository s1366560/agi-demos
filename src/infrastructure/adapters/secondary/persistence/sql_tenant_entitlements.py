"""Bind quota reads and updates to a host-authenticated tenant member."""

from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.services.tenant_entitlement_port import (
    TenantEntitlementsNotFound,
    TenantQuota,
    TenantQuotaAccessDenied,
    TenantUsage,
    TenantUsageAccessDenied,
)
from src.infrastructure.adapters.secondary.persistence.models import Tenant, UserTenant
from src.infrastructure.adapters.secondary.persistence.sql_memory_repository import (
    SqlMemoryRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_repository import (
    SqlProjectRepository,
)


@dataclass(frozen=True, kw_only=True)
class SqlTenantEntitlements:
    session: AsyncSession
    tenant_id: str
    user_id: str

    async def _check(self, *, owner: bool = False) -> None:
        role = await self.session.scalar(
            select(UserTenant.role)
            .where(UserTenant.tenant_id == self.tenant_id, UserTenant.user_id == self.user_id)
            .with_for_update(read=True)
        )
        if owner and role != "owner":
            raise TenantQuotaAccessDenied
        if role not in {"owner", "admin"}:
            raise TenantUsageAccessDenied

    async def authorize_quota_change(self) -> None:
        await self._check(owner=True)

    async def read_quota(self) -> TenantQuota:
        await self._check()
        row = await self.session.scalar(
            select(Tenant)
            .where(Tenant.id == self.tenant_id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise TenantEntitlementsNotFound
        return _quota(row)

    async def read_usage(self) -> TenantUsage:
        await self._check()
        members = await self.session.scalar(
            select(func.count(UserTenant.id)).where(UserTenant.tenant_id == self.tenant_id)
        )
        project_ids = await SqlProjectRepository(self.session).ids_for_tenant(self.tenant_id)
        memories, storage = await SqlMemoryRepository(self.session).measure_usage(project_ids)
        return TenantUsage(
            users=members or 0, projects=len(project_ids), memories=memories, storage=storage
        )

    async def update_quota(self, *, plan: str, storage_limit: int) -> TenantQuota:
        # The shared membership lock fences role changes until the caller commits or rolls back.
        await self._check(owner=True)
        row = await self.session.scalar(
            update(Tenant)
            .where(Tenant.id == self.tenant_id)
            .values(plan=plan, max_storage=storage_limit)
            .returning(Tenant)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise TenantEntitlementsNotFound
        return _quota(row)


def _quota(tenant: Tenant) -> TenantQuota:
    return TenantQuota(
        id=tenant.id,
        name=tenant.name,
        plan=tenant.plan,
        storage_limit=tenant.max_storage,
        projects_limit=tenant.max_projects,
        users_limit=tenant.max_users,
    )
