"""
SQLAlchemy implementation of TenantRepository.
"""

import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.tenant.tenant import Tenant
from src.domain.ports.repositories.tenant_repository import TenantRepository
from src.infrastructure.adapters.secondary.persistence.models import Tenant as DBTenant

logger = logging.getLogger(__name__)


class SqlAlchemyTenantRepository(TenantRepository):
    """SQLAlchemy implementation of TenantRepository"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, tenant: Tenant) -> None:
        """Save a tenant (create or update)"""
        result = await self._session.execute(select(DBTenant).where(DBTenant.id == tenant.id))
        db_tenant = result.scalar_one_or_none()

        if db_tenant:
            # Update existing tenant
            db_tenant.name = tenant.name
            db_tenant.description = tenant.description
            # db_tenant.plan = tenant.plan
            # db_tenant.max_projects = tenant.max_projects
            # db_tenant.max_users = tenant.max_users
            # db_tenant.max_storage = tenant.max_storage
            db_tenant.updated_at = tenant.updated_at
        else:
            # Create new tenant
            db_tenant = DBTenant(
                id=tenant.id,
                name=tenant.name,
                owner_id=tenant.owner_id,
                description=tenant.description,
                # plan=tenant.plan,  # DB model does not have plan yet
                # max_projects=tenant.max_projects, # DB model does not have max_projects yet
                # max_users=tenant.max_users, # DB model does not have max_users yet
                # max_storage=tenant.max_storage, # DB model does not have max_storage yet
                created_at=tenant.created_at,
                updated_at=tenant.updated_at,
            )
            self._session.add(db_tenant)

        await self._session.flush()

    async def find_by_id(self, tenant_id: str) -> Optional[Tenant]:
        """Find a tenant by ID"""
        result = await self._session.execute(select(DBTenant).where(DBTenant.id == tenant_id))
        db_tenant = result.scalar_one_or_none()
        return self._to_domain(db_tenant) if db_tenant else None

    async def find_by_owner(self, owner_id: str, limit: int = 50, offset: int = 0) -> List[Tenant]:
        """List all tenants owned by a user"""
        result = await self._session.execute(
            select(DBTenant).where(DBTenant.owner_id == owner_id).offset(offset).limit(limit)
        )
        db_tenants = result.scalars().all()
        return [self._to_domain(t) for t in db_tenants]

    async def find_by_name(self, name: str) -> Optional[Tenant]:
        """Find a tenant by name"""
        result = await self._session.execute(select(DBTenant).where(DBTenant.name == name))
        db_tenant = result.scalar_one_or_none()
        return self._to_domain(db_tenant) if db_tenant else None

    async def list_all(self, limit: int = 50, offset: int = 0) -> List[Tenant]:
        """List all tenants with pagination"""
        result = await self._session.execute(select(DBTenant).offset(offset).limit(limit))
        db_tenants = result.scalars().all()
        return [self._to_domain(t) for t in db_tenants]

    async def delete(self, tenant_id: str) -> None:
        """Delete a tenant"""
        result = await self._session.execute(select(DBTenant).where(DBTenant.id == tenant_id))
        db_tenant = result.scalar_one_or_none()
        if db_tenant:
            await self._session.delete(db_tenant)
            await self._session.flush()

    def _to_domain(self, db_tenant: DBTenant) -> Tenant:
        """Convert database model to domain model"""
        return Tenant(
            id=db_tenant.id,
            name=db_tenant.name,
            owner_id=db_tenant.owner_id,
            description=db_tenant.description,
            # plan=db_tenant.plan,
            # max_projects=db_tenant.max_projects,
            # max_users=db_tenant.max_users,
            # max_storage=db_tenant.max_storage,
            created_at=db_tenant.created_at,
            updated_at=db_tenant.updated_at,
        )
