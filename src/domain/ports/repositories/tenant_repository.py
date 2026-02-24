from abc import ABC, abstractmethod

from src.domain.model.tenant.tenant import Tenant


class TenantRepository(ABC):
    """Repository interface for Tenant entity"""

    @abstractmethod
    async def save(self, tenant: Tenant) -> Tenant:
        """Save a tenant (create or update). Returns the saved tenant."""
        pass

    @abstractmethod
    async def find_by_id(self, tenant_id: str) -> Tenant | None:
        """Find a tenant by ID"""
        pass

    @abstractmethod
    async def find_by_owner(self, owner_id: str, limit: int = 50, offset: int = 0) -> list[Tenant]:
        """List all tenants owned by a user"""
        pass

    @abstractmethod
    async def find_by_name(self, name: str) -> Tenant | None:
        """Find a tenant by name"""
        pass

    @abstractmethod
    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Tenant]:
        """List all tenants with pagination"""
        pass

    @abstractmethod
    async def delete(self, tenant_id: str) -> bool:
        """Delete a tenant. Returns True if deleted, False if not found."""
        pass
