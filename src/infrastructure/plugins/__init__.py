"""Platform plugin kernel shared by Python services."""

from .context import CapabilityRegistry, PluginContext, PluginScopeContext
from .dump_config import DumpConfigError, dump_profile
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
from .service_registry import (
    ServiceConflictError,
    ServiceContext,
    ServiceDeclaration,
    ServiceDependencyError,
    ServiceRegistry,
)

__all__ = [
    "CapabilityRegistry",
    "DumpConfigError",
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
    "ServiceConflictError",
    "ServiceContext",
    "ServiceDeclaration",
    "ServiceDependencyError",
    "ServiceRegistry",
    "compose_profile",
    "dump_profile",
    "get_llm_adapter_provider_registry",
    "parse_profile_document",
]
