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

import logging
from enum import Enum
from typing import Any

from src.domain.llm_providers.llm_types import LLMClient, LLMConfig
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.llm.registry import get_provider_adapter_registry
from src.infrastructure.llm.resilience import (
    CircuitBreakerRegistry,
    HealthChecker,
    HealthStatus,
    ProviderRateLimiter,
    get_circuit_breaker_registry,
    get_health_checker,
    get_provider_rate_limiter,
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
    ):
        """
        Initialize the provider manager.

        Args:
            circuit_breaker_registry: Optional custom circuit breaker registry
            rate_limiter: Optional custom rate limiter
            health_checker: Optional custom health checker
        """
        self._registry = get_provider_adapter_registry()
        self._circuit_breakers = circuit_breaker_registry or get_circuit_breaker_registry()
        self._rate_limiter = rate_limiter or get_provider_rate_limiter()
        self._health_checker = health_checker or get_health_checker()

        # Provider configurations (loaded from database or settings)
        self._provider_configs: dict[ProviderType, ProviderConfig] = {}

        # Fallback order for each operation type
        self._fallback_order: dict[OperationType, list[ProviderType]] = {
            OperationType.LLM: [
                ProviderType.OPENAI,
                ProviderType.ANTHROPIC,
                ProviderType.GEMINI,
                ProviderType.DASHSCOPE,
                ProviderType.DEEPSEEK,
                ProviderType.OLLAMA,
                ProviderType.LMSTUDIO,
            ],
            OperationType.EMBEDDING: [
                ProviderType.OPENAI,
                ProviderType.DASHSCOPE,
                ProviderType.GEMINI,
                ProviderType.OLLAMA,
                ProviderType.LMSTUDIO,
            ],
            OperationType.STRUCTURED_OUTPUT: [
                ProviderType.DASHSCOPE,  # Best structured output support
                ProviderType.OPENAI,
                ProviderType.GEMINI,
            ],
            OperationType.VISION: [
                ProviderType.GEMINI,  # Best vision support
                ProviderType.OPENAI,
                ProviderType.ANTHROPIC,
            ],
            OperationType.CODE: [
                ProviderType.DEEPSEEK,  # DeepSeek-Coder
                ProviderType.OPENAI,
                ProviderType.ANTHROPIC,
            ],
        }

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

        logger.info(f"Registered provider: {provider_type.value}")

    def unregister_provider(self, provider_type: ProviderType) -> None:
        """Unregister a provider configuration."""
        self._provider_configs.pop(provider_type, None)
        self._health_checker.unregister_provider(provider_type)

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
                logger.debug(
                    f"Skipping {provider_type.value}: no configuration registered"
                )
                continue

            # Check circuit breaker
            circuit_breaker = self._circuit_breakers.get(provider_type)
            if not circuit_breaker.can_execute():
                logger.debug(
                    f"Skipping {provider_type.value}: circuit breaker open"
                )
                continue

            # Check health status
            health = await self._health_checker.get_health(provider_type)
            if not health.is_healthy:
                logger.debug(
                    f"Skipping {provider_type.value}: unhealthy "
                    f"(status: {health.status.value})"
                )
                continue

            # Try to create adapter
            try:
                adapter = self._registry.create_adapter(
                    provider_config=provider_config,
                    llm_config=llm_config,
                    **kwargs,
                )
                logger.debug(f"Created adapter for {provider_type.value}")
                return adapter

            except Exception as e:
                last_error = e
                logger.warning(
                    f"Failed to create adapter for {provider_type.value}: {e}"
                )
                circuit_breaker.record_failure()

                if not allow_fallback:
                    raise

        # No healthy provider available
        raise RuntimeError(
            f"No healthy LLM provider available for operation {operation.value}. "
            f"Last error: {last_error}"
        )

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

    async def health_check_all(self) -> dict[ProviderType, dict]:
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
            status = self._health_checker._current_status.get(
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

    def get_metrics(self) -> dict:
        """
        Get aggregated metrics for all providers.

        Returns:
            Dict with metrics per provider and aggregates
        """
        metrics = {
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
            health_status = self._health_checker._current_status.get(
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
