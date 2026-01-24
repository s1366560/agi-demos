from abc import ABC, abstractmethod
from typing import List, Optional

from src.domain.model.tenant.tenant import Tenant


class TenantRepository(ABC):
    """Repository interface for Tenant entity"""

    @abstractmethod
    async def save(self, tenant: Tenant) -> None:
        """Save a tenant (create or update)"""
        pass

    @abstractmethod
    async def find_by_id(self, tenant_id: str) -> Optional[Tenant]:
        """Find a tenant by ID"""
        pass

    @abstractmethod
    async def find_by_owner(self, owner_id: str, limit: int = 50, offset: int = 0) -> List[Tenant]:
        """List all tenants owned by a user"""
        pass

    @abstractmethod
    async def find_by_name(self, name: str) -> Optional[Tenant]:
        """Find a tenant by name"""
        pass

    @abstractmethod
    async def list_all(self, limit: int = 50, offset: int = 0) -> List[Tenant]:
        """List all tenants with pagination"""
        pass

    @abstractmethod
    async def delete(self, tenant_id: str) -> None:
        """Delete a tenant"""
        pass
