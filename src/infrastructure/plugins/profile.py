"""Declarative plugin profile composition and deterministic snapshots."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from src.domain.model.plugins import (
    PluginManifest,
    PluginRequirement,
    ProvidedCapability,
    parse_plugin_manifest,
)


class ProfileCompositionError(ValueError):
    """Raised when a profile cannot compose into a valid runtime snapshot."""


PROFILE_SNAPSHOT_TYPE_URL = "types.memstack.ai/plugin.profile.v1"


@dataclass(frozen=True)
class ProfileRow:
    """One plugin activation row contributed by a profile layer."""

    id: str
    enabled: bool = True
    config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProfileLayer:
    """An ordered bundle layer containing plugin rows."""

    id: str
    rows: tuple[ProfileRow, ...]


@dataclass(frozen=True)
class ProfilePatch:
    """A whole-config patch targeting one plugin row id."""

    target: str
    enabled: bool | None = None
    config: Mapping[str, Any] | None = None
    remove: bool = False


@dataclass(frozen=True)
class ProfileDocument:
    """Parsed profile document before manifest validation."""

    profile_id: str
    layers: tuple[ProfileLayer, ...]
    patches: tuple[ProfilePatch, ...] = ()


@dataclass(frozen=True)
class PluginSnapshotRow:
    """One enabled plugin and its complete effective configuration."""

    manifest: PluginManifest
    config: dict[str, Any]
    layer_id: str

    def to_payload(self) -> dict[str, Any]:
        """Return the canonical wire representation."""
        payload = self.manifest.to_payload()
        payload["config"] = dict(self.config)
        payload["layer_id"] = self.layer_id
        return payload


@dataclass(frozen=True)
class ProfileSnapshot:
    """Immutable effective plugin composition shared by every data plane."""

    profile_id: str
    schema_version: int
    rows: tuple[PluginSnapshotRow, ...]
    digest: str

    def to_payload(self) -> dict[str, Any]:
        """Return the canonical JSON-compatible snapshot payload."""
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "plugins": [row.to_payload() for row in self.rows],
            "digest": self.digest,
        }

    def to_json(self) -> str:
        """Return canonical JSON used for digesting and cross-runtime transfer."""
        return json.dumps(self.to_payload(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ControlPlaneEnvelope:
    """Versioned snapshot envelope consumed by a data-plane reconciler."""

    version: int
    nonce: str
    snapshot_digest: str
    type_url: str

    def to_payload(self) -> dict[str, Any]:
        """Return the canonical control-plane wire representation."""
        return {
            "version": self.version,
            "nonce": self.nonce,
            "snapshot_digest": self.snapshot_digest,
            "type_url": self.type_url,
        }


def parse_profile_document(payload: object) -> ProfileDocument:
    """Parse and structurally validate a profile document payload."""
    if not isinstance(payload, dict):
        raise ProfileCompositionError("profile document must be an object")

    profile = payload.get("profile")
    if not isinstance(profile, dict):
        raise ProfileCompositionError("profile must be an object")
    profile_id = profile.get("id")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ProfileCompositionError("profile.id must be a non-empty string")

    raw_layers = profile.get("layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        raise ProfileCompositionError("profile.layers must be a non-empty array")

    layers = tuple(_parse_layer(raw_layer, index) for index, raw_layer in enumerate(raw_layers))
    layer_ids = [layer.id for layer in layers]
    if len(set(layer_ids)) != len(layer_ids):
        raise ProfileCompositionError("profile layer ids must be unique")

    raw_patches = payload.get("patches", [])
    if not isinstance(raw_patches, list):
        raise ProfileCompositionError("patches must be an array")
    patches = tuple(_parse_patch(raw_patch, index) for index, raw_patch in enumerate(raw_patches))
    return ProfileDocument(
        profile_id=profile_id,
        layers=layers,
        patches=patches,
    )


def load_profile_document(path: str | Path) -> ProfileDocument:
    """Load and parse a YAML profile document."""
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileCompositionError(f"failed to load profile {path}: {exc}") from exc
    return parse_profile_document(payload)


def compose_profile(
    document: ProfileDocument,
    manifests: Mapping[str, PluginManifest | dict[str, Any] | str],
) -> ProfileSnapshot:
    """Compose layers and patches into a validated dependency-ordered snapshot."""
    resolved_manifests = {
        plugin_id: _resolve_manifest(plugin_id, manifest)
        for plugin_id, manifest in manifests.items()
    }
    effective_rows = _compose_rows(document)
    errors: list[str] = []
    active_manifests: dict[str, PluginManifest] = {}
    layer_by_plugin: dict[str, str] = {}

    for plugin_id, (row, layer_id) in effective_rows.items():
        manifest = resolved_manifests.get(plugin_id)
        if manifest is None:
            errors.append(f"plugin {plugin_id} has no manifest in the catalog")
            continue
        config_errors = _validate_config(manifest, row.config)
        errors.extend(config_errors)
        active_manifests[plugin_id] = manifest
        layer_by_plugin[plugin_id] = layer_id

    _validate_requirements(active_manifests, errors)
    if errors:
        raise ProfileCompositionError(errors)

    ordered_ids = _dependency_order(active_manifests)
    rows = tuple(
        PluginSnapshotRow(
            manifest=active_manifests[plugin_id],
            config=dict(effective_rows[plugin_id][0].config),
            layer_id=layer_by_plugin[plugin_id],
        )
        for plugin_id in ordered_ids
    )
    snapshot_payload = {
        "schema_version": 1,
        "profile_id": document.profile_id,
        "plugins": [row.to_payload() for row in rows],
    }
    digest = hashlib.sha256(
        json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ProfileSnapshot(
        profile_id=document.profile_id,
        schema_version=1,
        rows=rows,
        digest=digest,
    )


def control_envelope(
    snapshot: ProfileSnapshot,
    *,
    version: int,
    nonce: str | None = None,
    type_url: str = PROFILE_SNAPSHOT_TYPE_URL,
) -> ControlPlaneEnvelope:
    """Build a versioned envelope for snapshot distribution."""
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("version must be a positive integer")
    return ControlPlaneEnvelope(
        version=version,
        nonce=nonce or str(uuid.uuid4()),
        snapshot_digest=snapshot.digest,
        type_url=type_url,
    )


def _parse_layer(raw_layer: object, index: int) -> ProfileLayer:
    if isinstance(raw_layer, str):
        if not raw_layer.strip():
            raise ProfileCompositionError(f"profile.layers[{index}] id must be non-empty")
        return ProfileLayer(id=raw_layer, rows=())
    if not isinstance(raw_layer, dict):
        raise ProfileCompositionError(f"profile.layers[{index}] must be an object or string")

    layer_id = raw_layer.get("id")
    if not isinstance(layer_id, str) or not layer_id.strip():
        raise ProfileCompositionError(f"profile.layers[{index}].id must be non-empty")
    raw_rows = raw_layer.get("plugins", [])
    if not isinstance(raw_rows, list):
        raise ProfileCompositionError(f"layer {layer_id} plugins must be an array")
    rows = tuple(
        _parse_row(raw_row, layer_id, row_index) for row_index, raw_row in enumerate(raw_rows)
    )
    row_ids = [row.id for row in rows]
    if len(set(row_ids)) != len(row_ids):
        raise ProfileCompositionError(f"layer {layer_id} contains duplicate plugin ids")
    return ProfileLayer(id=layer_id, rows=rows)


def _parse_row(raw_row: object, layer_id: str, index: int) -> ProfileRow:
    if not isinstance(raw_row, dict):
        raise ProfileCompositionError(f"layer {layer_id} plugins[{index}] must be an object")
    row_id = raw_row.get("id")
    if not isinstance(row_id, str) or not row_id.strip():
        raise ProfileCompositionError(f"layer {layer_id} plugins[{index}].id must be non-empty")
    enabled = raw_row.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ProfileCompositionError(f"layer {layer_id} plugin {row_id} enabled must be boolean")
    config = raw_row.get("config", {})
    if not isinstance(config, dict):
        raise ProfileCompositionError(f"layer {layer_id} plugin {row_id} config must be an object")
    return ProfileRow(id=row_id, enabled=enabled, config=config)


def _parse_patch(raw_patch: object, index: int) -> ProfilePatch:
    if not isinstance(raw_patch, dict):
        raise ProfileCompositionError(f"patches[{index}] must be an object")
    target = raw_patch.get("target")
    if not isinstance(target, str) or not target.strip():
        raise ProfileCompositionError(f"patches[{index}].target must be non-empty")
    enabled = raw_patch.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise ProfileCompositionError(f"patches[{index}].enabled must be boolean")
    config = raw_patch.get("config")
    if config is not None and not isinstance(config, dict):
        raise ProfileCompositionError(f"patches[{index}].config must be an object")
    remove = raw_patch.get("remove", False)
    if not isinstance(remove, bool):
        raise ProfileCompositionError(f"patches[{index}].remove must be boolean")
    if enabled is None and config is None and not remove:
        raise ProfileCompositionError(f"patches[{index}] must set enabled, config, or remove")
    return ProfilePatch(target=target, enabled=enabled, config=config, remove=remove)


def _compose_rows(document: ProfileDocument) -> dict[str, tuple[ProfileRow, str]]:
    rows: dict[str, tuple[ProfileRow, str]] = {}
    for layer in document.layers:
        for row in layer.rows:
            rows[row.id] = row, layer.id

    for patch in document.patches:
        existing = rows.get(patch.target)
        if existing is None:
            raise ProfileCompositionError(f"patch target is absent: {patch.target}")
        row, layer_id = existing
        if patch.remove:
            del rows[patch.target]
            continue
        rows[patch.target] = (
            ProfileRow(
                id=row.id,
                enabled=patch.enabled if patch.enabled is not None else row.enabled,
                config=patch.config if patch.config is not None else row.config,
            ),
            layer_id,
        )

    return {plugin_id: item for plugin_id, item in rows.items() if item[0].enabled}


def _resolve_manifest(
    plugin_id: str, manifest: PluginManifest | dict[str, Any] | str
) -> PluginManifest:
    try:
        if isinstance(manifest, PluginManifest):
            parsed = manifest
        elif isinstance(manifest, str):
            from src.domain.model.plugins.manifest import parse_plugin_manifest_json

            parsed = parse_plugin_manifest_json(manifest)
        else:
            parsed = parse_plugin_manifest(manifest)
    except ValueError as exc:
        raise ProfileCompositionError([f"invalid manifest for {plugin_id}: {exc}"]) from exc
    if parsed.id != plugin_id:
        raise ProfileCompositionError(
            f"catalog key {plugin_id} does not match manifest id {parsed.id}"
        )
    return parsed


def _validate_config(manifest: PluginManifest, config: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for capability in manifest.provides:
        schema = capability.config_schema
        if not schema:
            continue
        validator = jsonschema.Draft7Validator(schema)
        for error in sorted(validator.iter_errors(dict(config)), key=lambda item: item.json_path):
            errors.append(
                f"plugin {manifest.id} config invalid for {capability.contract}: "
                f"{error.message} at {error.json_path}"
            )
    return errors


def _validate_requirements(
    active_manifests: Mapping[str, PluginManifest], errors: list[str]
) -> None:
    contract_owners: dict[str, tuple[str, PluginManifest]] = {}
    for plugin_id, manifest in active_manifests.items():
        for capability in manifest.provides:
            contract = _provided_contract(capability, plugin_id)
            existing = contract_owners.get(contract)
            if existing is not None:
                errors.append(
                    f"contract {contract} is provided by both {existing[0]} and {plugin_id}"
                )
            else:
                contract_owners[contract] = plugin_id, manifest

    for plugin_id, manifest in active_manifests.items():
        for requirement in manifest.requires:
            provider_id = _requirement_owner(
                requirement,
                {key: owner[0] for key, owner in contract_owners.items()},
            )
            if provider_id is None:
                base_matches = {
                    key
                    for key in contract_owners
                    if key.rsplit("@", 1)[0] == requirement.capability
                }
                if len(base_matches) > 1:
                    errors.append(
                        f"plugin {plugin_id} requires ambiguous capability "
                        f"{_required_contract(requirement, plugin_id)}; pin it with @plugin-id"
                    )
                else:
                    errors.append(
                        f"plugin {plugin_id} requires missing capability {_required_contract(requirement, plugin_id)}"
                    )
                continue
            owner = provider_id, active_manifests[provider_id]
            provider_id, provider_manifest = owner
            if provider_id == plugin_id:
                errors.append(
                    f"plugin {plugin_id} requires its own {_required_contract(requirement, plugin_id)}"
                )
                continue
            if requirement.min_version and _version_tuple(
                provider_manifest.version
            ) < _version_tuple(requirement.min_version):
                errors.append(
                    f"plugin {plugin_id} requires {_required_contract(requirement, plugin_id)} "
                    f">={requirement.min_version}, but {provider_id} is {provider_manifest.version}"
                )


def _dependency_order(active_manifests: Mapping[str, PluginManifest]) -> Sequence[str]:
    provider_by_contract = {
        _provided_contract(capability, plugin_id): plugin_id
        for plugin_id, manifest in active_manifests.items()
        for capability in manifest.provides
    }
    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(plugin_id: str) -> None:
        if plugin_id in visited:
            return
        if plugin_id in visiting:
            raise ProfileCompositionError(f"plugin dependency cycle includes {plugin_id}")
        visiting.add(plugin_id)
        manifest = active_manifests[plugin_id]
        for requirement in manifest.requires:
            provider_id = _requirement_owner(requirement, provider_by_contract)
            if provider_id is not None and provider_id != plugin_id:
                visit(provider_id)
        visiting.remove(plugin_id)
        visited.add(plugin_id)
        ordered.append(plugin_id)

    for plugin_id in sorted(active_manifests):
        visit(plugin_id)
    return ordered


def _version_tuple(version: str) -> tuple[int, int, int, str]:
    base, _, suffix = version.partition("-")
    major, minor, patch = (int(item) for item in base.split("."))
    return major, minor, patch, suffix


def _provided_contract(capability: ProvidedCapability, plugin_id: str) -> str:
    contract = capability.contract
    return f"{contract}@{plugin_id}"


def _required_contract(requirement: PluginRequirement, plugin_id: str) -> str:
    contract = requirement.capability
    return f"{contract}@{plugin_id}"


def _requirement_owner(
    requirement: PluginRequirement,
    provider_by_contract: Mapping[str, str],
) -> str | None:
    """Resolve a requirement to its provider: exact ``@plugin`` pin, else a
    unique base-contract match; ambiguous or absent matches return None."""
    pinned = provider_by_contract.get(requirement.capability)
    if pinned is not None:
        return pinned
    matches = {
        owner
        for key, owner in provider_by_contract.items()
        if key.rsplit("@", 1)[0] == requirement.capability
    }
    if len(matches) == 1:
        return matches.pop()
    return None
