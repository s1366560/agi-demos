"""Platform plugin kernel shared by Python services."""

from .context import CapabilityRegistry, PluginContext, PluginScopeContext
from .llm_adapters import (
    LegacyLlmAdapterProvider,
    LlmAdapterProvider,
    LlmAdapterProviderRegistry,
    LlmAdapterRegistration,
    LlmAdapterRequest,
    get_llm_adapter_provider_registry,
)
from .profile import compose_profile, parse_profile_document

__all__ = [
    "CapabilityRegistry",
    "LegacyLlmAdapterProvider",
    "LlmAdapterProvider",
    "LlmAdapterProviderRegistry",
    "LlmAdapterRegistration",
    "LlmAdapterRequest",
    "PluginContext",
    "PluginScopeContext",
    "compose_profile",
    "get_llm_adapter_provider_registry",
    "parse_profile_document",
]
