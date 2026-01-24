"""
TenantSkillConfigRepository port for tenant skill configuration persistence.

Repository interface for persisting and retrieving tenant-level
skill configurations (disable/override system skills).
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from src.domain.model.agent.tenant_skill_config import TenantSkillConfig


class TenantSkillConfigRepositoryPort(ABC):
    """
    Repository port for tenant skill configuration persistence.

    Provides CRUD operations for tenant-level configurations
    that control how system skills are handled for each tenant.
    """

    @abstractmethod
    async def create(self, config: TenantSkillConfig) -> TenantSkillConfig:
        """
        Create a new tenant skill config.

        Args:
            config: Config to create

        Returns:
            Created config

        Raises:
            ValueError: If config already exists for this tenant/skill combo
        """
        pass

    @abstractmethod
    async def get_by_id(self, config_id: str) -> Optional[TenantSkillConfig]:
        """
        Get a config by its ID.

        Args:
            config_id: Config ID

        Returns:
            Config if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_by_tenant_and_skill(
        self,
        tenant_id: str,
        system_skill_name: str,
    ) -> Optional[TenantSkillConfig]:
        """
        Get a config by tenant and system skill name.

        Args:
            tenant_id: Tenant ID
            system_skill_name: Name of the system skill

        Returns:
            Config if found, None otherwise
        """
        pass

    @abstractmethod
    async def update(self, config: TenantSkillConfig) -> TenantSkillConfig:
        """
        Update an existing config.

        Args:
            config: Config to update

        Returns:
            Updated config

        Raises:
            ValueError: If config not found
        """
        pass

    @abstractmethod
    async def delete(self, config_id: str) -> None:
        """
        Delete a config by ID.

        Args:
            config_id: Config ID to delete

        Raises:
            ValueError: If config not found
        """
        pass

    @abstractmethod
    async def delete_by_tenant_and_skill(
        self,
        tenant_id: str,
        system_skill_name: str,
    ) -> None:
        """
        Delete a config by tenant and system skill name.

        Args:
            tenant_id: Tenant ID
            system_skill_name: Name of the system skill
        """
        pass

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: str,
    ) -> List[TenantSkillConfig]:
        """
        List all configs for a tenant.

        Args:
            tenant_id: Tenant ID

        Returns:
            List of configs for the tenant
        """
        pass

    @abstractmethod
    async def get_configs_map(
        self,
        tenant_id: str,
    ) -> Dict[str, TenantSkillConfig]:
        """
        Get all configs for a tenant as a map keyed by system_skill_name.

        This is useful for efficient lookups when loading skills.

        Args:
            tenant_id: Tenant ID

        Returns:
            Dict mapping system_skill_name to TenantSkillConfig
        """
        pass

    @abstractmethod
    async def count_by_tenant(
        self,
        tenant_id: str,
    ) -> int:
        """
        Count configs for a tenant.

        Args:
            tenant_id: Tenant ID

        Returns:
            Number of configs
        """
        pass
