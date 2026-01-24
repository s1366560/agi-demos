"""
LLM Provider Repository Interface

Domain repository interface following DDD principles.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from src.domain.llm_providers.models import (
    LLMUsageLog,
    LLMUsageLogCreate,
    ProviderConfig,
    ProviderConfigCreate,
    ProviderConfigUpdate,
    ProviderHealth,
    ResolvedProvider,
    TenantProviderMapping,
    UsageStatistics,
)


class ProviderRepository(ABC):
    """
    Repository interface for LLM provider configuration.

    Follows Domain-Driven Design principles with abstract interface
    defined in domain layer and implementation in infrastructure layer.
    """

    @abstractmethod
    async def create(self, config: ProviderConfigCreate) -> ProviderConfig:
        """Create a new provider configuration."""
        pass

    @abstractmethod
    async def get_by_id(self, provider_id: UUID) -> Optional[ProviderConfig]:
        """Get provider by ID."""
        pass

    @abstractmethod
    async def get_by_name(self, name: str) -> Optional[ProviderConfig]:
        """Get provider by name."""
        pass

    @abstractmethod
    async def list_all(self, include_inactive: bool = False) -> List[ProviderConfig]:
        """List all providers, optionally including inactive ones."""
        pass

    @abstractmethod
    async def list_active(self) -> List[ProviderConfig]:
        """List all active providers."""
        pass

    @abstractmethod
    async def update(
        self, provider_id: UUID, config: ProviderConfigUpdate
    ) -> Optional[ProviderConfig]:
        """Update provider configuration."""
        pass

    @abstractmethod
    async def delete(self, provider_id: UUID) -> bool:
        """Delete provider (soft delete by setting is_active=False)."""
        pass

    @abstractmethod
    async def find_default_provider(self) -> Optional[ProviderConfig]:
        """Find the default provider."""
        pass

    @abstractmethod
    async def find_first_active_provider(self) -> Optional[ProviderConfig]:
        """Find the first active provider as fallback."""
        pass

    @abstractmethod
    async def find_tenant_provider(self, tenant_id: str) -> Optional[ProviderConfig]:
        """Find provider assigned to specific tenant."""
        pass

    @abstractmethod
    async def resolve_provider(self, tenant_id: Optional[str] = None) -> ResolvedProvider:
        """
        Resolve appropriate provider for tenant.

        Resolution hierarchy:
        1. Tenant-specific provider (if configured)
        2. Default provider (if set)
        3. First active provider (fallback)

        Raises:
            NoActiveProviderError: If no active provider found
        """
        pass

    @abstractmethod
    async def create_health_check(self, health: ProviderHealth) -> ProviderHealth:
        """Create a health check entry."""
        pass

    @abstractmethod
    async def get_latest_health(self, provider_id: UUID) -> Optional[ProviderHealth]:
        """Get latest health check for provider."""
        pass

    @abstractmethod
    async def create_usage_log(self, usage_log: LLMUsageLogCreate) -> LLMUsageLog:
        """Create a usage log entry."""
        pass

    @abstractmethod
    async def get_usage_statistics(
        self,
        provider_id: Optional[UUID] = None,
        tenant_id: Optional[str] = None,
        operation_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[UsageStatistics]:
        """Get aggregated usage statistics."""
        pass

    @abstractmethod
    async def assign_provider_to_tenant(
        self, tenant_id: str, provider_id: UUID, priority: int = 0
    ) -> TenantProviderMapping:
        """Assign provider to tenant."""
        pass

    @abstractmethod
    async def unassign_provider_from_tenant(self, tenant_id: str, provider_id: UUID) -> bool:
        """Unassign provider from tenant."""
        pass

    @abstractmethod
    async def get_tenant_providers(self, tenant_id: str) -> List[TenantProviderMapping]:
        """Get all providers assigned to tenant."""
        pass
