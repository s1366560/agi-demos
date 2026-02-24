"""
V2 SQLAlchemy implementation of TenantRepository using BaseRepository.
"""

import logging
import re
from typing import Any
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.tenant.tenant import Tenant
from src.domain.ports.repositories.tenant_repository import TenantRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import Tenant as DBTenant

logger = logging.getLogger(__name__)


def _generate_slug(name: str) -> str:
    """Generate a URL-friendly slug from a name."""
    # Convert to lowercase and replace spaces/special chars with hyphens
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = slug.strip("-")
    return slug


class SqlTenantRepository(BaseRepository[Tenant, DBTenant], TenantRepository):
    """V2 SQLAlchemy implementation of TenantRepository using BaseRepository."""

    _model_class = DBTenant

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository."""
        super().__init__(session)

    # === Interface implementation ===

    async def find_by_owner(self, owner_id: str, limit: int = 50, offset: int = 0) -> list[Tenant]:
        """List all tenants owned by a user."""
        query = select(DBTenant).where(DBTenant.owner_id == owner_id).offset(offset).limit(limit)
        result = await self._session.execute(query)
        db_tenants = result.scalars().all()
        return [d for t in db_tenants if (d := self._to_domain(t)) is not None]

    async def find_by_name(self, name: str) -> Tenant | None:
        """Find a tenant by name."""
        query = select(DBTenant).where(DBTenant.name == name)
        result = await self._session.execute(query)
        db_tenant = result.scalar_one_or_none()
        return self._to_domain(db_tenant)

    async def list_all(self, limit: int = 50, offset: int = 0, **filters: Any) -> list[Tenant]:
        """List all tenants with pagination."""
        return await super().list_all(limit=limit, offset=offset, **filters)

    async def delete(self, tenant_id: str) -> bool:
        """Delete a tenant."""
        db_tenant = await self._find_db_model_by_id(tenant_id)
        if db_tenant:
            await self._session.delete(db_tenant)
            await self._session.flush()
            return True
        return False
    # === Conversion methods ===

    def _to_domain(self, db_tenant: DBTenant | None) -> Tenant | None:
        """Convert database model to domain model."""
        if db_tenant is None:
            return None

        return Tenant(
            id=db_tenant.id,
            name=db_tenant.name,
            owner_id=db_tenant.owner_id,
            description=db_tenant.description,
            created_at=db_tenant.created_at,
            updated_at=db_tenant.updated_at,
        )

    def _to_db(self, domain_entity: Tenant) -> DBTenant:
        """Convert domain entity to database model."""
        return DBTenant(
            id=domain_entity.id,
            name=domain_entity.name,
            slug=_generate_slug(domain_entity.name),
            owner_id=domain_entity.owner_id,
            description=domain_entity.description,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
        )

    def _update_fields(self, db_model: DBTenant, domain_entity: Tenant) -> None:
        """Update database model fields from domain entity."""
        db_model.name = domain_entity.name
        db_model.slug = _generate_slug(domain_entity.name)
        db_model.description = domain_entity.description
        db_model.updated_at = domain_entity.updated_at
