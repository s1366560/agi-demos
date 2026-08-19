"""Platform plugin kernel shared by Python services."""

from .context import CapabilityRegistry, PluginContext, PluginScopeContext
from .legacy_inventory_bridge import (
    LegacyInventoryBridge,
    LegacyInventoryDiagnostic,
    LegacyInventorySyncReceipt,
    LegacyPluginFacts,
)
from .llm_adapters import (
    LlmAdapterProvider,
    LlmAdapterProviderRegistry,
    LlmAdapterRegistration,
    LlmAdapterRequest,
    RoutedLlmAdapterProvider,
    get_llm_adapter_provider_registry,
)
from .profile import compose_profile, parse_profile_document

__all__ = [
    "CapabilityRegistry",
    "LegacyInventoryBridge",
    "LegacyInventoryDiagnostic",
    "LegacyInventorySyncReceipt",
    "LegacyPluginFacts",
    "LlmAdapterProvider",
    "LlmAdapterProviderRegistry",
    "LlmAdapterRegistration",
    "LlmAdapterRequest",
    "PluginContext",
    "PluginScopeContext",
    "RoutedLlmAdapterProvider",
    "compose_profile",
    "get_llm_adapter_provider_registry",
    "parse_profile_document",
]
