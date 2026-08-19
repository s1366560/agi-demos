"""MemStack plugin bundle (`.mspkg`) format: profile layer distribution.

Phase P4 of the full-pluginization roadmap. A bundle packages one named
profile layer — plugin manifests plus the layer's activation rows and
patches — so installing it appends a composable layer to a profile without
hand-editing YAML. Bundles are plain zip archives with a `bundle.json`
descriptor, parsed with the same size/count limits as plugin archives.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.domain.model.plugins import PluginManifest, parse_plugin_manifest

from .profile import ProfileLayer, ProfilePatch, ProfileRow, _parse_patch

BUNDLE_DESCRIPTOR = "bundle.json"
BUNDLE_SCHEMA_VERSION = 1
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_BUNDLE_FILES = 512
MAX_BUNDLE_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_DESCRIPTOR_BYTES = 2 * 1024 * 1024

__all__ = [
    "BUNDLE_DESCRIPTOR",
    "BundleError",
    "PluginBundle",
    "bundle_to_profile_layer",
    "read_bundle",
    "write_bundle",
]


class BundleError(ValueError):
    """Raised when a bundle archive or descriptor is invalid."""


@dataclass(frozen=True)
class PluginBundle:
    """One parsed bundle: a named profile layer plus its plugin manifests."""

    bundle_id: str
    version: str
    layer: ProfileLayer
    manifests: tuple[PluginManifest, ...]
    patches: tuple[ProfilePatch, ...] = ()
    description: str = ""

    def to_descriptor(self) -> dict[str, Any]:
        """Return the bundle.json representation."""
        return {
            "schemaVersion": BUNDLE_SCHEMA_VERSION,
            "id": self.bundle_id,
            "version": self.version,
            "description": self.description,
            "layer": {
                "id": self.layer.id,
                "plugins": [
                    {
                        "id": row.id,
                        **({} if row.enabled else {"enabled": row.enabled}),
                        **({"config": dict(row.config)} if row.config else {}),
                    }
                    for row in self.layer.rows
                ],
            },
            "patches": [
                {
                    "target": patch.target,
                    **({"enabled": patch.enabled} if patch.enabled is not None else {}),
                    **({"config": dict(patch.config)} if patch.config is not None else {}),
                    **({"remove": patch.remove} if patch.remove else {}),
                }
                for patch in self.patches
            ],
            "manifests": [manifest.to_payload() for manifest in self.manifests],
        }


def read_bundle(path: Path) -> PluginBundle:
    """Parse and validate a `.mspkg` archive, failing loud on any defect."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise BundleError(f"cannot read bundle {path}: {exc}") from exc
    if len(raw) > MAX_BUNDLE_BYTES:
        raise BundleError(f"bundle {path} exceeds the {MAX_BUNDLE_BYTES} byte limit")
    files = _read_zip(raw, path)
    descriptor_bytes = files.get(BUNDLE_DESCRIPTOR)
    if descriptor_bytes is None:
        raise BundleError(f"bundle {path} is missing {BUNDLE_DESCRIPTOR}")
    try:
        descriptor = json.loads(descriptor_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError(f"bundle {path} has an invalid {BUNDLE_DESCRIPTOR}: {exc}") from exc
    return _parse_descriptor(descriptor, path)


def write_bundle(path: Path, bundle: PluginBundle) -> None:
    """Write a bundle archive containing exactly the descriptor document."""
    descriptor = json.dumps(bundle.to_descriptor(), indent=2, sort_keys=True).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(BUNDLE_DESCRIPTOR, descriptor)


def bundle_to_profile_layer(bundle: PluginBundle) -> ProfileLayer:
    """Return the profile layer a marketplace install would append."""
    return bundle.layer


def _read_zip(raw: bytes, path: Path) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise BundleError(f"bundle {path} is not a valid zip archive") from exc
    names = archive.namelist()
    if len(names) > MAX_BUNDLE_FILES:
        raise BundleError(f"bundle {path} exceeds the {MAX_BUNDLE_FILES} file limit")
    files: dict[str, bytes] = {}
    total = 0
    for name in names:
        if name.endswith("/"):
            continue
        if name.startswith("/") or ".." in Path(name).parts:
            raise BundleError(f"bundle {path} has an unsafe entry name: {name}")
        data = archive.read(name)
        total += len(data)
        if total > MAX_BUNDLE_UNCOMPRESSED_BYTES:
            raise BundleError(f"bundle {path} exceeds the uncompressed size limit")
        if name == BUNDLE_DESCRIPTOR and len(data) > MAX_DESCRIPTOR_BYTES:
            raise BundleError(f"bundle {path} descriptor exceeds the size limit")
        files[name] = data
    return files


def _parse_descriptor(descriptor: object, path: Path) -> PluginBundle:
    if not isinstance(descriptor, dict):
        raise BundleError(f"bundle {path} descriptor must be an object")
    if descriptor.get("schemaVersion") != BUNDLE_SCHEMA_VERSION:
        raise BundleError(f"bundle {path} schemaVersion must be {BUNDLE_SCHEMA_VERSION}")
    bundle_id = _required_str(descriptor, "id", path)
    version = _required_str(descriptor, "version", path)
    description = descriptor.get("description") or ""
    if not isinstance(description, str):
        raise BundleError(f"bundle {path} description must be a string")

    layer_payload = descriptor.get("layer")
    if not isinstance(layer_payload, dict):
        raise BundleError(f"bundle {path} layer must be an object")
    layer_id = _required_str(layer_payload, "id", path)
    rows_payload = layer_payload.get("plugins")
    if not isinstance(rows_payload, list):
        raise BundleError(f"bundle {path} layer.plugins must be an array")
    rows = tuple(_parse_row(item, path, index) for index, item in enumerate(rows_payload))

    patches_payload = descriptor.get("patches", [])
    if not isinstance(patches_payload, list):
        raise BundleError(f"bundle {path} patches must be an array")
    try:
        patches = tuple(_parse_patch(item, index) for index, item in enumerate(patches_payload))
    except Exception as exc:
        raise BundleError(f"bundle {path} has an invalid patch: {exc}") from exc

    manifests_payload = descriptor.get("manifests")
    if not isinstance(manifests_payload, list) or not manifests_payload:
        raise BundleError(f"bundle {path} manifests must be a non-empty array")
    manifests: list[PluginManifest] = []
    for index, item in enumerate(manifests_payload):
        try:
            manifests.append(parse_plugin_manifest(item))
        except Exception as exc:
            raise BundleError(f"bundle {path} manifests[{index}] is invalid: {exc}") from exc

    _validate_cross_references(path, rows, patches, manifests)
    return PluginBundle(
        bundle_id=bundle_id,
        version=version,
        layer=ProfileLayer(id=layer_id, rows=rows),
        manifests=tuple(manifests),
        patches=patches,
        description=description,
    )


def _validate_cross_references(
    path: Path,
    rows: tuple[ProfileRow, ...],
    patches: tuple[ProfilePatch, ...],
    manifests: list[PluginManifest],
) -> None:
    manifest_ids = {manifest.id for manifest in manifests}
    if len(manifest_ids) != len(manifests):
        raise BundleError(f"bundle {path} contains duplicate manifest ids")
    row_ids = [row.id for row in rows]
    if len(set(row_ids)) != len(row_ids):
        raise BundleError(f"bundle {path} layer contains duplicate plugin ids")
    for row in rows:
        if row.id not in manifest_ids:
            raise BundleError(f"bundle {path} row {row.id} has no manifest in the bundle")
    for patch in patches:
        if patch.target not in manifest_ids:
            raise BundleError(
                f"bundle {path} patch target {patch.target} has no manifest in the bundle"
            )


def _parse_row(item: object, path: Path, index: int) -> ProfileRow:
    if not isinstance(item, dict):
        raise BundleError(f"bundle {path} layer.plugins[{index}] must be an object")
    row_id = item.get("id")
    if not isinstance(row_id, str) or not row_id.strip():
        raise BundleError(f"bundle {path} layer.plugins[{index}].id must be non-empty")
    enabled = item.get("enabled", True)
    if not isinstance(enabled, bool):
        raise BundleError(f"bundle {path} row {row_id} enabled must be boolean")
    config = item.get("config", {})
    if not isinstance(config, dict):
        raise BundleError(f"bundle {path} row {row_id} config must be an object")
    return ProfileRow(id=row_id, enabled=enabled, config=config)


def _required_str(payload: dict[str, Any], key: str, path: Path) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BundleError(f"bundle {path} {key} must be a non-empty string")
    return value
