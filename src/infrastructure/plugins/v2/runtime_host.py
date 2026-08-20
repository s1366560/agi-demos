"""Production-facing async host for the Python protocol v2 data plane."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from src.domain.model.plugins.generated_v2 import (
    ApplyStatusV2,
    ControlPlaneEnvelopeV2,
    PluginManifestV2,
    ProfileSnapshotV2,
    SnapshotApplyReceiptV2,
)

from .composer import compose_profile_v2, load_profile_document_v2
from .protocol import control_envelope_v2, parse_plugin_manifest_v2
from .reconciler import PlatformPluginSnapshotReconcilerV2
from .runtime import (
    GenerationLeaseV2,
    GenerationManagerV2,
    LoaderV2,
    PluginDefinitionV2,
)


@dataclass(frozen=True, kw_only=True)
class PlatformPluginPublicationV2:
    """One composed snapshot, distribution envelope, and local apply receipt."""

    snapshot: ProfileSnapshotV2
    envelope: ControlPlaneEnvelopeV2
    receipt: SnapshotApplyReceiptV2

    @property
    def accepted(self) -> bool:
        return self.receipt.status is ApplyStatusV2.ACK


class PlatformPluginRuntimeHostV2:
    """Own one Python Loader/Reconciler/GenerationManager v2 graph."""

    def __init__(self, definitions: Sequence[PluginDefinitionV2] = ()) -> None:
        self.loader = LoaderV2(definitions)
        self.reconciler = PlatformPluginSnapshotReconcilerV2(self.loader)

    @property
    def manager(self) -> GenerationManagerV2:
        return self.reconciler.manager

    async def apply(
        self,
        snapshot: ProfileSnapshotV2,
        envelope: ControlPlaneEnvelopeV2,
    ) -> PlatformPluginPublicationV2:
        """Stage and atomically publish one snapshot, retaining last-good on NACK."""
        receipt = await self.reconciler.apply(snapshot, envelope)
        return PlatformPluginPublicationV2(
            snapshot=snapshot,
            envelope=envelope,
            receipt=receipt,
        )

    async def bootstrap(
        self,
        *,
        profile_path: str | Path,
        manifest_paths: Sequence[str | Path],
        generation: int,
        version: int,
        nonce: str | None = None,
    ) -> PlatformPluginPublicationV2:
        """Load strict v2 files and publish the initial production generation."""
        manifests = _load_manifests(manifest_paths)
        snapshot = compose_profile_v2(
            load_profile_document_v2(profile_path),
            manifests,
            generation=generation,
        )
        return await self.apply(
            snapshot,
            control_envelope_v2(snapshot, version=version, nonce=nonce),
        )

    async def acquire(self) -> GenerationLeaseV2:
        """Acquire the complete generation used by one data-plane boundary."""
        return await self.manager.acquire()

    async def close(self) -> None:
        """Retire the active generation and dispose it after leases drain."""
        await self.reconciler.close()


def _load_manifests(paths: Sequence[str | Path]) -> dict[str, PluginManifestV2]:
    manifests: dict[str, PluginManifestV2] = {}
    for path_value in paths:
        path = Path(path_value)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"failed to load v2 manifest {path}: {exc}") from exc
        manifest = parse_plugin_manifest_v2(payload)
        if manifest.plugin_id in manifests:
            raise ValueError(f"duplicate v2 manifest {manifest.plugin_id}")
        manifests[manifest.plugin_id] = manifest
    return manifests
