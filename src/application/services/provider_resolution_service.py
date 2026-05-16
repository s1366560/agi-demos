"""
Provider Resolution Service

Service for resolving the appropriate LLM provider for a given tenant.
Implements fallback hierarchy and caching for performance.
"""

import logging
import time
from typing import Any, cast

from src.domain.llm_providers.models import (
    NoActiveProviderError,
    OperationType,
    ProviderConfig,
    ResolvedProvider,
)
from src.domain.llm_providers.repositories import ProviderRepository

logger = logging.getLogger(__name__)

_PROVIDER_ALIASES: dict[str, str] = {
    "azure_openai": "openai",
}


def _normalize_provider_key(provider: str | None) -> str | None:
    """Normalize provider key for cross-layer/provider-type matching."""
    if provider is None:
        return None

    normalized = provider.strip().lower()
    if not normalized:
        return None

    for suffix in ("_coding", "_embedding", "_reranker"):
        if normalized.endswith(suffix):
            normalized = normalized.removesuffix(suffix)
            break

    return _PROVIDER_ALIASES.get(normalized, normalized)


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
            cache: Simple in-memory cache (use Redis in production).
                   Each entry stores (ProviderConfig, cached_at_timestamp).
        """
        self.repository = repository
        self.cache: dict[str, tuple[Any, float]] = cache if cache is not None else {}

    async def resolve_provider(
        self,
        tenant_id: str | None = None,
        operation_type: OperationType = OperationType.LLM,
        model_id: str | None = None,
    ) -> ProviderConfig:
        """
        Resolve provider for tenant.

        Args:
            tenant_id: Optional tenant/group ID
            operation_type: Type of operation
            model_id: Optional model ID to check filtering

        Returns:
            Provider configuration

        Raises:
            NoActiveProviderError: If no active provider found
        """
        # Check cache first (with TTL enforcement)
        model_key = model_id or "any"
        cache_key = f"provider:{tenant_id or 'default'}:{operation_type.value}:{model_key}"
        cached_entry = self.cache.get(cache_key)
        if cached_entry is not None:
            cached_provider, cached_at = cached_entry
            age = time.monotonic() - cached_at
            if age <= self.CACHE_TTL_SECONDS:
                logger.debug(
                    "Provider cache hit for %s (age=%.1fs)",
                    cache_key,
                    age,
                )
                return cast(ProviderConfig, cached_provider)
            del self.cache[cache_key]
            logger.debug(
                "Provider cache expired for %s (age=%.1fs > TTL=%ds)",
                cache_key,
                age,
                self.CACHE_TTL_SECONDS,
            )

        # Resolve provider (with fallback logic)
        resolved = await self._resolve_with_fallback(tenant_id, operation_type, model_id)
        provider = resolved.provider

        # Cache the result with timestamp
        self.cache[cache_key] = (provider, time.monotonic())

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
        model_id: str | None = None,
    ) -> ResolvedProvider:
        """
        Resolve provider using fallback hierarchy.

        Checks is_enabled and is_model_allowed() at each tier.

        Args:
            tenant_id: Optional tenant ID
            operation_type: Type of operation
            model_id: Optional model ID for filtering

        Returns:
            Resolved provider with resolution source

        Raises:
            NoActiveProviderError: If no active provider found
        """
        provider = None
        resolution_source = ""
        requested_provider = self._resolve_model_provider(model_id)
        active_providers: list[ProviderConfig] | None = None
        if model_id and requested_provider is None:
            active_providers = await self.repository.list_active()
            requested_provider = self._infer_provider_from_configured_models(
                model_id,
                active_providers,
            )

        if tenant_id:
            # 1. Try tenant-specific provider
            logger.debug(f"Looking for tenant-specific provider: {tenant_id}")
            candidate = await self.repository.find_tenant_provider(tenant_id, operation_type)
            if candidate and self._is_provider_eligible(
                candidate,
                model_id,
                operation_type=operation_type,
                requested_provider=requested_provider,
            ):
                provider = candidate
                resolution_source = "tenant"

        if not provider:
            # 2. Try default provider
            logger.debug("Looking for default provider")
            candidate = await self.repository.find_default_provider()
            if candidate and self._is_provider_eligible(
                candidate,
                model_id,
                operation_type=operation_type,
                requested_provider=requested_provider,
            ):
                provider = candidate
                resolution_source = "default"

        if not provider:
            # 3. Fallback to the first eligible active provider
            logger.debug("Looking for first eligible active provider")
            if active_providers is None:
                active_providers = await self.repository.list_active()
            for candidate in active_providers:
                if self._is_provider_eligible(
                    candidate,
                    model_id,
                    operation_type=operation_type,
                    requested_provider=requested_provider,
                ):
                    provider = candidate
                    resolution_source = "fallback"
                    break

        if not provider:
            raise NoActiveProviderError(
                "No active LLM provider configured. Please configure at least one active provider."
            )

        return ResolvedProvider(
            provider=provider,
            resolution_source=resolution_source,
        )

    @staticmethod
    def _is_provider_eligible(
        provider: ProviderConfig,
        model_id: str | None,
        *,
        operation_type: OperationType = OperationType.LLM,
        requested_provider: str | None = None,
    ) -> bool:
        """
        Check if a provider is eligible based on enable flag
        and model filtering.

        Args:
            provider: Provider configuration to check
            model_id: Optional model ID to validate

        Returns:
            True if provider is eligible
        """
        if not provider.is_enabled:
            logger.debug(f"Provider '{provider.name}' skipped: disabled")
            return False

        raw_provider_type = str(getattr(provider.provider_type, "value", provider.provider_type))
        provider_type = raw_provider_type.strip().lower()
        if not ProviderResolutionService._is_operation_type_compatible(
            provider_type, operation_type
        ):
            logger.debug(
                "Provider '%s' skipped: incompatible provider_type '%s' for %s operation",
                provider.name,
                provider_type,
                operation_type.value,
            )
            return False

        provider_key = _normalize_provider_key(raw_provider_type)
        if requested_provider is not None and provider_key != requested_provider:
            logger.debug(
                "Provider '%s' skipped: model provider mismatch (%s != %s)",
                provider.name,
                provider_key,
                requested_provider,
            )
            return False

        if not ProviderResolutionService._is_model_allowed_for_provider(provider, model_id):
            logger.debug(f"Provider '{provider.name}' skipped: model '{model_id}' not allowed")
            return False

        return True

    @staticmethod
    def _is_operation_type_compatible(provider_type: str, operation_type: OperationType) -> bool:
        """Check provider type compatibility with requested operation type."""
        operation_value = operation_type.value
        if operation_value == OperationType.LLM.value:
            return not (provider_type.endswith("_embedding") or provider_type.endswith("_reranker"))
        if operation_value == OperationType.EMBEDDING.value:
            return not provider_type.endswith("_reranker")
        if operation_value == OperationType.RERANK.value:
            return not provider_type.endswith("_embedding")
        return True

    @staticmethod
    def _is_model_allowed_for_provider(provider: ProviderConfig, model_id: str | None) -> bool:
        """Check model allow/block rules, including provider-qualified model IDs."""
        if not model_id:
            return True

        if provider.is_model_allowed(model_id):
            return True

        if "/" not in model_id:
            return False

        unqualified_model = model_id.split("/", 1)[1]
        return provider.is_model_allowed(unqualified_model)

    @staticmethod
    def _resolve_model_provider(model_id: str | None) -> str | None:
        """Resolve provider key from model id using catalog fuzzy matching."""
        normalized_model_id = (model_id or "").strip()
        if not normalized_model_id:
            return None

        if "/" in normalized_model_id:
            # Explicit provider-qualified model should be authoritative.
            return _normalize_provider_key(normalized_model_id.split("/", 1)[0])

        from src.infrastructure.llm.model_catalog import get_model_catalog_service

        catalog = get_model_catalog_service()
        model_meta = catalog.get_model_fuzzy(normalized_model_id)
        if model_meta is not None:
            return _normalize_provider_key(model_meta.provider)

        return None

    @staticmethod
    def _normalize_model_name_for_match(model_name: str | None) -> str | None:
        """Normalize model id for cross-provider matching heuristics."""
        normalized = (model_name or "").strip().lower()
        if not normalized:
            return None
        if "/" in normalized:
            return normalized.split("/", 1)[1]
        return normalized

    @staticmethod
    def _infer_provider_from_configured_models(
        model_id: str,
        providers: list[ProviderConfig],
    ) -> str | None:
        """Infer provider key when model is not catalog-resolvable but matches configured models."""
        target_model = ProviderResolutionService._normalize_model_name_for_match(model_id)
        if not target_model:
            return None

        matched_provider_keys: set[str] = set()
        for provider in providers:
            provider_key = _normalize_provider_key(
                str(getattr(provider.provider_type, "value", provider.provider_type))
            )
            if provider_key is None:
                continue

            for configured_model in (provider.llm_model, provider.llm_small_model):
                configured = ProviderResolutionService._normalize_model_name_for_match(
                    configured_model
                )
                if configured and configured == target_model:
                    matched_provider_keys.add(provider_key)
                    break

        if len(matched_provider_keys) == 1:
            return next(iter(matched_provider_keys))
        return None

    async def list_pool_providers(
        self,
        tenant_id: str | None = None,
        operation_type: OperationType = OperationType.LLM,
    ) -> list[ProviderConfig]:
        """List every provider eligible for the tenant pool.

        Unlike :meth:`resolve_provider` which returns a single best match,
        this returns *all* active providers that pass the eligibility
        checks (enabled, compatible operation type, pool_enabled=True).
        Used by the load-balancer / auto-router to spread traffic.
        """
        active_providers = await self.repository.list_active()
        eligible: list[ProviderConfig] = []
        for candidate in active_providers:
            if not self._is_provider_eligible(
                candidate,
                model_id=None,
                operation_type=operation_type,
                requested_provider=None,
            ):
                continue
            if not getattr(candidate, "pool_enabled", True):
                continue
            eligible.append(candidate)
        return eligible

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
