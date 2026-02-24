"""
LLM Provider Repository Interface

Domain repository interface following DDD principles.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from src.domain.llm_providers.models import (
    LLMUsageLog,
    LLMUsageLogCreate,
    OperationType,
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

    @abstractmethod
    async def get_by_id(self, provider_id: UUID) -> ProviderConfig | None:
        """Get provider by ID."""

    @abstractmethod
    async def get_by_name(self, name: str) -> ProviderConfig | None:
        """Get provider by name."""

    @abstractmethod
    async def list_all(self, include_inactive: bool = False) -> list[ProviderConfig]:
        """List all providers, optionally including inactive ones."""

    @abstractmethod
    async def list_active(self) -> list[ProviderConfig]:
        """List all active providers."""

    @abstractmethod
    async def update(
        self, provider_id: UUID, config: ProviderConfigUpdate
    ) -> ProviderConfig | None:
        """Update provider configuration."""

    @abstractmethod
    async def delete(self, provider_id: UUID) -> bool:
        """Delete provider (soft delete by setting is_active=False)."""

    @abstractmethod
    async def find_default_provider(self) -> ProviderConfig | None:
        """Find the default provider."""

    @abstractmethod
    async def find_first_active_provider(self) -> ProviderConfig | None:
        """Find the first active provider as fallback."""

    @abstractmethod
    async def find_tenant_provider(
        self,
        tenant_id: str,
        operation_type: OperationType = OperationType.LLM,
    ) -> ProviderConfig | None:
        """Find provider assigned to specific tenant."""

    @abstractmethod
    async def resolve_provider(
        self,
        tenant_id: str | None = None,
        operation_type: OperationType = OperationType.LLM,
    ) -> ResolvedProvider:
        """
        Resolve appropriate provider for tenant.

        Resolution hierarchy:
        1. Tenant-specific provider (if configured)
        2. Default provider (if set)
        3. First active provider (fallback)

        Raises:
            NoActiveProviderError: If no active provider found
        """

    @abstractmethod
    async def create_health_check(self, health: ProviderHealth) -> ProviderHealth:
        """Create a health check entry."""

    @abstractmethod
    async def get_latest_health(self, provider_id: UUID) -> ProviderHealth | None:
        """Get latest health check for provider."""

    @abstractmethod
    async def create_usage_log(self, usage_log: LLMUsageLogCreate) -> LLMUsageLog:
        """Create a usage log entry."""

    @abstractmethod
    async def get_usage_statistics(
        self,
        provider_id: UUID | None = None,
        tenant_id: str | None = None,
        operation_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[UsageStatistics]:
        """Get aggregated usage statistics."""

    @abstractmethod
    async def assign_provider_to_tenant(
        self,
        tenant_id: str,
        provider_id: UUID,
        priority: int = 0,
        operation_type: OperationType = OperationType.LLM,
    ) -> TenantProviderMapping:
        """Assign provider to tenant."""

    @abstractmethod
    async def unassign_provider_from_tenant(
        self,
        tenant_id: str,
        provider_id: UUID,
        operation_type: OperationType = OperationType.LLM,
    ) -> bool:
        """Unassign provider from tenant."""

    @abstractmethod
    async def get_tenant_providers(
        self,
        tenant_id: str,
        operation_type: OperationType | None = None,
    ) -> list[TenantProviderMapping]:
        """Get all providers assigned to tenant."""
