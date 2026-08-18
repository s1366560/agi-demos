"""Platform plugin kernel shared by Python services."""

from .context import CapabilityRegistry, PluginContext, PluginScopeContext
from .llm_adapters import (
    LegacyLlmAdapterProvider,
    LlmAdapterProvider,
    LlmAdapterRequest,
)
from .profile import compose_profile, parse_profile_document

__all__ = [
    "CapabilityRegistry",
    "LegacyLlmAdapterProvider",
    "LlmAdapterProvider",
    "LlmAdapterRequest",
    "PluginContext",
    "PluginScopeContext",
    "compose_profile",
    "parse_profile_document",
]
