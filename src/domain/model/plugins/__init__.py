"""Domain contracts for the platform plugin kernel."""

from .events import (
    PLATFORM_PLUGIN_EVENTS,
    EventDefinition,
    MissingNextPolicy,
    PluginEventMode,
)
from .manifest import (
    CapabilityKind,
    PluginActivation,
    PluginBilling,
    PluginManifest,
    PluginManifestError,
    PluginRequirement,
    PluginResourceQuota,
    PluginRestartPolicy,
    PluginRuntimeKind,
    PluginScope,
    PluginTrust,
    ProvidedCapability,
    parse_plugin_manifest,
    parse_plugin_manifest_json,
)
from .runtime import CredentialReference, PluginGeneration, PluginScopeContext

__all__ = [
    "PLATFORM_PLUGIN_EVENTS",
    "CapabilityKind",
    "CredentialReference",
    "EventDefinition",
    "MissingNextPolicy",
    "PluginActivation",
    "PluginBilling",
    "PluginEventMode",
    "PluginGeneration",
    "PluginManifest",
    "PluginManifestError",
    "PluginRequirement",
    "PluginResourceQuota",
    "PluginRestartPolicy",
    "PluginRuntimeKind",
    "PluginScope",
    "PluginScopeContext",
    "PluginTrust",
    "ProvidedCapability",
    "parse_plugin_manifest",
    "parse_plugin_manifest_json",
]
