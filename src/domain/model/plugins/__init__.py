"""Domain contracts for the platform plugin kernel."""

from .manifest import (
    CapabilityKind,
    PluginActivation,
    PluginManifest,
    PluginManifestError,
    PluginRequirement,
    PluginRestartPolicy,
    PluginRuntimeKind,
    PluginScope,
    PluginTrust,
    ProvidedCapability,
    parse_plugin_manifest,
    parse_plugin_manifest_json,
)

__all__ = [
    "CapabilityKind",
    "PluginActivation",
    "PluginManifest",
    "PluginManifestError",
    "PluginRequirement",
    "PluginRestartPolicy",
    "PluginRuntimeKind",
    "PluginScope",
    "PluginTrust",
    "ProvidedCapability",
    "parse_plugin_manifest",
    "parse_plugin_manifest_json",
]
