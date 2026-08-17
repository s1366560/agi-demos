"""Application service for the platform plugin control plane."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from src.domain.model.plugins import PluginManifest, parse_plugin_manifest
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)
from src.infrastructure.plugins.builtin_manifests import default_builtin_manifests
from src.infrastructure.plugins.profile import (
    ControlPlaneEnvelope,
    ProfileDocument,
    ProfileLayer,
    ProfileRow,
    ProfileSnapshot,
    compose_profile,
    control_envelope,
    load_profile_document,
)

ManifestProvider = Callable[[], Mapping[str, PluginManifest]]
DEFAULT_PROFILE_PATH = (
    Path(__file__).resolve().parents[3] / "config/plugin-profiles/memstack-default.yaml"
)


@dataclass(frozen=True)
class PlatformPluginPublication:
    """A persisted snapshot and the envelope that distributes it."""

    snapshot: ProfileSnapshot
    envelope: ControlPlaneEnvelope


class PlatformPluginProfileService:
    """Compose, persist, audit, and distribute effective plugin profiles."""

    def __init__(
        self,
        repository: PlatformPluginRepository,
        *,
        profile_path: str | Path = DEFAULT_PROFILE_PATH,
        manifest_provider: ManifestProvider = default_builtin_manifests,
    ) -> None:
        self._repository = repository
        self._profile_path = Path(profile_path)
        self._manifest_provider = manifest_provider

    async def publish(
        self,
        *,
        version: int,
        nonce: str | None = None,
        actor_id: str | None = None,
    ) -> PlatformPluginPublication:
        """Persist manifests, effective snapshot, audit rows, and envelope."""
        manifests = dict(self._manifest_provider())
        for catalog_row in await self._repository.list_catalog():
            manifests[catalog_row.plugin_id] = parse_plugin_manifest(catalog_row.manifest)
        for manifest in sorted(manifests.values(), key=lambda item: item.id):
            await self._repository.upsert_catalog_manifest(manifest)

        document = await self._effective_document()
        snapshot = compose_profile(document, manifests)
        envelope = control_envelope(snapshot, version=version, nonce=nonce)
        await self._repository.record_snapshot(
            snapshot,
            version=version,
            nonce=envelope.nonce,
        )
        for row in snapshot.rows:
            for capability in row.manifest.provides:
                await self._repository.record_capability_transition(
                    snapshot_digest=snapshot.digest,
                    plugin_id=row.manifest.id,
                    action="provide",
                    capability_kind=capability.kind.value,
                    capability_id=capability.id,
                    actor_id=actor_id,
                    before_state={},
                    after_state={"owner": row.manifest.id, "layer": row.layer_id},
                )

        return PlatformPluginPublication(
            snapshot=snapshot,
            envelope=envelope,
        )

    async def record_ack(
        self,
        publication: PlatformPluginPublication,
        *,
        data_plane_id: str,
        applied_version: int,
    ) -> None:
        """Record a successful data-plane apply."""
        await self._repository.record_apply_state(
            data_plane_id=data_plane_id,
            snapshot_digest=publication.snapshot.digest,
            requested_version=publication.envelope.version,
            applied_version=applied_version,
            status="ack",
        )

    async def _effective_document(self) -> ProfileDocument:
        """Merge the static base profile with installed marketplace desired rows."""
        document = load_profile_document(self._profile_path)
        packages = {
            package.plugin_id: package
            for package in await self._repository.list_installed_packages()
        }
        existing_ids = {row.id for layer in document.layers for row in layer.rows}
        rows = []
        for desired in await self._repository.list_desired_states():
            package = packages.get(desired.plugin_id)
            if not desired.enabled or package is None or desired.plugin_id in existing_ids:
                continue
            rows.append(
                ProfileRow(
                    id=desired.plugin_id,
                    enabled=True,
                    config={
                        **dict(desired.config),
                        "artifact": {
                            "registry": package.artifact_registry,
                            "repository": package.artifact_repository,
                            "manifest_sha256": package.oci_manifest_digest,
                            "layer_sha256": package.artifact_digest,
                        },
                    },
                )
            )
        if not rows:
            return document
        return replace(
            document,
            layers=(*document.layers, ProfileLayer(id="marketplace-installed", rows=tuple(rows))),
        )

    async def record_nack(
        self,
        publication: PlatformPluginPublication,
        *,
        data_plane_id: str,
        applied_version: int,
        error_message: str,
    ) -> None:
        """Record rejection while retaining the last-good applied version."""
        if not error_message.strip():
            raise ValueError("error_message is required for NACK")
        await self._repository.record_apply_state(
            data_plane_id=data_plane_id,
            snapshot_digest=publication.snapshot.digest,
            requested_version=publication.envelope.version,
            applied_version=applied_version,
            status="nack",
            error_message=error_message,
        )
