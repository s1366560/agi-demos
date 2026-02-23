"""Manifest parsing helpers for local runtime plugins."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .registry import PluginDiagnostic

LOCAL_PLUGIN_MANIFEST_FILE = "memstack.plugin.json"


@dataclass(frozen=True)
class PluginManifestMetadata:
    """Normalized manifest metadata for one plugin."""

    id: str
    manifest_path: Optional[str] = None
    kind: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    channels: tuple[str, ...] = field(default_factory=tuple)
    providers: tuple[str, ...] = field(default_factory=tuple)
    skills: tuple[str, ...] = field(default_factory=tuple)


def load_local_plugin_manifest(
    plugin_dir: Path,
    *,
    plugin_name: str,
) -> tuple[Optional[PluginManifestMetadata], list[PluginDiagnostic]]:
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
    manifest_path: Optional[str] = None,
    source: str = "manifest",
) -> tuple[Optional[PluginManifestMetadata], list[PluginDiagnostic]]:
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
    )
    return metadata, diagnostics


def _read_json_manifest(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _normalize_str(value: Any) -> Optional[str]:
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
