"""
LLM Provider Service

Application service for managing LLM provider configurations.
Handles business logic and coordinates between domain and infrastructure layers.
"""

import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.provider_resolution_service import get_provider_resolution_service
from src.domain.llm_providers.models import (
    CircuitBreakerState,
    LLMUsageLog,
    LLMUsageLogCreate,
    ModelMetadata,
    OperationType,
    ProviderAuthMethod,
    ProviderConfig,
    ProviderConfigCreate,
    ProviderConfigResponse,
    ProviderConfigUpdate,
    ProviderHealth,
    ProviderProbeRequest,
    ProviderStatus,
    ProviderType,
    ProviderValidationResponse,
    RateLimitStats,
    ResilienceStatus,
    TenantProviderMapping,
    get_default_model_metadata,
)
from src.domain.llm_providers.repositories import ProviderRepository
from src.infrastructure.llm.provider_credentials import from_decrypted_api_key
from src.infrastructure.llm.resilience import (
    get_circuit_breaker_registry,
    get_health_checker,
    get_provider_rate_limiter,
)
from src.infrastructure.persistence.llm_providers_repository import SQLAlchemyProviderRepository
from src.infrastructure.security.encryption_service import get_encryption_service

logger = logging.getLogger(__name__)
_PROVIDER_VARIANT_SUFFIXES: tuple[str, ...] = ("_coding", "_embedding", "_reranker")


