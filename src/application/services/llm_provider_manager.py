"""
LLM Provider Manager.

Unified manager for all LLM provider operations, integrating:
- Adapter registry for provider creation
- Circuit breaker for failure protection
- Rate limiter for per-provider throttling
- Health checker for availability monitoring

This is the main entry point for obtaining LLM clients with
automatic resilience and fallback capabilities.

Example:
    manager = get_llm_provider_manager()

    # Get an LLM client with automatic fallback
    client = await manager.get_llm_client(
        tenant_id="tenant-1",
        preferred_provider=ProviderType.GEMINI,
    )

    # Check all provider health
    health_status = await manager.health_check_all()
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis.asyncio import Redis
from src.domain.llm_providers.llm_types import LLMClient, LLMConfig
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.domain.model.plugins import CredentialReference
from src.domain.ports.plugins import ResolvedLlmRoute
from src.infrastructure.llm.resilience import (
    CircuitBreakerRegistry,
    HealthChecker,
    HealthStatus,
    ProviderRateLimiter,
    get_circuit_breaker_registry,
    get_health_checker,
    get_provider_rate_limiter,
)
from src.infrastructure.plugins.context import PluginScopeContext
from src.infrastructure.plugins.llm_adapters import (
    LegacyLlmAdapterProvider,
    LlmAdapterProvider,
    LlmAdapterProviderRegistry,
    LlmAdapterRequest,
    freeze_adapter_kwargs,
    get_llm_adapter_provider_registry,
)
from src.infrastructure.plugins.llm_runtime import (
    CredentialLease,
    CredentialLeaseScope,
    LlmRouteResolver,
    ProviderMetadataRegistry,
    ProviderRouteConfig,
)

logger = logging.getLogger(__name__)


class OperationType(str, Enum):
    """Type of LLM operation for routing decisions."""

    LLM = "llm"  # Standard completion/chat
    EMBEDDING = "embedding"
    RERANK = "rerank"
    STRUCTURED_OUTPUT = "structured_output"  # JSON/structured responses
    VISION = "vision"  # Image understanding
    CODE = "code"  # Code generation/completion


class ProviderSelectionStrategy(str, Enum):
    """Strategy for selecting providers."""

    PREFERRED = "preferred"  # Use preferred provider if healthy
    ROUND_ROBIN = "round_robin"  # Rotate through healthy providers
    LEAST_LOADED = "least_loaded"  # Use least loaded provider
    FASTEST = "fastest"  # Use provider with lowest latency


class LLMProviderManager:
    """
    Unified manager for LLM provider operations.

    Coordinates adapter creation, resilience patterns, and intelligent
    provider routing with automatic fallback.
    """

    def __init__(
        self,
        circuit_breaker_registry: CircuitBreakerRegistry | None = None,
        rate_limiter: ProviderRateLimiter | None = None,
        health_checker: HealthChecker | None = None,
        redis_client: Redis | None = None,
        adapter_provider: LlmAdapterProvider | None = None,
        adapter_registry: LlmAdapterProviderRegistry | None = None,
    ) -> None:
        """
        Initialize the provider manager.

        Args:
            circuit_breaker_registry: Optional custom circuit breaker registry
            rate_limiter: Optional custom rate limiter
            health_checker: Optional custom health checker
            redis_client: Optional async Redis client for distributed
                resilience (circuit breaker state + rate limiting).
                When None, falls back to in-memory implementations.
        """
        self._circuit_breakers = circuit_breaker_registry or self._build_circuit_breaker_registry(
            redis_client
        )
        self._rate_limiter = rate_limiter or self._build_rate_limiter(redis_client)
        self._health_checker = health_checker or get_health_checker()
        self.provider_metadata = ProviderMetadataRegistry()
        self._route_configs: dict[str, ProviderRouteConfig] = {}
        self._route_resolver = LlmRouteResolver(
            providers=self._route_configs,
            lease_resolver=_NoopCredentialLeaseResolver(),
        )
        self._adapter_provider = adapter_provider or LegacyLlmAdapterProvider()
        self._adapter_registry = adapter_registry or get_llm_adapter_provider_registry()

        # Provider configurations (loaded from database or settings)
        self._provider_configs: dict[ProviderType, ProviderConfig] = {}

        # Fallback order for each operation type
        self._fallback_order: dict[OperationType, list[ProviderType]] = {
            OperationType.LLM: [
                ProviderType.OPENAI,
                ProviderType.OPENROUTER,
                ProviderType.MINIMAX,
                ProviderType.ANTHROPIC,
                ProviderType.GEMINI,
                ProviderType.DASHSCOPE,
                ProviderType.DEEPSEEK,
                ProviderType.OLLAMA,
                ProviderType.LMSTUDIO,
                ProviderType.VOLCENGINE,
            ],
            OperationType.EMBEDDING: [
                ProviderType.OPENAI,
                ProviderType.OPENROUTER,
                ProviderType.MINIMAX,
                ProviderType.DASHSCOPE,
                ProviderType.GEMINI,
                ProviderType.OLLAMA,
                ProviderType.LMSTUDIO,
                ProviderType.VOLCENGINE,
            ],
            OperationType.STRUCTURED_OUTPUT: [
                ProviderType.DASHSCOPE,  # Best structured output support
                ProviderType.OPENAI,
                ProviderType.OPENROUTER,
                ProviderType.GEMINI,
            ],
            OperationType.VISION: [
                ProviderType.GEMINI,  # Best vision support
                ProviderType.OPENAI,
                ProviderType.OPENROUTER,
                ProviderType.ANTHROPIC,
            ],
            OperationType.CODE: [
                ProviderType.DEEPSEEK,  # DeepSeek-Coder
                ProviderType.OPENAI,
                ProviderType.OPENROUTER,
                ProviderType.ANTHROPIC,
            ],
        }

    def _adapter_provider_for(self, provider_id: str) -> LlmAdapterProvider:
        """Resolve an explicit provider, or use legacy compatibility when allowed."""
        explicit = self._adapter_registry.get(provider_id)
        if explicit is not None:
            return explicit
        from src.configuration.config import get_settings

        settings = get_settings()
        remove_legacy = getattr(settings, "platform_plugin_llm_remove_legacy", False)
        if remove_legacy and not settings.platform_plugin_llm_v2:
            raise ValueError("PLATFORM_PLUGIN_LLM_REMOVE_LEGACY requires LLM routes V2")
        if remove_legacy:
            raise RuntimeError(
                "legacy LLM adapter fallback is disabled and no provider is registered"
            )
        return self._adapter_provider

    @staticmethod
    def _build_circuit_breaker_registry(
        redis_client: Redis | None,
    ) -> CircuitBreakerRegistry:
        """Build a CircuitBreakerRegistry with optional Redis store.

        When *redis_client* is provided, a
        ``RedisCircuitBreakerStore`` is created and passed to the
        registry so that circuit breaker state is persisted in Redis
        across restarts.  When ``None``, the plain in-memory registry
        is returned.
        """
        if redis_client is not None:
            try:
                from src.infrastructure.llm.resilience.redis_store import (
                    RedisCircuitBreakerStore,
                )

                store = RedisCircuitBreakerStore(
                    redis_client=redis_client,
                )
                logger.info(
                    "Using Redis-backed circuit breaker store",
                )
                return CircuitBreakerRegistry(state_store=store)
            except Exception:
                logger.warning(
                    "Failed to create Redis circuit breaker store, falling back to in-memory",
                    exc_info=True,
                )
        return get_circuit_breaker_registry()

    @staticmethod
    def _build_rate_limiter(
        redis_client: Redis | None,
    ) -> ProviderRateLimiter:
        """Build a rate limiter with optional Redis backing.

        Returns a ``RedisRateLimiter`` (which wraps a local
        ``ProviderRateLimiter``) when *redis_client* is provided,
        otherwise returns the global in-memory limiter.
        """
        if redis_client is not None:
            try:
                from src.infrastructure.llm.resilience.rate_limiter import (
                    RedisRateLimiter,
                )

                logger.info(
                    "Using Redis-backed rate limiter",
                )
                return RedisRateLimiter(  # type: ignore[return-value]
                    redis_client=redis_client,
                )
            except Exception:
                logger.warning(
                    "Failed to create Redis rate limiter, falling back to in-memory",
                    exc_info=True,
                )
        return get_provider_rate_limiter()

    def register_provider(
        self,
        provider_config: ProviderConfig,
    ) -> None:
        """
        Register a provider configuration.

        Args:
            provider_config: Provider configuration to register
        """
        provider_type = provider_config.provider_type
        self._provider_configs[provider_type] = provider_config

        # Register with health checker
        self._health_checker.register_provider(provider_type, provider_config)
        self._register_route_config(provider_config)

        logger.info(f"Registered provider: {provider_type.value}")

    def unregister_provider(self, provider_type: ProviderType) -> None:
        """Unregister a provider configuration."""
        self._provider_configs.pop(provider_type, None)
        self._health_checker.unregister_provider(provider_type)
        self._route_configs.pop(provider_type.value, None)

    def resolve_route(
        self,
        provider_type: ProviderType,
        model_id: str | None = None,
    ) -> ResolvedLlmRoute:
        """Resolve request-scoped provider facts without exposing credentials."""
        return self._route_resolver.resolve(provider_type.value, model_id=model_id)

    def _record_llm_route_shadow(
        self,
        provider_config: ProviderConfig,
        tenant_id: str | None,
        model_id: str | None,
    ) -> None:
        """Persist one bounded legacy/typed route comparison in shadow mode."""
        from src.configuration.config import get_settings
        from src.infrastructure.plugins.llm_runtime import LlmRouteResolutionError
        from src.infrastructure.plugins.rollout_buckets import (
            is_scope_selected,
            settings_allowlist,
            settings_percentage,
        )
        from src.infrastructure.plugins.shadow_rollout import (
            enqueue_shadow_rollout_event,
            make_shadow_rollout_event,
        )

        settings = get_settings()
        normalized_scope = (tenant_id or "").strip()
        if not is_scope_selected(
            capability="llm_routes",
            scope_id=normalized_scope or None,
            percentage=settings_percentage(settings, "platform_plugin_llm_shadow_percent"),
            allowlist=settings_allowlist(settings, "platform_plugin_shadow_scope_allowlist"),
        ):
            return

        raw_config = provider_config.config
        model_override = model_id or None
        legacy = {
            "provider_id": provider_config.provider_type.value,
            "model_id": model_override
            or provider_config.llm_model
            or provider_config.embedding_model
            or provider_config.reranker_model
            or "",
            "base_url": provider_config.base_url
            or f"memstack://provider/{provider_config.provider_type.value}",
            "credential_ref": f"vault://llm-provider/{provider_config.id}",
            "credential_revision": max(1, int(provider_config.updated_at.timestamp() * 1000)),
            "timeout_ms": _positive_int(raw_config.get("timeout_seconds"), 120) * 1000,
            "context_window": _positive_int(raw_config.get("context_window"), 128_000),
            "max_output_tokens": _positive_int(raw_config.get("max_output_tokens"), 8_192),
        }
        try:
            route = self.resolve_route(provider_config.provider_type, model_id=model_override)
            typed = {
                "provider_id": route.provider_id,
                "model_id": route.model_id,
                "base_url": route.base_url,
                "credential_ref": route.credential.ref,
                "credential_revision": route.credential.revision,
                "timeout_ms": route.timeout_ms,
                "context_window": route.context_window,
                "max_output_tokens": route.max_output_tokens,
            }
        except LlmRouteResolutionError as exc:
            typed = {"error": str(exc)}

        enqueue_shadow_rollout_event(
            make_shadow_rollout_event(
                capability="llm_routes",
                event_name="llm.route",
                hook_name="provider_route",
                scope_type="tenant" if normalized_scope else "global",
                scope_id=normalized_scope or "global",
                equal=legacy == typed,
                legacy_payload=legacy,
                typed_payload=typed,
            )
        )

    async def lease_route_credential(
        self,
        scope: PluginScopeContext,
        route: ResolvedLlmRoute,
    ) -> CredentialLeaseScope:
        """Lease a credential at an execution boundary; fail closed without vault."""
        return await self._route_resolver.lease(scope, route)

    def _register_route_config(self, provider_config: ProviderConfig) -> None:
        """Project a provider row into request-time route and metadata registries."""
        model_id = (
            provider_config.llm_model
            or provider_config.embedding_model
            or provider_config.reranker_model
            or ""
        )
        raw_config = provider_config.config
        route = ProviderRouteConfig(
            provider_id=provider_config.provider_type.value,
            provider_type=provider_config.provider_type.value,
            model_id=model_id,
            base_url=provider_config.base_url
            or f"memstack://provider/{provider_config.provider_type.value}",
            credential_ref=f"vault://llm-provider/{provider_config.id}",
            credential_revision=max(1, int(provider_config.updated_at.timestamp() * 1000)),
            timeout_ms=_positive_int(raw_config.get("timeout_seconds"), 120) * 1000,
            context_window=_positive_int(raw_config.get("context_window"), 128_000),
            max_output_tokens=_positive_int(raw_config.get("max_output_tokens"), 8_192),
        )
        provider_id = provider_config.provider_type.value
        self._route_configs[provider_id] = route
        self.provider_metadata.register(
            provider_id,
            {
                "provider_id": provider_id,
                "operation_type": provider_config.operation_type.value,
                "model_id": model_id,
                "pool_enabled": provider_config.pool_enabled,
                "pool_weight": provider_config.pool_weight,
                "context_window": route.context_window,
                "max_output_tokens": route.max_output_tokens,
            },
        )

    def get_provider_config(
        self,
        provider_type: ProviderType,
    ) -> ProviderConfig | None:
        """Get registered provider configuration."""
        return self._provider_configs.get(provider_type)

    async def get_llm_client(
        self,
        tenant_id: str | None = None,
        operation: OperationType = OperationType.LLM,
        preferred_provider: ProviderType | None = None,
        llm_config: LLMConfig | None = None,
        allow_fallback: bool = True,
        **kwargs: Any,
    ) -> LLMClient:
        """
        Get an LLM client with automatic health checking and fallback.

        Args:
            tenant_id: Optional tenant ID for multi-tenant configs
            operation: Type of operation (affects provider selection)
            preferred_provider: Preferred provider to use
            llm_config: Optional LLM configuration override
            allow_fallback: Whether to fallback to other providers
            **kwargs: Additional arguments for adapter creation

        Returns:
            Configured LLMClient instance

        Raises:
            RuntimeError: If no healthy provider is available
        """
        # Determine provider order
        providers_to_try = self._get_provider_order(
            operation=operation,
            preferred_provider=preferred_provider,
        )

        last_error: Exception | None = None

        for provider_type in providers_to_try:
            # Check if we have config for this provider
            provider_config = self._provider_configs.get(provider_type)
            if not provider_config:
                logger.debug(f"Skipping {provider_type.value}: no configuration registered")
                continue
            from src.configuration.config import get_settings

            rollout_settings = get_settings()
            resolved_route: ResolvedLlmRoute | None = None
            if rollout_settings.platform_plugin_llm_v2:
                resolved_route = self.resolve_route(
                    provider_type,
                    model_id=llm_config.model if llm_config is not None else None,
                )
                logger.debug(
                    "Resolved platform LLM route provider=%s model=%s credential_ref=%s",
                    provider_type.value,
                    resolved_route.model_id,
                    resolved_route.credential.ref,
                )
            elif rollout_settings.platform_plugin_llm_shadow:
                self._record_llm_route_shadow(
                    provider_config,
                    tenant_id,
                    llm_config.model if llm_config is not None else None,
                )

            # Check circuit breaker
            circuit_breaker = self._circuit_breakers.get(provider_type)
            if not circuit_breaker.can_execute():
                logger.debug(f"Skipping {provider_type.value}: circuit breaker open")
                continue

            # Check health status
            health = await self._health_checker.get_health(provider_type)
            if not health.is_healthy:
                logger.debug(
                    f"Skipping {provider_type.value}: unhealthy (status: {health.status.value})"
                )
                continue

            # Try to create adapter
            adapter_provider = self._adapter_provider_for(provider_type.value)
            try:
                adapter = adapter_provider.create_adapter(
                    LlmAdapterRequest(
                        route=resolved_route,
                        provider_config=provider_config,
                        llm_config=llm_config,
                        adapter_kwargs=freeze_adapter_kwargs(kwargs),
                    )
                )
                logger.debug(f"Created adapter for {provider_type.value}")
                return adapter

            except Exception as e:
                last_error = e
                logger.warning(f"Failed to create adapter for {provider_type.value}: {e}")
                circuit_breaker.record_failure()

                if not allow_fallback:
                    raise

        # No healthy provider available
        raise RuntimeError(
            f"No healthy LLM provider available for operation {operation.value}. "
            f"Last error: {last_error}"
        )

    @property
    def _route_rollout_enabled(self) -> bool:
        """Return whether V2 route resolution or shadow comparison is enabled."""
        from src.configuration.config import get_settings

        settings = get_settings()
        return settings.platform_plugin_llm_v2 or settings.platform_plugin_llm_shadow

    def _get_provider_order(
        self,
        operation: OperationType,
        preferred_provider: ProviderType | None,
    ) -> list[ProviderType]:
        """
        Get ordered list of providers to try.

        Args:
            operation: Operation type
            preferred_provider: Preferred provider (tried first if healthy)

        Returns:
            Ordered list of provider types
        """
        # Get default order for operation
        fallback_order = self._fallback_order.get(
            operation,
            self._fallback_order[OperationType.LLM],
        )

        # Build final order
        providers = []

        # Add preferred provider first if specified
        if preferred_provider:
            providers.append(preferred_provider)

        # Add remaining providers from fallback order
        for provider in fallback_order:
            if provider not in providers:
                providers.append(provider)

        # Add any remaining registered providers
        for provider in self._provider_configs.keys():
            if provider not in providers:
                providers.append(provider)

        return providers

    async def health_check_all(self) -> dict[ProviderType, dict[str, Any]]:
        """
        Check health of all registered providers.

        Returns:
            Dict mapping provider type to health status dict
        """
        results = {}

        for provider_type in self._provider_configs.keys():
            health = await self._health_checker.check_health(provider_type)
            circuit_breaker = self._circuit_breakers.get(provider_type)
            rate_stats = self._rate_limiter.get_stats(provider_type)

            results[provider_type] = {
                "health_status": health.status.value,
                "is_healthy": health.is_healthy,
                "response_time_ms": health.response_time_ms,
                "error_message": health.error_message,
                "circuit_breaker_state": circuit_breaker.state.value,
                "rate_limit_stats": rate_stats.get("stats", {}),
            }

        return results

    def get_healthy_providers(
        self,
        operation: OperationType = OperationType.LLM,
    ) -> list[ProviderType]:
        """
        Get list of healthy providers for an operation.

        Args:
            operation: Operation type for filtering

        Returns:
            List of healthy provider types
        """
        healthy = []
        fallback_order = self._fallback_order.get(
            operation,
            self._fallback_order[OperationType.LLM],
        )

        for provider_type in fallback_order:
            if provider_type not in self._provider_configs:
                continue

            # Check circuit breaker
            circuit_breaker = self._circuit_breakers.get(provider_type)
            if not circuit_breaker.can_execute():
                continue

            # Check cached health status
            status = self._health_checker.get_current_status().get(
                provider_type, HealthStatus.UNKNOWN
            )
            if status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED):
                healthy.append(provider_type)

        return healthy

    def set_fallback_order(
        self,
        operation: OperationType,
        providers: list[ProviderType],
    ) -> None:
        """
        Set custom fallback order for an operation type.

        Args:
            operation: Operation type
            providers: Ordered list of providers
        """
        self._fallback_order[operation] = providers

    def get_metrics(self) -> dict[str, Any]:
        """
        Get aggregated metrics for all providers.

        Returns:
            Dict with metrics per provider and aggregates
        """
        metrics: dict[str, Any] = {
            "providers": {},
            "totals": {
                "healthy_count": 0,
                "unhealthy_count": 0,
                "total_requests": 0,
            },
        }

        for provider_type in self._provider_configs.keys():
            rate_stats = self._rate_limiter.get_stats(provider_type)
            circuit_breaker = self._circuit_breakers.get(provider_type)
            health_status = self._health_checker.get_current_status().get(
                provider_type, HealthStatus.UNKNOWN
            )

            is_healthy = health_status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)

            metrics["providers"][provider_type.value] = {
                "is_healthy": is_healthy,
                "health_status": health_status.value,
                "circuit_state": circuit_breaker.state.value,
                "rate_limit": rate_stats.get("stats", {}),
            }

            if is_healthy:
                metrics["totals"]["healthy_count"] += 1
            else:
                metrics["totals"]["unhealthy_count"] += 1

            metrics["totals"]["total_requests"] += rate_stats.get("stats", {}).get(
                "total_requests", 0
            )

        return metrics

    async def start_health_monitoring(self) -> None:
        """Start background health monitoring."""
        await self._health_checker.start()

    async def stop_health_monitoring(self) -> None:
        """Stop background health monitoring."""
        await self._health_checker.stop()


def _positive_int(value: Any, default: int) -> int:
    """Coerce a public numeric provider setting to a positive integer."""
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


class _NoopCredentialLeaseResolver:
    """Fail-closed lease resolver for managers without a vault implementation."""

    async def resolve(
        self,
        scope: PluginScopeContext,
        credential: CredentialReference,
    ) -> CredentialLease:
        _ = scope
        raise RuntimeError(f"credential vault is not configured for {credential.ref}")


# Global manager instance
_manager: LLMProviderManager | None = None


def get_llm_provider_manager() -> LLMProviderManager:
    """Get the global LLM provider manager."""
    global _manager
    if _manager is None:
        _manager = LLMProviderManager()
    return _manager


def reset_manager() -> None:
    """Reset the global manager (for testing)."""
    global _manager
    _manager = None
