"""Platform plugin kernel shared by Python services."""

from .context import CapabilityRegistry, PluginContext, PluginScopeContext
from .profile import compose_profile, parse_profile_document

__all__ = [
    "CapabilityRegistry",
    "PluginContext",
    "PluginScopeContext",
    "compose_profile",
    "parse_profile_document",
]
