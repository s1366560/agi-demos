"""
Provider Resolution Service

Service for resolving the appropriate LLM provider for a given tenant.
Implements fallback hierarchy and caching for performance.
"""

import logging
from typing import Any

from src.domain.llm_providers.models import (
    NoActiveProviderError,
    OperationType,
    ProviderConfig,
    ResolvedProvider,
)
from src.domain.llm_providers.repositories import ProviderRepository

logger = logging.getLogger(__name__)


class ProviderResolutionService:
    """
    Resolve the appropriate LLM provider for a given tenant.

    Resolution hierarchy:
    1. Tenant-specific provider (if configured)
    2. Default provider (if set)
    3. First active provider (fallback)

    Includes caching to improve performance.
    """

    CACHE_TTL_SECONDS = 300  # 5 minutes

    def __init__(
        self,
        repository: ProviderRepository,
        cache: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize provider resolution service.

        Args:
            repository: Provider repository instance (required)
            cache: Simple in-memory cache (use Redis in production)
        """
        self.repository = repository
        self.cache = cache if cache is not None else {}

    async def resolve_provider(
        self,
        tenant_id: str | None = None,
        operation_type: OperationType = OperationType.LLM,
    ) -> ProviderConfig:
        """
        Resolve provider for tenant.

        Args:
            tenant_id: Optional tenant/group ID

        Returns:
            Provider configuration

        Raises:
            NoActiveProviderError: If no active provider found
        """
        # Check cache first
        cache_key = f"provider:{tenant_id or 'default'}:{operation_type.value}"
        if cache_key in self.cache:
            cached_provider = self.cache[cache_key]
            logger.debug(f"Cache hit for {cache_key}")
            return cached_provider

        # Resolve provider (with fallback logic)
        resolved = await self._resolve_with_fallback(tenant_id, operation_type)
        provider = resolved.provider

        # Cache the result
        self.cache[cache_key] = provider

        logger.info(
            f"Resolved provider '{provider.name}' ({provider.provider_type}) "
            f"for tenant '{tenant_id or 'default'}' "
            f"(source: {resolved.resolution_source})"
        )

        return provider

    async def _resolve_with_fallback(
        self,
        tenant_id: str | None,
        operation_type: OperationType,
    ) -> ResolvedProvider:
        """
        Resolve provider using fallback hierarchy.

        Args:
            tenant_id: Optional tenant ID

        Returns:
            Resolved provider with resolution source

        Raises:
            NoActiveProviderError: If no active provider found
        """
        provider = None
        resolution_source = ""

        if tenant_id:
            # 1. Try tenant-specific provider
            logger.debug(f"Looking for tenant-specific provider: {tenant_id}")
            provider = await self.repository.find_tenant_provider(tenant_id, operation_type)
            if provider:
                resolution_source = "tenant"

        if not provider:
            # 2. Try default provider
            logger.debug("Looking for default provider")
            provider = await self.repository.find_default_provider()
            if provider:
                resolution_source = "default"

        if not provider:
            # 3. Fallback to first active provider
            logger.debug("Looking for first active provider")
            provider = await self.repository.find_first_active_provider()
            if provider:
                resolution_source = "fallback"

        if not provider:
            raise NoActiveProviderError(
                "No active LLM provider configured. Please configure at least one active provider."
            )

        return ResolvedProvider(
            provider=provider,
            resolution_source=resolution_source,
        )

    def invalidate_cache(self, tenant_id: str | None = None) -> None:
        """
        Invalidate cached provider resolution.

        Args:
            tenant_id: Optional tenant ID to invalidate. If None, clears all cache.
        """
        if tenant_id:
            prefix = f"provider:{tenant_id}:"
            keys_to_delete = [k for k in self.cache.keys() if k.startswith(prefix)]
            for key in keys_to_delete:
                del self.cache[key]
            if keys_to_delete:
                logger.debug(
                    f"Invalidated {len(keys_to_delete)} provider cache entries for tenant '{tenant_id}'"
                )
        else:
            self.cache.clear()
            logger.debug("Cleared all provider cache")


# Singleton instance
_provider_resolution_service: ProviderResolutionService | None = None


def get_provider_resolution_service() -> ProviderResolutionService:
    """Get or create singleton provider resolution service."""
    global _provider_resolution_service
    if _provider_resolution_service is None:
        from src.infrastructure.persistence.llm_providers_repository import (
            SQLAlchemyProviderRepository,
        )

        _provider_resolution_service = ProviderResolutionService(
            repository=SQLAlchemyProviderRepository(),
        )
    return _provider_resolution_service