class ProviderService:
    """
    Service for LLM provider configuration management.

    Provides high-level operations for creating, updating, and managing
    LLM provider configurations with proper validation and error handling.
    """

    def __init__(self, repository: ProviderRepository | None = None) -> None:
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

        # If this is marked as default, unset other defaults for the same operation role.
        if config.is_default:
            await self._clear_default_providers(config.operation_type)

        # Create provider (idempotent - returns existing if another process created it)
        provider = await self.repository.create(config)

        # Invalidate cache (affects default provider resolution)
        self.resolution_service.invalidate_cache()
        await self._sync_health_checker_provider_type(provider.provider_type)

        logger.info(f"Created provider: {provider.id}")
        return provider

    async def list_providers(self, include_inactive: bool = False) -> list[ProviderConfig]:
        """List all providers."""
        return await self.repository.list_all(include_inactive=include_inactive)

    async def get_provider(self, provider_id: UUID) -> ProviderConfig | None:
        """Get provider by ID."""
        return await self.repository.get_by_id(provider_id)

    async def get_provider_response(self, provider_id: UUID) -> ProviderConfigResponse | None:
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

        return await self._provider_to_response(provider)

    async def get_provider_responses(
        self,
        providers: list[ProviderConfig],
    ) -> list[ProviderConfigResponse]:
        """Build API responses from already loaded provider configs."""
        return [await self._provider_to_response(provider) for provider in providers]

    async def _provider_to_response(self, provider: ProviderConfig) -> ProviderConfigResponse:
        """Build an API response without reloading the provider row."""
        # Get latest health status
        health = await self.repository.get_latest_health(provider.id)

        # Mask API key (show only last 4 characters)
        api_key_masked = self._mask_api_key(provider.api_key_encrypted)

        # Get resilience status
        resilience = self._get_resilience_status(provider.provider_type)

        return ProviderConfigResponse(
            id=provider.id,
            tenant_id=provider.tenant_id,
            name=provider.name,
            provider_type=provider.provider_type,
            operation_type=provider.operation_type,
            base_url=provider.base_url,
            llm_model=provider.llm_model,
            llm_small_model=provider.llm_small_model,
            embedding_model=provider.embedding_model,
            embedding_config=provider.embedding_config,
            reranker_model=provider.reranker_model,
            config=provider.config,
            is_active=provider.is_active,
            is_default=provider.is_default,
            is_enabled=provider.is_enabled,
            allowed_models=provider.allowed_models,
            blocked_models=provider.blocked_models,
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
    ) -> ProviderConfig | None:
        """Update provider configuration."""
        logger.info(f"Updating provider: {provider_id}")

        # Validate provider exists
        existing = await self.repository.get_by_id(provider_id)
        if not existing:
            return None
        original_provider_type = existing.provider_type

        target_operation = config.operation_type or existing.operation_type
        will_be_default = (
            config.is_default if config.is_default is not None else existing.is_default
        )

        # If setting as default, unset other defaults for the target operation role.
        if will_be_default and (
            not existing.is_default or target_operation != existing.operation_type
        ):
            await self._clear_default_providers(
                target_operation,
                exclude_provider_id=provider_id,
            )

        # Update provider
        updated = await self.repository.update(provider_id, config)

        self.resolution_service.invalidate_cache()
        self._invalidate_model_pool_cache()
        if updated is not None:
            await self._sync_health_checker_provider_type(original_provider_type)
            if updated.provider_type != original_provider_type:
                await self._sync_health_checker_provider_type(updated.provider_type)

        logger.info(f"Updated provider: {provider_id}")
        return updated

    def _invalidate_model_pool_cache(self) -> None:
        """Best-effort cache invalidation for pooled LLM routing."""
        try:
            from src.infrastructure.llm.model_pool import get_model_pool_service

            get_model_pool_service().invalidate()
        except Exception:
            logger.exception("Failed to invalidate model pool cache after provider update")

    async def delete_provider(self, provider_id: UUID) -> bool:
        """Delete provider (hard delete)."""
        logger.info(f"Deleting provider: {provider_id}")
        existing = await self.repository.get_by_id(provider_id)

        success = await self.repository.delete(provider_id, hard_delete=True)

        if success:
            # Invalidate cache
            self.resolution_service.invalidate_cache()
            if existing is not None:
                await self._sync_health_checker_provider_type(existing.provider_type)

        return success

    async def check_provider_health(self, provider_id: UUID) -> ProviderHealth:
        """Perform health check on provider."""
        import time

        logger.info(f"Checking health for provider: {provider_id}")

        provider = await self.repository.get_by_id(provider_id)
        if not provider:
            raise ValueError(f"Provider not found: {provider_id}")

        start_time = time.time()
        status = "healthy"
        error_message = None
        response_time_ms = None

        try:
            decrypted_key = self.encryption_service.decrypt(provider.api_key_encrypted)
            api_key = from_decrypted_api_key(decrypted_key)
            assert api_key is not None, "Decrypted API key is None"
            status, error_message = await self._check_provider_endpoint(provider, api_key)
            response_time_ms = int((time.time() - start_time) * 1000)
        except Exception as e:
            logger.error(f"Health check failed for provider {provider_id}: {e}")
            status = "unhealthy"
            error_message = str(e)
            response_time_ms = int((time.time() - start_time) * 1000)

        health = ProviderHealth(
            provider_id=provider_id,
            status=ProviderStatus(status),
            last_check=datetime.now(UTC),
            error_message=error_message,
            response_time_ms=response_time_ms,
        )

        await self.repository.create_health_check(health)
        logger.info(f"Health check complete for {provider_id}: {status}")
        return health

    async def test_provider_connection(
        self,
        config: ProviderProbeRequest,
    ) -> ProviderValidationResponse:
        """Run a live provider health check from form data without persisting it."""
        import time

        provider_id = uuid4()
        start_time = time.time()
        now = datetime.now(UTC)
        status = "healthy"
        error_message = None
        response_time_ms = None

        api_key = config.api_key or ""
        if config.auth_method == ProviderAuthMethod.ENVIRONMENT:
            environment_variable = config.environment_variable
            api_key = os.getenv(environment_variable, "").strip() if environment_variable else ""
            if not api_key:
                health = ProviderHealth(
                    provider_id=provider_id,
                    status=ProviderStatus.UNHEALTHY,
                    last_check=datetime.now(UTC),
                    error_message=None,
                    response_time_ms=0,
                )
                return ProviderValidationResponse.from_health(
                    health,
                    probed=False,
                    detail="Environment credential is not configured",
                    catalog=None,
                    environment_variable=environment_variable,
                )

        provider = ProviderConfig(
            id=provider_id,
            api_key_encrypted="",
            created_at=now,
            updated_at=now,
            **config.model_dump(exclude={"api_key", "auth_method", "environment_variable"}),
        )

        try:
            status, error_message = await self._check_provider_endpoint(provider, api_key)
            response_time_ms = int((time.time() - start_time) * 1000)
        except Exception as e:
            logger.error("Provider connection test failed for %s: %s", config.provider_type, e)
            status = "unhealthy"
            error_message = str(e)
            response_time_ms = int((time.time() - start_time) * 1000)

        health = ProviderHealth(
            provider_id=provider_id,
            status=ProviderStatus(status),
            last_check=datetime.now(UTC),
            error_message=error_message,
            response_time_ms=response_time_ms,
        )
        return ProviderValidationResponse.from_health(
            health,
            probed=True,
            detail=None,
            catalog=None,
            environment_variable=config.environment_variable,
        )

    async def _check_provider_endpoint(
        self,
        provider: ProviderConfig,
        api_key: str,
    ) -> tuple[str, str | None]:
        """Check a provider endpoint and return (status, error_message)."""
        import httpx

        provider_type = provider.provider_type
        normalized_provider_type = self._normalize_provider_type(provider_type)
        base_url = provider.base_url

        # Providers with standard GET /models + Bearer auth
        bearer_providers: dict[str, str] = {
            "openai": "https://api.openai.com/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "deepseek": "https://api.deepseek.com/v1",
            "minimax": "https://api.minimax.io/v1",
            "zai": "https://open.bigmodel.cn/api/paas/v4",
            "kimi": "https://api.moonshot.cn/v1",
            "groq": "https://api.groq.com/openai/v1",
            "mistral": "https://api.mistral.ai/v1",
            "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            if normalized_provider_type in bearer_providers:
                return await self._http_health_check(
                    client,
                    url=f"{base_url or bearer_providers[normalized_provider_type]}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )

            return await self._check_special_provider(
                client, normalized_provider_type, base_url, api_key, provider
            )

    @staticmethod
    def _normalize_provider_type(provider_type: ProviderType | str) -> str:
        """Normalize specialized provider variants to their base provider type."""
        normalized = str(getattr(provider_type, "value", provider_type)).strip().lower()
        for suffix in _PROVIDER_VARIANT_SUFFIXES:
            if normalized.endswith(suffix):
                normalized = normalized.removesuffix(suffix)
                break
        return normalized

    async def _check_special_provider(
        self,
        client: "httpx.AsyncClient",
        provider_type: str,
        base_url: str | None,
        api_key: str,
        provider: ProviderConfig,
    ) -> tuple[str, str | None]:
        """Check providers with non-standard health check patterns."""
        if provider_type == "bedrock":
            return await self._check_bedrock_provider(api_key, provider)
        if provider_type == "vertex":
            return await self._check_vertex_provider(client, base_url, api_key, provider)
        if provider_type == "azure_openai" and not base_url:
            return "unhealthy", "Azure OpenAI requires a custom base URL"
        check_spec = self._build_special_check_spec(provider_type, base_url, api_key, provider)
        if check_spec is None:
            return "degraded", f"Unknown provider type: {provider_type}"
        url, headers = check_spec
        return await self._http_health_check(client, url=url, headers=headers)

    @staticmethod
    def _build_special_check_spec(
        provider_type: str,
        base_url: str | None,
        api_key: str,
        provider: ProviderConfig,
    ) -> tuple[str, dict[str, str] | None] | None:
        """Return (url, headers) for special provider health checks, or None if unknown."""
        builders: dict[str, tuple[str, str, dict[str, str] | None]] = {
            "gemini": (
                base_url or "https://generativelanguage.googleapis.com",
                "/v1beta/models/{model}",
                {"x-goog-api-key": api_key},
            ),
            "anthropic": (
                base_url or "https://api.anthropic.com",
                "/v1/models",
                {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            ),
            "azure_openai": (base_url or "", "/models", {"api-key": api_key}),
            "ollama": (base_url or "http://localhost:11434", "/api/tags", None),
            "lmstudio": (
                base_url or "http://localhost:1234/v1",
                "/models",
                {"Authorization": f"Bearer {api_key}"} if api_key else None,
            ),
            "cohere": (
                base_url or "https://api.cohere.com",
                "/v1/models",
                {"Authorization": f"Bearer {api_key}"},
            ),
        }
        spec = builders.get(provider_type)
        if spec is None:
            return None
        api_base, path_template, headers = spec
        # Gemini uses model in URL path
        if provider_type == "gemini":
            model = provider.llm_model or "gemini-pro"
            path_template = path_template.format(model=model)
        return f"{api_base}{path_template}", headers

    @staticmethod
    async def _check_bedrock_provider(
        api_key: str,
        provider: ProviderConfig,
    ) -> tuple[str, str | None]:
        """Check AWS Bedrock by listing foundation models with configured AWS credentials."""
        config = provider.config or {}
        secret_key = config.get("aws_secret_access_key") or config.get("secret_access_key")
        if not secret_key:
            return "unhealthy", "Bedrock health check requires aws_secret_access_key in config"

        import aioboto3

        region = str(
            config.get("region_name")
            or config.get("region")
            or config.get("aws_region")
            or "us-east-1"
        )
        session_token = config.get("aws_session_token") or config.get("session_token")
        session_kwargs: dict[str, str] = {
            "aws_access_key_id": api_key,
            "aws_secret_access_key": str(secret_key),
            "region_name": region,
        }
        if session_token:
            session_kwargs["aws_session_token"] = str(session_token)

        session = aioboto3.Session(**session_kwargs)
        async with cast(Any, session.client("bedrock")) as bedrock_client:
            await bedrock_client.list_foundation_models()
        return "healthy", None

    async def _check_vertex_provider(
        self,
        client: "httpx.AsyncClient",
        base_url: str | None,
        api_key: str,
        provider: ProviderConfig,
    ) -> tuple[str, str | None]:
        """Check Vertex AI Model Garden with an OAuth access token."""
        config = provider.config or {}
        project_id = config.get("project_id") or config.get("project")
        if not project_id:
            return "unhealthy", "Vertex AI health check requires project_id in config"

        access_token = config.get("access_token") or config.get("oauth_token")
        if not access_token and api_key.startswith("ya29."):
            access_token = api_key
        if not access_token:
            return "unhealthy", "Vertex AI health check requires an OAuth access_token in config"

        location = str(config.get("location") or config.get("region") or "us-central1")
        api_base = (base_url or f"https://{location}-aiplatform.googleapis.com/v1").rstrip("/")
        url = f"{api_base}/projects/{project_id}/locations/{location}/publishers/google/models"
        return await self._http_health_check(
            client,
            url=url,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    @staticmethod
    async def _http_health_check(
        client: "httpx.AsyncClient",
        url: str,
        headers: dict[str, str] | None,
    ) -> tuple[str, str | None]:
        """Perform a GET request and return (status, error_message)."""
        response = await client.get(url, headers=headers)
        if response.status_code == 200:
            return "healthy", None
        return "unhealthy", f"HTTP {response.status_code}"

    async def _sync_health_checker_provider_type(self, provider_type: ProviderType) -> None:
        """Synchronize health checker registration for one provider type."""
        active_providers = await self.repository.list_active()
        candidates = [
            provider
            for provider in active_providers
            if provider.is_active
            and provider.is_enabled
            and provider.provider_type == provider_type
            and ProviderService._coerce_operation_type(provider.operation_type) == OperationType.LLM
        ]
        checker = get_health_checker()
        if not candidates:
            checker.unregister_provider(provider_type)
            return

        representative = self._select_health_check_provider(candidates)
        checker.register_provider(provider_type, representative)

    @staticmethod
    def _select_health_check_provider(providers: list[ProviderConfig]) -> ProviderConfig:
        """Pick deterministic provider config when multiple entries share one type."""
        return min(
            providers,
            key=lambda provider: (
                0 if provider.is_default else 1,
                provider.created_at,
                str(provider.id),
            ),
        )

    @staticmethod
    def _sync_health_checker_registration(provider: ProviderConfig) -> None:
        """Deprecated shim kept for backward compatibility in tests/extensions."""
        checker = get_health_checker()
        if provider.is_active and provider.is_enabled:
            checker.register_provider(provider.provider_type, provider)
        else:
            checker.unregister_provider(provider.provider_type)

    async def assign_provider_to_tenant(
        self,
        tenant_id: str,
        provider_id: UUID,
        priority: int = 0,
        operation_type: OperationType = OperationType.LLM,
    ) -> TenantProviderMapping:
        """Assign provider to tenant."""
        logger.info(f"Assigning provider {provider_id} to tenant {tenant_id}")

        # Validate provider exists
        provider = await self.repository.get_by_id(provider_id)
        if not provider:
            raise ValueError(f"Provider not found: {provider_id}")
        provider_operation_type = self._coerce_operation_type(
            getattr(provider, "operation_type", OperationType.LLM)
        )
        if provider_operation_type != operation_type:
            raise ValueError(
                f"Provider operation_type '{provider_operation_type.value}' "
                f"cannot be assigned for '{operation_type.value}'"
            )

        mapping = await self.repository.assign_provider_to_tenant(
            tenant_id, provider_id, priority, operation_type
        )

        # Invalidate cache for this tenant
        self.resolution_service.invalidate_cache(tenant_id=tenant_id)

        logger.info(f"Assigned provider {provider_id} to tenant {tenant_id}")
        return mapping

    async def unassign_provider_from_tenant(
        self,
        tenant_id: str,
        provider_id: UUID,
        operation_type: OperationType = OperationType.LLM,
    ) -> bool:
        """Unassign provider from tenant."""
        logger.info(f"Unassigning provider {provider_id} from tenant {tenant_id}")

        success = await self.repository.unassign_provider_from_tenant(
            tenant_id, provider_id, operation_type
        )

        if success:
            # Invalidate cache for this tenant
            self.resolution_service.invalidate_cache(tenant_id=tenant_id)

        return success

    async def get_tenant_provider(
        self,
        tenant_id: str,
        operation_type: OperationType = OperationType.LLM,
    ) -> ProviderConfig | None:
        """Get provider for tenant."""
        return await self.repository.find_tenant_provider(tenant_id, operation_type)

    async def get_tenant_providers(
        self,
        tenant_id: str,
        operation_type: OperationType | None = None,
    ) -> list[TenantProviderMapping]:
        """Get all providers assigned to tenant."""
        return await self.repository.get_tenant_providers(tenant_id, operation_type)

    async def resolve_provider_for_tenant(
        self,
        tenant_id: str,
        operation_type: OperationType = OperationType.LLM,
    ) -> ProviderConfig:
        """
        Resolve provider for tenant with fallback.

        Args:
            tenant_id: Tenant ID

        Returns:
            Resolved provider configuration

        Raises:
            NoActiveProviderError: If no active provider found
        """
        resolved = await self.repository.resolve_provider(tenant_id, operation_type)
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

        model_name = self._get_model_name_by_type(provider, model_type)
        return get_default_model_metadata(model_name if model_name is not None else "unknown")

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

    def _get_model_name_by_type(self, provider: ProviderConfig, model_type: str) -> str | None:
        if model_type == "llm":
            return provider.llm_model
        elif model_type == "llm_small":
            return provider.llm_small_model or provider.llm_model
        elif model_type == "embedding":
            if provider.embedding_config and provider.embedding_config.model:
                return provider.embedding_config.model
            return provider.embedding_model or "text-embedding-3-small"
        elif model_type == "reranker":
            return provider.reranker_model or "rerank-v3"
        return provider.llm_model

    async def log_usage(self, usage_log: LLMUsageLogCreate) -> LLMUsageLog:
        """Log LLM usage for tracking."""
        return await self.repository.create_usage_log(usage_log)

    async def get_usage_statistics(
        self,
        provider_id: UUID | None = None,
        tenant_id: str | None = None,
        operation_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[Any]:
        """Get usage statistics."""
        return await self.repository.get_usage_statistics(
            provider_id, tenant_id, operation_type, start_date, end_date
        )

    @staticmethod
    def _coerce_operation_type(value: object) -> OperationType:
        """Normalize operation type values from domain models, ORM rows, or tests."""
        if isinstance(value, OperationType):
            return value
        if isinstance(value, str):
            try:
                return OperationType(value)
            except ValueError:
                return OperationType.LLM
        return OperationType.LLM

    async def _clear_default_providers(
        self,
        operation_type: OperationType = OperationType.LLM,
        *,
        exclude_provider_id: UUID | None = None,
    ) -> None:
        """Unset default flag from providers in the same operation role."""
        providers = await self.repository.list_all()
        for provider in providers:
            provider_operation_type = self._coerce_operation_type(
                getattr(provider, "operation_type", OperationType.LLM)
            )
            if (
                provider.is_default
                and provider_operation_type == operation_type
                and provider.id != exclude_provider_id
            ):
                await self.repository.update(
                    provider.id, ProviderConfigUpdate(name=None, api_key=None, is_default=False)
                )

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
                await cast(Any, self.repository).delete(provider.id, hard_delete=True)
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
            normalized = from_decrypted_api_key(decrypted)
            if not normalized:
                return "(local-no-key)"
            if len(normalized) <= 8:
                return "sk-***"
            return f"sk-{normalized[:4]}...{normalized[-4:]}"
        except ValueError as e:
            logger.warning(
                "Failed to decrypt API key for masking invalid_format=true error_type=%s",
                type(e).__name__,
            )
            return "sk-[ERROR]"
        except Exception as e:
            logger.error(
                "Unexpected error decrypting API key for masking error_type=%s",
                type(e).__name__,
            )
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
            return ResilienceStatus(
                circuit_breaker_state=CircuitBreakerState.CLOSED,
                failure_count=0,
                success_count=0,
                can_execute=True,
            )


# Singleton instance for dependency injection
_provider_service: ProviderService | None = None


def get_provider_service(session: "AsyncSession | None" = None) -> ProviderService:
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
