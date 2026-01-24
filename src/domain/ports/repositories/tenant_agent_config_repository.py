"""
TenantAgentConfigRepository port (T094).

Repository interface for tenant agent configuration persistence.

This port defines the contract for persisting and retrieving
tenant-level agent configuration.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.model.agent.tenant_agent_config import TenantAgentConfig


class TenantAgentConfigRepositoryPort(ABC):
    """
    Repository port for tenant agent configuration.

    Provides CRUD operations for tenant agent configuration.
    Each tenant has exactly one configuration record.
    """

    @abstractmethod
    async def get_by_tenant(self, tenant_id: str) -> Optional[TenantAgentConfig]:
        """
        Get configuration for a tenant.

        Args:
            tenant_id: Tenant ID

        Returns:
            Configuration if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, config: TenantAgentConfig) -> TenantAgentConfig:
        """
        Save a configuration (create or update).

        Args:
            config: Configuration to save

        Returns:
            Saved configuration
        """
        pass

    @abstractmethod
    async def delete(self, tenant_id: str) -> None:
        """
        Delete configuration for a tenant.

        This resets the tenant to use default configuration.

        Args:
            tenant_id: Tenant ID

        Raises:
            ValueError: If configuration not found
        """
        pass

    @abstractmethod
    async def exists(self, tenant_id: str) -> bool:
        """
        Check if a tenant has custom configuration.

        Args:
            tenant_id: Tenant ID

        Returns:
            True if custom config exists, False otherwise
        """
        pass
