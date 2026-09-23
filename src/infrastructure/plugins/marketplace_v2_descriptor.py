"""Public catalog projection; installation still uses the signed V2 authority path."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.persistence.models import PlatformPluginPackageModel


def describe_v2_package(package: PlatformPluginPackageModel) -> dict[str, Any]:
    """Expose only public metadata, without conferring signature trust or install authority."""
    manifests = package.manifest.get("manifests", [])
    permissions = sorted(
        {
            permission
            for manifest in manifests
            if isinstance(manifest, dict)
            for permission in manifest.get("permissions", [])
            if isinstance(permission, str) and permission
        }
    )
    # V2 has no category/capability display metadata. Do not infer it from names,
    # service identifiers or permission strings.
    return {
        "id": package.plugin_id,
        "name": package.plugin_id,
        "description": "",
        "version": package.version,
        "publisher": package.publisher,
        "source_id": "signed-v2",
        "format": "v2",
        "install_strategy": "signed-v2",
        "category": "",
        "capabilities": [],
        "targets": ["cloud"],
        "permissions": permissions,
        "compatible": not package.revoked,
        "reasons": ["signed_package_revoked"] if package.revoked else [],
        "digest": package.artifact_digest,
        "readme": "",
        "changelog": "",
    }
