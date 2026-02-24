"""
Provider Adapter Registry.

Centralized registry for managing LLM provider adapters.
All providers use LiteLLM as the unified adapter layer.

Features:
- Automatic adapter selection based on provider type
- LiteLLM as unified adapter for all providers
- Runtime adapter registration for custom providers

Example:
    registry = get_provider_adapter_registry()

    # Create adapter for a provider
    adapter = registry.create_adapter(provider_config)

    # Register custom adapter
    registry.register(ProviderType.CUSTOM, CustomAdapter)
"""

import logging
from typing import Any, Protocol

from src.domain.llm_providers.llm_types import LLMClient, LLMConfig
from src.domain.llm_providers.models import ProviderConfig, ProviderType

logger = logging.getLogger(__name__)


class AdapterFactory(Protocol):
    """Protocol for adapter factory functions."""

    def __call__(
        self,
        config: LLMConfig,
        provider_config: ProviderConfig,
        **kwargs: Any,
    ) -> LLMClient:
        """Create an adapter instance."""
        ...


class ProviderAdapterRegistry:
    """
    Registry for LLM provider adapters.

    All providers use LiteLLM as the unified adapter layer.
    Custom adapters can be registered for specific providers if needed.
    """

    def __init__(self) -> None:
        """Initialize the registry with default adapters."""
        self._adapters: dict[ProviderType, type[LLMClient] | AdapterFactory] = {}
        self._register_default_adapters()

    def _register_default_adapters(self) -> None:
        """Register default adapters for known providers."""
        # All providers use LiteLLM by default
        # No native adapters registered - LiteLLM handles everything
        logger.debug("Registry initialized - all providers use LiteLLM adapter")

    def register(
        self,
        provider_type: ProviderType,
        adapter_class: type[LLMClient] | AdapterFactory,
    ) -> None:
        """
        Register a custom adapter for a provider.

        Args:
            provider_type: The provider type to register
            adapter_class: The adapter class or factory function
        """
        self._adapters[provider_type] = adapter_class
        logger.info(f"Registered custom adapter for {provider_type.value}")

    def unregister(self, provider_type: ProviderType) -> None:
        """Unregister an adapter."""
        self._adapters.pop(provider_type, None)

    def _get_adapter_class(
        self,
        provider_type: ProviderType,
    ) -> type[LLMClient] | AdapterFactory:
        """
        Get adapter class for a provider.

        Uses lazy imports to avoid circular dependencies.
        """
        # Check if custom adapter is registered
        if provider_type in self._adapters:
            return self._adapters[provider_type]

        # All providers use LiteLLM
        from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient

        return LiteLLMClient

    def create_adapter(
        self,
        provider_config: ProviderConfig,
        llm_config: LLMConfig | None = None,
        **kwargs: Any,
    ) -> LLMClient:
        """
        Create an adapter instance for a provider.

        Args:
            provider_config: Provider configuration from database
            llm_config: Optional LLM configuration (model, temperature, etc.)
            **kwargs: Additional arguments passed to adapter constructor

        Returns:
            Configured LLMClient instance
        """
        provider_type = provider_config.provider_type

        # Build LLMConfig if not provided
        if llm_config is None:
            llm_config = LLMConfig(
                model=provider_config.llm_model,
                temperature=provider_config.temperature,  # type: ignore[attr-defined]
            )

        # Get adapter class
        adapter_class = self._get_adapter_class(provider_type)

        # Create adapter instance
        try:
            adapter = adapter_class(
                config=llm_config,
                provider_config=provider_config,  # type: ignore[call-arg]
                **kwargs,
            )
            logger.debug(f"Created {adapter_class.__name__} adapter for {provider_type.value}")  # type: ignore[union-attr]
            return adapter

        except Exception as e:
            logger.error(f"Failed to create adapter for {provider_type.value}: {e}")
            raise

    def get_supported_providers(self) -> list[ProviderType]:
        """Get list of all provider types (all supported via LiteLLM)."""
        return list(ProviderType)

    def get_registered_providers(self) -> list[ProviderType]:
        """Get list of explicitly registered provider types."""
        return list(self._adapters.keys())


# Global registry instance
_registry: ProviderAdapterRegistry | None = None


def get_provider_adapter_registry() -> ProviderAdapterRegistry:
    """Get the global provider adapter registry."""
    global _registry
    if _registry is None:
        _registry = ProviderAdapterRegistry()
    return _registry


def reset_registry() -> None:
    """Reset the global registry (for testing)."""
    global _registry
    _registry = None
