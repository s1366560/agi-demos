"""Manifest parsing helpers for local runtime plugins."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .registry import PluginDiagnostic

LOCAL_PLUGIN_MANIFEST_FILE = "memstack.plugin.json"


@dataclass(frozen=True)
class PluginManifestMetadata:
    """Normalized manifest metadata for one plugin."""

    id: str
    manifest_path: str | None = None
    kind: str | None = None
    name: str | None = None
    description: str | None = None
    version: str | None = None
    channels: tuple[str, ...] = field(default_factory=tuple)
    providers: tuple[str, ...] = field(default_factory=tuple)
    skills: tuple[str, ...] = field(default_factory=tuple)
    contracts: dict[str, tuple[str, ...]] = field(default_factory=dict)
    activation: dict[str, Any] = field(default_factory=dict)
    command_aliases: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    tool_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    hook_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    config_schema: dict[str, Any] | None = None
    config_ui_hints: dict[str, Any] | None = None
    env_vars: dict[str, tuple[str, ...]] = field(default_factory=dict)


def load_local_plugin_manifest(
    plugin_dir: Path,
    *,
    plugin_name: str,
) -> tuple[PluginManifestMetadata | None, list[PluginDiagnostic]]:
    """Load optional local plugin manifest metadata."""
    manifest_path = plugin_dir / LOCAL_PLUGIN_MANIFEST_FILE
    if not manifest_path.exists():
        return None, []

    diagnostics: list[PluginDiagnostic] = []
    raw_payload = _read_json_manifest(manifest_path)
    if raw_payload is None:
        diagnostics.append(
            PluginDiagnostic(
                plugin_name=plugin_name,
                code="plugin_manifest_invalid",
                message=f"Failed to parse plugin manifest at {manifest_path}",
                level="error",
            )
        )
        return None, diagnostics

    metadata, payload_diagnostics = parse_plugin_manifest_payload(
        raw_payload,
        plugin_name=plugin_name,
        manifest_path=str(manifest_path),
        source="local manifest",
    )
    diagnostics.extend(payload_diagnostics)
    return metadata, diagnostics


def parse_plugin_manifest_payload(
    payload: Any,
    *,
    plugin_name: str,
    manifest_path: str | None = None,
    source: str = "manifest",
) -> tuple[PluginManifestMetadata | None, list[PluginDiagnostic]]:
    """Parse a manifest payload from local files or entrypoint metadata."""
    diagnostics: list[PluginDiagnostic] = []
    if not isinstance(payload, dict):
        diagnostics.append(
            PluginDiagnostic(
                plugin_name=plugin_name,
                code="plugin_manifest_invalid",
                message=f"{source} must be a JSON object",
                level="error",
            )
        )
        return None, diagnostics

    manifest_id = _normalize_str(payload.get("id"))
    if not manifest_id:
        diagnostics.append(
            PluginDiagnostic(
                plugin_name=plugin_name,
                code="plugin_manifest_invalid",
                message=f"{source} requires non-empty 'id'",
                level="error",
            )
        )
        return None, diagnostics

    metadata = PluginManifestMetadata(
        id=manifest_id,
        manifest_path=manifest_path,
        kind=_normalize_str(payload.get("kind")),
        name=_normalize_str(payload.get("name")),
        description=_normalize_str(payload.get("description")),
        version=_normalize_str(payload.get("version")),
        channels=normalize_string_list(payload.get("channels")),
        providers=normalize_string_list(payload.get("providers")),
        skills=normalize_string_list(payload.get("skills")),
        contracts=normalize_string_list_map(payload.get("contracts")),
        activation=normalize_dict(payload.get("activation")),
        command_aliases=normalize_command_aliases(payload.get("commandAliases")),
        tool_metadata=normalize_object_map(payload.get("toolMetadata")),
        hook_metadata=normalize_object_map(payload.get("hookMetadata")),
        config_schema=normalize_optional_dict(payload.get("configSchema")),
        config_ui_hints=normalize_optional_dict(payload.get("uiHints")),
        env_vars=normalize_manifest_env_vars(payload),
    )
    diagnostics.extend(validate_manifest_contracts(metadata, plugin_name=plugin_name))
    return metadata, diagnostics


def _read_json_manifest(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _normalize_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def normalize_string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    items: list[str] = []
    for item in value:
        if isinstance(item, str):
            normalized = item.strip()
            if normalized:
                items.append(normalized)
    return tuple(items)


def normalize_dict(value: Any) -> dict[str, Any]:
    """Return a shallow dict copy for manifest object fields."""
    return dict(value) if isinstance(value, dict) else {}


def normalize_optional_dict(value: Any) -> dict[str, Any] | None:
    """Return a shallow dict copy or None for optional manifest object fields."""
    return dict(value) if isinstance(value, dict) else None


def normalize_string_list_map(value: Any) -> dict[str, tuple[str, ...]]:
    """Normalize object values that declare named string-list contracts."""
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, tuple[str, ...]] = {}
    for raw_key, raw_items in value.items():
        key = _normalize_contract_family(raw_key)
        if key is None:
            continue
        items = normalize_string_list(raw_items)
        if items:
            normalized[key] = items
    return normalized


def normalize_object_map(value: Any) -> dict[str, dict[str, Any]]:
    """Normalize manifest object maps keyed by capability name."""
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_payload in value.items():
        key = _normalize_str(raw_key)
        if key is None or not isinstance(raw_payload, dict):
            continue
        normalized[key] = dict(raw_payload)
    return normalized


def normalize_command_aliases(value: Any) -> tuple[dict[str, Any], ...]:
    """Normalize OpenClaw-style command alias descriptors."""
    if not isinstance(value, list):
        return ()
    aliases: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _normalize_str(item.get("name"))
        if name is None:
            continue
        alias = dict(item)
        alias["name"] = name
        kind = _normalize_str(alias.get("kind"))
        if kind is not None:
            alias["kind"] = kind
        cli_command = _normalize_str(alias.get("cliCommand"))
        if cli_command is not None:
            alias["cliCommand"] = cli_command
        aliases.append(alias)
    return tuple(aliases)


def normalize_manifest_env_vars(payload: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """Normalize known manifest env-var declaration blocks."""
    env_vars: dict[str, tuple[str, ...]] = {}
    for field_name in ("envVars", "channelEnvVars", "providerAuthEnvVars"):
        env_vars.update(normalize_string_list_map(payload.get(field_name)))
    return env_vars


def validate_manifest_contracts(
    metadata: PluginManifestMetadata,
    *,
    plugin_name: str,
) -> list[PluginDiagnostic]:
    """Validate manifest-first ownership declarations without executing plugin code."""
    diagnostics: list[PluginDiagnostic] = []
    _append_missing_contract_diagnostics(
        diagnostics,
        plugin_name=plugin_name,
        family="channels",
        declared=metadata.contracts.get("channels", ()),
        advertised=metadata.channels,
    )
    _append_missing_contract_diagnostics(
        diagnostics,
        plugin_name=plugin_name,
        family="providers",
        declared=metadata.contracts.get("providers", ()),
        advertised=metadata.providers,
    )
    _append_command_activation_diagnostics(diagnostics, metadata, plugin_name=plugin_name)
    _append_metadata_contract_diagnostics(
        diagnostics,
        plugin_name=plugin_name,
        family="tools",
        declared=metadata.contracts.get("tools", ()),
        metadata_keys=tuple(metadata.tool_metadata.keys()),
    )
    _append_metadata_contract_diagnostics(
        diagnostics,
        plugin_name=plugin_name,
        family="hooks",
        declared=metadata.contracts.get("hooks", ()),
        metadata_keys=tuple(metadata.hook_metadata.keys()),
    )
    return diagnostics


def _append_missing_contract_diagnostics(
    diagnostics: list[PluginDiagnostic],
    *,
    plugin_name: str,
    family: str,
    declared: tuple[str, ...],
    advertised: tuple[str, ...],
) -> None:
    if not declared or not advertised:
        return
    declared_set = {item.lower() for item in declared}
    missing = [item for item in advertised if item.lower() not in declared_set]
    if missing:
        diagnostics.append(
            PluginDiagnostic(
                plugin_name=plugin_name,
                code="plugin_manifest_contract_mismatch",
                message=(
                    f"Manifest {family} must also be declared in contracts.{family}: "
                    f"{', '.join(missing)}"
                ),
                level="warning",
            )
        )


def _append_metadata_contract_diagnostics(
    diagnostics: list[PluginDiagnostic],
    *,
    plugin_name: str,
    family: str,
    declared: tuple[str, ...],
    metadata_keys: tuple[str, ...],
) -> None:
    if not declared or not metadata_keys:
        return
    declared_set = {item.lower() for item in declared}
    missing = [item for item in metadata_keys if item.lower() not in declared_set]
    if missing:
        diagnostics.append(
            PluginDiagnostic(
                plugin_name=plugin_name,
                code="plugin_manifest_contract_mismatch",
                message=(
                    f"Manifest {family} metadata must also be declared in contracts.{family}: "
                    f"{', '.join(missing)}"
                ),
                level="warning",
            )
        )


def _append_command_activation_diagnostics(
    diagnostics: list[PluginDiagnostic],
    metadata: PluginManifestMetadata,
    *,
    plugin_name: str,
) -> None:
    raw_commands = metadata.activation.get("onCommands")
    activation_commands = normalize_string_list(raw_commands)
    if not activation_commands:
        return
    declared_commands = {item.lower() for item in metadata.contracts.get("commands", ())}
    alias_names = {str(item.get("name", "")).lower() for item in metadata.command_aliases}
    alias_cli_commands = {
        str(item.get("cliCommand", "")).lower()
        for item in metadata.command_aliases
        if item.get("cliCommand")
    }
    known = declared_commands | alias_names | alias_cli_commands
    missing = [item for item in activation_commands if item.lower() not in known]
    if missing:
        diagnostics.append(
            PluginDiagnostic(
                plugin_name=plugin_name,
                code="plugin_manifest_activation_mismatch",
                message=(
                    "activation.onCommands should match contracts.commands or commandAliases: "
                    f"{', '.join(missing)}"
                ),
                level="warning",
            )
        )


def _normalize_contract_family(value: Any) -> str | None:
    normalized = _normalize_str(value)
    if normalized is None:
        return None
    aliases = {
        "clicommands": "cli_commands",
        "cliCommands": "cli_commands",
        "cli-commands": "cli_commands",
        "cli_commands": "cli_commands",
        "lifecyclehooks": "lifecycle_hooks",
        "lifecycleHooks": "lifecycle_hooks",
        "lifecycle-hooks": "lifecycle_hooks",
        "lifecycle_hooks": "lifecycle_hooks",
    }
    return aliases.get(normalized, aliases.get(normalized.lower(), normalized))
