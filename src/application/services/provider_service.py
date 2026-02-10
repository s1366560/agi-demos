"""
LLM Provider Service

Application service for managing LLM provider configurations.
Handles business logic and coordinates between domain and infrastructure layers.
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.provider_resolution_service import get_provider_resolution_service
from src.domain.llm_providers.models import (
    CircuitBreakerState,
    LLMUsageLog,
    LLMUsageLogCreate,
    ModelMetadata,
    ProviderConfig,
    ProviderConfigCreate,
    ProviderConfigResponse,
    ProviderConfigUpdate,
    ProviderHealth,
    ProviderType,
    RateLimitStats,
    ResilienceStatus,
    TenantProviderMapping,
    get_default_model_metadata,
)
from src.domain.llm_providers.repositories import ProviderRepository
from src.infrastructure.llm.resilience import (
    get_circuit_breaker_registry,
    get_provider_rate_limiter,
)
from src.infrastructure.persistence.llm_providers_repository import SQLAlchemyProviderRepository
from src.infrastructure.security.encryption_service import get_encryption_service

logger = logging.getLogger(__name__)


class ProviderService:
    """
    Service for LLM provider configuration management.

    Provides high-level operations for creating, updating, and managing
    LLM provider configurations with proper validation and error handling.
    """

    def __init__(self, repository: Optional[ProviderRepository] = None):
        """
        Initialize provider service.

        Args:
            repository: Provider repository instance. If None, creates default.
        """
        self.repository = repository or SQLAlchemyProviderRepository()
        self.encryption_service = get_encryption_service()
        self.resolution_service = get_provider_resolution_service()

    async def create_provider(self, config: ProviderConfigCreate) -> ProviderConfig:
        """
        Create a new LLM provider configuration.

        If a provider with the same name already exists (e.g., created by another
        process during initialization), returns the existing provider instead of
        raising an error. This makes the operation idempotent for concurrent
        initialization scenarios.

        Args:
            config: Provider configuration data

        Returns:
            Created or existing provider configuration

        Raises:
            ValueError: If validation fails (excluding duplicate name)
        """
        logger.info(f"Creating provider: {config.name} ({config.provider_type})")

        # Fast path: check if provider already exists
        existing = await self.repository.get_by_name(config.name)
        if existing:
            logger.info(f"Provider '{config.name}' already exists, returning existing provider")
            return existing

        # If this is marked as default, unset other defaults
        if config.is_default:
            await self._clear_default_providers()

        # Create provider (idempotent - returns existing if another process created it)
        provider = await self.repository.create(config)

        # Invalidate cache (affects default provider resolution)
        self.resolution_service.invalidate_cache()

        logger.info(f"Created provider: {provider.id}")
        return provider

    async def list_providers(self, include_inactive: bool = False) -> List[ProviderConfig]:
        """List all providers."""
        return await self.repository.list_all(include_inactive=include_inactive)

    async def get_provider(self, provider_id: UUID) -> Optional[ProviderConfig]:
        """Get provider by ID."""
        return await self.repository.get_by_id(provider_id)

    async def get_provider_response(self, provider_id: UUID) -> Optional[ProviderConfigResponse]:
        """
        Get provider for API response (with masked API key, health status, and resilience info).

        Args:
            provider_id: Provider ID

        Returns:
            Provider configuration with masked API key, health status, and resilience status
        """
        provider = await self.repository.get_by_id(provider_id)
        if not provider:
            return None

        # Get latest health status
        health = await self.repository.get_latest_health(provider_id)

        # Mask API key (show only last 4 characters)
        api_key_masked = self._mask_api_key(provider.api_key_encrypted)

        # Get resilience status
        resilience = self._get_resilience_status(provider.provider_type)

        return ProviderConfigResponse(
            id=provider.id,
            name=provider.name,
            provider_type=provider.provider_type,
            base_url=provider.base_url,
            llm_model=provider.llm_model,
            llm_small_model=provider.llm_small_model,
            embedding_model=provider.embedding_model,
            reranker_model=provider.reranker_model,
            config=provider.config,
            is_active=provider.is_active,
            is_default=provider.is_default,
            api_key_masked=api_key_masked,
            created_at=provider.created_at,
            updated_at=provider.updated_at,
            health_status=health.status if health else None,
            health_last_check=health.last_check if health else None,
            response_time_ms=health.response_time_ms if health else None,
            error_message=health.error_message if health else None,
            resilience=resilience,
        )

    async def update_provider(
        self, provider_id: UUID, config: ProviderConfigUpdate
    ) -> Optional[ProviderConfig]:
        """Update provider configuration."""
        logger.info(f"Updating provider: {provider_id}")

        # Validate provider exists
        existing = await self.repository.get_by_id(provider_id)
        if not existing:
            return None

        # If setting as default, unset other defaults
        if config.is_default and not existing.is_default:
            await self._clear_default_providers()

        # Update provider
        updated = await self.repository.update(provider_id, config)

        # Invalidate cache if active/default changed
        if config.is_active is not None or config.is_default is not None:
            self.resolution_service.invalidate_cache()

        logger.info(f"Updated provider: {provider_id}")
        return updated

    async def delete_provider(self, provider_id: UUID) -> bool:
        """Delete provider (soft delete)."""
        logger.info(f"Deleting provider: {provider_id}")

        success = await self.repository.delete(provider_id)

        if success:
            # Invalidate cache
            self.resolution_service.invalidate_cache()

        return success

    async def check_provider_health(self, provider_id: UUID) -> ProviderHealth:
        """
        Perform health check on provider.

        This method tests the provider's API by making a simple request
        to verify it's working correctly.

        Args:
            provider_id: Provider to check

        Returns:
            Health check result
        """
        import time

        import httpx

        logger.info(f"Checking health for provider: {provider_id}")

        provider = await self.repository.get_by_id(provider_id)
        if not provider:
            raise ValueError(f"Provider not found: {provider_id}")

        start_time = time.time()
        status = "healthy"
        error_message = None
        response_time_ms = None

        try:
            # Decrypt API key
            api_key = self.encryption_service.decrypt(provider.api_key_encrypted)

            # Make a simple test request (using litellm or direct HTTP)
            # All providers support custom base_url for proxy/self-hosted scenarios
            async with httpx.AsyncClient(timeout=5.0) as client:
                provider_type = provider.provider_type
                base_url = provider.base_url

                if provider_type == "openai":
                    # OpenAI supports custom base_url (e.g., for OpenAI-compatible APIs)
                    api_base = base_url or "https://api.openai.com/v1"
                    response = await client.get(
                        f"{api_base}/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    status = "healthy" if response.status_code == 200 else "unhealthy"
                    if response.status_code != 200:
                        error_message = f"HTTP {response.status_code}"

                elif provider_type == "qwen":
                    # Test Qwen API
                    api_base = base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
                    response = await client.get(
                        f"{api_base}/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    status = "healthy" if response.status_code == 200 else "unhealthy"
                    if response.status_code != 200:
                        error_message = f"HTTP {response.status_code}"

                elif provider_type == "gemini":
                    # Test Google Gemini API
                    api_base = base_url or "https://generativelanguage.googleapis.com"
                    model = provider.llm_model or "gemini-pro"
                    response = await client.get(
                        f"{api_base}/v1beta/models/{model}",
                        headers={"x-goog-api-key": api_key},
                    )
                    status = "healthy" if response.status_code == 200 else "unhealthy"
                    if response.status_code != 200:
                        error_message = f"HTTP {response.status_code}"

                elif provider_type == "anthropic":
                    # Anthropic Claude API
                    api_base = base_url or "https://api.anthropic.com"
                    response = await client.get(
                        f"{api_base}/v1/models",
                        headers={
                            "x-api-key": api_key,
                            "anthropic-version": "2023-06-01",
                        },
                    )
                    status = "healthy" if response.status_code == 200 else "unhealthy"
                    if response.status_code != 200:
                        error_message = f"HTTP {response.status_code}"

                elif provider_type == "deepseek":
                    # Deepseek API
                    api_base = base_url or "https://api.deepseek.com/v1"
                    response = await client.get(
                        f"{api_base}/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    status = "healthy" if response.status_code == 200 else "unhealthy"
                    if response.status_code != 200:
                        error_message = f"HTTP {response.status_code}"

                elif provider_type == "zai":
                    # ZhipuAI (Z.AI) API
                    api_base = base_url or "https://open.bigmodel.cn/api/paas/v4"
                    response = await client.get(
                        f"{api_base}/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    status = "healthy" if response.status_code == 200 else "unhealthy"
                    if response.status_code != 200:
                        error_message = f"HTTP {response.status_code}"

                elif provider_type == "groq":
                    # Groq API
                    api_base = base_url or "https://api.groq.com/openai/v1"
                    response = await client.get(
                        f"{api_base}/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    status = "healthy" if response.status_code == 200 else "unhealthy"
                    if response.status_code != 200:
                        error_message = f"HTTP {response.status_code}"

                elif provider_type == "azure_openai":
                    # Azure OpenAI requires custom base_url
                    if not base_url:
                        status = "unhealthy"
                        error_message = "Azure OpenAI requires a custom base URL"
                    else:
                        response = await client.get(
                            f"{base_url}/models",
                            headers={"api-key": api_key},
                        )
                        status = "healthy" if response.status_code == 200 else "unhealthy"
                        if response.status_code != 200:
                            error_message = f"HTTP {response.status_code}"

                elif provider_type == "cohere":
                    # Cohere API
                    api_base = base_url or "https://api.cohere.com"
                    response = await client.get(
                        f"{api_base}/v1/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    status = "healthy" if response.status_code == 200 else "unhealthy"
                    if response.status_code != 200:
                        error_message = f"HTTP {response.status_code}"

                elif provider_type == "mistral":
                    # Mistral API
                    api_base = base_url or "https://api.mistral.ai/v1"
                    response = await client.get(
                        f"{api_base}/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    status = "healthy" if response.status_code == 200 else "unhealthy"
                    if response.status_code != 200:
                        error_message = f"HTTP {response.status_code}"

                elif provider_type == "bedrock":
                    # AWS Bedrock is complex to test without boto3
                    # Mark as degraded (will be validated during actual usage)
                    status = "degraded"
                    error_message = "Bedrock health check not implemented, will be validated during usage"

                elif provider_type == "vertex":
                    # Google Vertex AI requires GCP authentication
                    # Mark as degraded (will be validated during actual usage)
                    status = "degraded"
                    error_message = "Vertex AI health check not implemented, will be validated during usage"

                else:
                    # Unknown provider, mark as degraded
                    status = "degraded"
                    error_message = f"Unknown provider type: {provider_type}"

            response_time_ms = int((time.time() - start_time) * 1000)

        except Exception as e:
            logger.error(f"Health check failed for provider {provider_id}: {e}")
            status = "unhealthy"
            error_message = str(e)
            response_time_ms = int((time.time() - start_time) * 1000)

        # Create health record
        from datetime import datetime

        health = ProviderHealth(
            provider_id=provider_id,
            status=status,
            last_check=datetime.now(timezone.utc),
            error_message=error_message,
            response_time_ms=response_time_ms,
        )

        await self.repository.create_health_check(health)

        logger.info(f"Health check complete for {provider_id}: {status}")
        return health

    async def assign_provider_to_tenant(
        self, tenant_id: str, provider_id: UUID, priority: int = 0
    ) -> TenantProviderMapping:
        """Assign provider to tenant."""
        logger.info(f"Assigning provider {provider_id} to tenant {tenant_id}")

        # Validate provider exists
        provider = await self.repository.get_by_id(provider_id)
        if not provider:
            raise ValueError(f"Provider not found: {provider_id}")

        mapping = await self.repository.assign_provider_to_tenant(tenant_id, provider_id, priority)

        # Invalidate cache for this tenant
        self.resolution_service.invalidate_cache(tenant_id=tenant_id)

        logger.info(f"Assigned provider {provider_id} to tenant {tenant_id}")
        return mapping

    async def unassign_provider_from_tenant(self, tenant_id: str, provider_id: UUID) -> bool:
        """Unassign provider from tenant."""
        logger.info(f"Unassigning provider {provider_id} from tenant {tenant_id}")

        success = await self.repository.unassign_provider_from_tenant(tenant_id, provider_id)

        if success:
            # Invalidate cache for this tenant
            self.resolution_service.invalidate_cache(tenant_id=tenant_id)

        return success

    async def get_tenant_provider(self, tenant_id: str) -> Optional[ProviderConfig]:
        """Get provider for tenant."""
        return await self.repository.find_tenant_provider(tenant_id)

    async def resolve_provider_for_tenant(self, tenant_id: str) -> ProviderConfig:
        """
        Resolve provider for tenant with fallback.

        Args:
            tenant_id: Tenant ID

        Returns:
            Resolved provider configuration

        Raises:
            NoActiveProviderError: If no active provider found
        """
        resolved = await self.repository.resolve_provider(tenant_id)
        logger.info(
            f"Resolved provider '{resolved.provider.name}' "
            f"for tenant '{tenant_id}' "
            f"(source: {resolved.resolution_source})"
        )
        return resolved.provider

    async def get_model_metadata(
        self,
        provider_id: UUID,
        model_type: str = "llm",
    ) -> ModelMetadata:
        """
        Get model metadata for context window management.

        Resolution order:
        1. Provider config.models[model_type] if defined
        2. Default model metadata registry by model name
        3. Conservative fallback defaults

        Args:
            provider_id: Provider ID
            model_type: Model type ("llm", "llm_small", "embedding", "reranker")

        Returns:
            ModelMetadata with context length, max output tokens, etc.
        """
        provider = await self.repository.get_by_id(provider_id)
        if not provider:
            logger.warning(f"Provider not found: {provider_id}, using fallback defaults")
            return get_default_model_metadata("unknown")

        # Try to get from provider config.models
        models_config = provider.config.get("models", {})
        if models_config and model_type in models_config:
            model_config = models_config[model_type]
            if isinstance(model_config, dict):
                try:
                    return ModelMetadata(**model_config)
                except Exception as e:
                    logger.warning(f"Invalid model config for {model_type}: {e}")

        # Fallback to default registry by model name
        model_name = self._get_model_name_by_type(provider, model_type)
        return get_default_model_metadata(model_name)

    async def get_model_context_length(
        self,
        provider_id: UUID,
        model_type: str = "llm",
    ) -> int:
        """
        Get model context length for context window sizing.

        Args:
            provider_id: Provider ID
            model_type: Model type ("llm", "llm_small")

        Returns:
            Maximum context window size in tokens
        """
        metadata = await self.get_model_metadata(provider_id, model_type)
        return metadata.context_length

    async def get_model_max_output(
        self,
        provider_id: UUID,
        model_type: str = "llm",
    ) -> int:
        """
        Get model max output tokens.

        Args:
            provider_id: Provider ID
            model_type: Model type ("llm", "llm_small")

        Returns:
            Maximum output tokens per request
        """
        metadata = await self.get_model_metadata(provider_id, model_type)
        return metadata.max_output_tokens

    def _get_model_name_by_type(self, provider: ProviderConfig, model_type: str) -> str:
        """Get model name from provider config by type."""
        if model_type == "llm":
            return provider.llm_model
        elif model_type == "llm_small":
            return provider.llm_small_model or provider.llm_model
        elif model_type == "embedding":
            return provider.embedding_model or "text-embedding-3-small"
        elif model_type == "reranker":
            return provider.reranker_model or "rerank-v3"
        return provider.llm_model

    async def log_usage(self, usage_log: LLMUsageLogCreate) -> LLMUsageLog:
        """Log LLM usage for tracking."""
        return await self.repository.create_usage_log(usage_log)

    async def get_usage_statistics(
        self,
        provider_id: Optional[UUID] = None,
        tenant_id: Optional[str] = None,
        operation_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List:
        """Get usage statistics."""
        return await self.repository.get_usage_statistics(
            provider_id, tenant_id, operation_type, start_date, end_date
        )

    async def _clear_default_providers(self):
        """Unset default flag from all providers."""
        providers = await self.repository.list_all()
        for provider in providers:
            if provider.is_default:
                await self.repository.update(provider.id, ProviderConfigUpdate(is_default=False))

    async def clear_all_providers(self) -> int:
        """
        Clear all LLM provider configurations.

        This is used when the encryption key changes or data is corrupted,
        requiring a full reset of provider configurations.

        Performs hard delete to remove providers completely from database,
        allowing recreation with the same name.

        Returns:
            Number of providers cleared
        """
        providers = await self.list_providers(include_inactive=True)
        count = len(providers)

        for provider in providers:
            try:
                await self.repository.delete(provider.id, hard_delete=True)
            except Exception as e:
                logger.warning(f"Failed to delete provider {provider.id}: {e}")

        logger.info(f"Cleared {count} providers (hard delete)")
        return count

    def _mask_api_key(self, encrypted_key: str) -> str:
        """
        Mask API key for display.

        Args:
            encrypted_key: Encrypted API key

        Returns:
            Masked API key (e.g., "sk-...xyz")
        """
        try:
            decrypted = self.encryption_service.decrypt(encrypted_key)
            if len(decrypted) <= 8:
                return "sk-***"
            return f"sk-{decrypted[:4]}...{decrypted[-4:]}"
        except ValueError as e:
            logger.warning(f"Failed to decrypt API key for masking (invalid format): {e}")
            return "sk-[ERROR]"
        except Exception as e:
            logger.error(f"Unexpected error decrypting API key for masking: {e}", exc_info=True)
            return "sk-[ERROR]"

    def _get_resilience_status(self, provider_type: ProviderType) -> ResilienceStatus:
        """
        Get resilience status for a provider (circuit breaker + rate limiter).

        Args:
            provider_type: Provider type

        Returns:
            ResilienceStatus with circuit breaker and rate limiter info
        """
        try:
            # Get circuit breaker status
            cb_registry = get_circuit_breaker_registry()
            circuit_breaker = cb_registry.get(provider_type)
            cb_status = circuit_breaker.get_status()

            # Map circuit breaker state
            cb_state_map = {
                "closed": CircuitBreakerState.CLOSED,
                "open": CircuitBreakerState.OPEN,
                "half_open": CircuitBreakerState.HALF_OPEN,
            }
            cb_state = cb_state_map.get(cb_status["state"], CircuitBreakerState.CLOSED)

            # Get rate limiter stats
            rate_limiter = get_provider_rate_limiter()
            rate_stats = rate_limiter.get_stats(provider_type)
            stats_data = rate_stats.get("stats", {})

            rate_limit = RateLimitStats(
                current_concurrent=stats_data.get("current_concurrent", 0),
                max_concurrent=stats_data.get("max_concurrent", 50),
                total_requests=stats_data.get("total_requests", 0),
                requests_per_minute=stats_data.get("current_minute_requests", 0),
                max_rpm=stats_data.get("max_rpm"),
            )

            return ResilienceStatus(
                circuit_breaker_state=cb_state,
                failure_count=cb_status.get("failure_count", 0),
                success_count=cb_status.get("success_count", 0),
                rate_limit=rate_limit,
                can_execute=circuit_breaker.can_execute(),
            )
        except Exception as e:
            logger.warning(f"Failed to get resilience status for {provider_type}: {e}")
            return ResilienceStatus()


# Singleton instance for dependency injection
_provider_service: Optional[ProviderService] = None


def get_provider_service(session: "AsyncSession" = None) -> ProviderService:
    """
    Get provider service instance.

    Args:
        session: Optional database session. If provided, creates a new
                 service instance with this session. If None, returns singleton.

    Returns:
        ProviderService instance
    """
    if session is not None:
        # Create new service with injected session
        from src.infrastructure.persistence.llm_providers_repository import (
            SQLAlchemyProviderRepository,
        )

        return ProviderService(repository=SQLAlchemyProviderRepository(session=session))

    global _provider_service
    if _provider_service is None:
        _provider_service = ProviderService()
    return _provider_service
