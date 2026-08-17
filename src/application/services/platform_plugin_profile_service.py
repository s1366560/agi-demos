"""Application service for the platform plugin control plane."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from src.domain.model.plugins import PluginManifest
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)
from src.infrastructure.plugins.builtin_manifests import default_builtin_manifests
from src.infrastructure.plugins.profile import (
    ControlPlaneEnvelope,
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
        manifests = self._manifest_provider()
        for manifest in sorted(manifests.values(), key=lambda item: item.id):
            await self._repository.upsert_catalog_manifest(manifest)

        snapshot = compose_profile(load_profile_document(self._profile_path), manifests)
        await self._repository.record_snapshot(snapshot, version=version)
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
            envelope=control_envelope(snapshot, version=version, nonce=nonce),
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
