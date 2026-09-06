"""Production-facing async host for the Python protocol v2 data plane."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from weakref import WeakKeyDictionary

from src.domain.model.plugins.generated_v2 import (
    ApplyStatusV2,
    ControlPlaneEnvelopeV2,
    PluginManifestV2,
    ProfileSnapshotV2,
    ScopeV2,
    SnapshotApplyReceiptV2,
)
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2

from .bundle_archive import VerifiedBundleArchiveV2
from .composer import ProfileDocumentV2, compose_profile_v2, load_profile_document_v2
from .protocol import (
    control_envelope_v2,
    control_envelope_v2_to_payload,
    parse_control_envelope_v2,
    parse_plugin_manifest_v2,
    parse_profile_snapshot_v2,
    profile_snapshot_v2_to_payload,
)
from .reconciler import GenerationPublicationStagerV2, PlatformPluginSnapshotReconcilerV2
from .runtime import (
    GenerationLeaseV2,
    GenerationManagerV2,
    LoaderV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeGenerationV2,
    RuntimeV2Error,
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


@dataclass(frozen=True, kw_only=True)
class PlatformPluginDistributionV2:
    """Process-safe snapshot distribution payload derived from one accepted publication."""

    descriptor: PluginGenerationDescriptorV2
    snapshot: ProfileSnapshotV2
    envelope: ControlPlaneEnvelopeV2

    def to_payload(self) -> dict[str, Any]:
        return {
            "descriptor": self.descriptor.to_payload(),
            "snapshot": profile_snapshot_v2_to_payload(self.snapshot),
            "envelope": control_envelope_v2_to_payload(self.envelope),
        }


class PlatformPluginRuntimeHostV2:
    """Own one Python Loader/Reconciler/GenerationManager v2 graph."""

    def __init__(
        self,
        definitions: Sequence[PluginDefinitionV2] = (),
        *,
        loader: LoaderV2 | None = None,
    ) -> None:
        if loader is not None and definitions:
            raise ValueError("definitions and an explicit v2 loader are mutually exclusive")
        self.loader = loader or LoaderV2(definitions)
        self.reconciler = PlatformPluginSnapshotReconcilerV2(self.loader)
        self._apply_lock = asyncio.Lock()
        self._current_publication: PlatformPluginPublicationV2 | None = None
        self._distributions: WeakKeyDictionary[
            RuntimeGenerationV2, PlatformPluginDistributionV2
        ] = WeakKeyDictionary()

    @property
    def manager(self) -> GenerationManagerV2:
        return self.reconciler.manager

    @property
    def current_distribution(self) -> PlatformPluginDistributionV2 | None:
        current = self.manager.current
        if current is None:
            return None
        return self._distributions.get(current)

    @property
    def current_publication(self) -> PlatformPluginPublicationV2 | None:
        """Return the accepted publication paired with the active generation."""
        return self._current_publication

    def distribution_for_generation(
        self,
        generation: RuntimeGenerationV2,
    ) -> PlatformPluginDistributionV2:
        """Return the immutable distribution paired with one exact leased generation."""
        distribution = self._distributions.get(generation)
        if distribution is None or distribution.descriptor != generation.descriptor:
            raise RuntimeV2Error(
                "generation_distribution_unavailable",
                "plugin distribution is unavailable for the leased generation",
            )
        return distribution

    async def apply(
        self,
        snapshot: ProfileSnapshotV2,
        envelope: ControlPlaneEnvelopeV2,
        *,
        publication_stager: GenerationPublicationStagerV2 | None = None,
        verified_archives: Sequence[VerifiedBundleArchiveV2] | None = None,
    ) -> PlatformPluginPublicationV2:
        """Stage and atomically publish one snapshot, retaining last-good on NACK."""
        archives = None if verified_archives is None else tuple(verified_archives)
        async with self._apply_lock:
            receipt = await self.reconciler.apply(
                snapshot,
                envelope,
                publication_stager=publication_stager,
                verified_archives=archives,
            )
            publication = PlatformPluginPublicationV2(
                snapshot=snapshot,
                envelope=envelope,
                receipt=receipt,
            )
            if publication.accepted:
                self._current_publication = publication
                current = self.manager.current
                if current is None:
                    raise RuntimeV2Error(
                        "generation_publication_missing",
                        "accepted plugin snapshot did not publish a runtime generation",
                    )
                self._distributions[current] = PlatformPluginDistributionV2(
                    descriptor=current.descriptor,
                    snapshot=publication.snapshot,
                    envelope=publication.envelope,
                )
            return publication

    async def apply_distribution(
        self,
        payload: Mapping[str, object],
        *,
        publication_stager: GenerationPublicationStagerV2 | None = None,
        verified_archives: Sequence[VerifiedBundleArchiveV2] | None = None,
    ) -> PlatformPluginPublicationV2:
        """Validate a complete process-safe distribution before staging it locally."""
        if set(payload) != {"descriptor", "snapshot", "envelope"}:
            raise ValueError("plugin distribution has invalid fields")
        descriptor_payload = payload["descriptor"]
        if not isinstance(descriptor_payload, dict):
            raise ValueError("plugin distribution descriptor must be an object")
        descriptor = PluginGenerationDescriptorV2.from_payload(
            cast(dict[str, Any], descriptor_payload)
        )
        snapshot = parse_profile_snapshot_v2(payload["snapshot"])
        envelope = parse_control_envelope_v2(payload["envelope"])
        expected = PluginGenerationDescriptorV2(
            profile_id=snapshot.profile_id,
            generation=snapshot.generation,
            digest=snapshot.digest,
        )
        if descriptor != expected:
            raise ValueError("plugin distribution descriptor does not match snapshot")
        return await self.apply(
            snapshot,
            envelope,
            publication_stager=publication_stager,
            verified_archives=verified_archives,
        )

    async def bootstrap(
        self,
        *,
        profile_path: str | Path,
        manifest_paths: Sequence[str | Path],
        generation: int,
        version: int,
        nonce: str | None = None,
        profile_projector: Callable[[ProfileDocumentV2], ProfileDocumentV2] | None = None,
        publication_stager: GenerationPublicationStagerV2 | None = None,
    ) -> PlatformPluginPublicationV2:
        """Load strict v2 files and publish the initial production generation."""
        manifests = _load_manifests(manifest_paths)
        document = load_profile_document_v2(profile_path)
        if profile_projector is not None:
            document = profile_projector(document)
        snapshot = compose_profile_v2(
            document,
            manifests,
            generation=generation,
        )
        return await self.apply(
            snapshot,
            control_envelope_v2(snapshot, version=version, nonce=nonce),
            publication_stager=publication_stager,
        )

    async def acquire(self) -> GenerationLeaseV2:
        """Acquire the complete generation used by one data-plane boundary."""
        async with self._apply_lock:
            return await self.manager.acquire()

    async def acquire_exact(
        self,
        generation: RuntimeGenerationV2,
        descriptor: PluginGenerationDescriptorV2,
    ) -> GenerationLeaseV2:
        """Retain one exact host-owned generation before its parent lease exits."""
        async with self._apply_lock:
            distribution = self.distribution_for_generation(generation)
            if generation.descriptor != descriptor or distribution.descriptor != descriptor:
                raise RuntimeV2Error(
                    "generation_descriptor_mismatch",
                    "exact generation reservation does not match its descriptor",
                )
            return await self.manager.retain(generation)

    async def close(self) -> None:
        """Retire the active generation and dispose it after leases drain."""
        async with self._apply_lock:
            try:
                await self.reconciler.close()
            finally:
                self._current_publication = None


class DataPlaneGenerationAdmissionV2:
    """Atomically validate a distribution and lease its exact local generation."""

    def __init__(self, definitions: Sequence[PluginDefinitionV2] = ()) -> None:
        self.host = PlatformPluginRuntimeHostV2(definitions)
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def admit(
        self,
        *,
        descriptor_payload: Mapping[str, object] | None,
        distribution_payload: Mapping[str, object] | None,
        operation_id: str,
        scope: ScopeV2,
        services: Mapping[str, object] | None = None,
    ) -> AsyncIterator[OperationContextV2]:
        if descriptor_payload is None:
            raise RuntimeV2Error(
                "generation_descriptor_missing",
                "plugin generation descriptor is required for operation admission",
            )
        descriptor = PluginGenerationDescriptorV2.from_payload(
            cast(dict[str, Any], descriptor_payload)
        )

        async with self._lock:
            if distribution_payload is not None:
                if distribution_payload.get("descriptor") != descriptor_payload:
                    raise RuntimeV2Error(
                        "generation_descriptor_mismatch",
                        "plugin distribution does not match the requested generation",
                    )
                publication = await self.host.apply_distribution(distribution_payload)
                if not publication.accepted:
                    raise RuntimeV2Error(
                        publication.receipt.error_code or "generation_apply_failed",
                        publication.receipt.error_message or "plugin generation apply failed",
                    )

            current = self.host.manager.current
            if current is None:
                raise RuntimeV2Error(
                    "generation_payload_required",
                    "plugin generation is unavailable without a complete distribution",
                )
            if descriptor != current.descriptor:
                raise RuntimeV2Error(
                    "generation_unavailable",
                    "requested plugin generation is no longer active on this data plane",
                )

            from .boundary import pin_operation_context_v2

            context_manager = pin_operation_context_v2(
                self.host,
                operation_id=operation_id,
                scope=scope,
                services=services,
            )
            operation = await context_manager.__aenter__()
            if operation.descriptor != descriptor:
                await context_manager.__aexit__(None, None, None)
                raise RuntimeV2Error(
                    "generation_admission_race",
                    "plugin generation changed before the operation lease was acquired",
                )

        try:
            yield operation
        finally:
            await context_manager.__aexit__(None, None, None)

    async def close(self) -> None:
        await self.host.close()


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
