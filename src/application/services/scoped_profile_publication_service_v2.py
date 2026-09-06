"""Compose exact stored sources and verified bundles into a private scope publication."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.plugins.generated_v2 import (
    BundleManifestV2,
    BundleReferenceV2,
    ScopeV2,
    ServiceRequiredV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.plugins.v2.bundle_archive import VerifiedBundleArchiveV2
from src.infrastructure.plugins.v2.composer import compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import compose_profile_sources_v2
from src.infrastructure.plugins.v2.protocol import (
    bundle_manifest_v2_to_payload,
    parse_bundle_manifest_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginPublicationV2
from src.infrastructure.plugins.v2.scope import validate_scope_v2
from src.infrastructure.plugins.v2.scoped_publication_coordinator import (
    ScopedPublicationCoordinatorV2,
)
from src.infrastructure.plugins.v2.service_closure import project_service_closure_v2


@dataclass(frozen=True, kw_only=True)
class ScopedProfilePublicationResultV2:
    desired_revision: int
    publication: PlatformPluginPublicationV2


class ScopedProfilePublicationServiceV2:
    """Internal authorized caller only; stored provenance is not a trust decision.

    The injected loader owns archive signature/permission policy and artifact resolution.
    This service never fetches a URL or installs artifacts into a global runtime.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        coordinator: ScopedPublicationCoordinatorV2,
        load_verified_bundle: Callable[[BundleReferenceV2], Awaitable[VerifiedBundleArchiveV2]],
        required_services: Sequence[ServiceRequiredV2],
    ) -> None:
        super().__init__()
        self._sessions = session_factory
        self._coordinator = coordinator
        self._load_bundle = load_verified_bundle
        self._requirements = tuple(required_services)

    async def publish_current(self, scope: ScopeV2) -> ScopedProfilePublicationResultV2:
        canonical = validate_scope_v2(scope)
        async with self._sessions() as session:
            record = await PlatformPluginDesiredBundleSetRepositoryV2(session).current_desired_set(
                canonical
            )
            if record is None:
                raise RuntimeV2Error(
                    "scope_desired_missing", "scope desired configuration is missing"
                )
            desired = record.desired_set
            reference = desired.profile_source
            source = await PlatformPluginProfileSourceRepositoryV2(session).read_exact(
                scope=canonical,
                source_id=reference.source_id,
                revision=reference.revision,
                digest=reference.digest,
            )
            if source is None:
                raise RuntimeV2Error(
                    "scope_profile_source_missing", "exact profile source is missing"
                )
        bundles: list[BundleManifestV2] = []
        for reference in desired.bundles:
            archive = cast(object, await self._load_bundle(reference))
            if not isinstance(archive, VerifiedBundleArchiveV2):
                raise RuntimeV2Error(
                    "scope_bundle_unverified", "bundle loader must return a verified archive"
                )
            manifest = parse_bundle_manifest_v2(bundle_manifest_v2_to_payload(archive.manifest))
            if (manifest.bundle_id, manifest.version, manifest.digest) != (
                reference.bundle_id,
                reference.version,
                reference.digest,
            ):
                raise RuntimeV2Error(
                    "scope_bundle_reference_mismatch",
                    "verified bundle differs from exact reference",
                )
            bundles.append(manifest)
        composition = compose_profile_sources_v2(
            desired_set=desired, bundles=bundles, profile_source=source, scope=canonical
        )
        snapshot = compose_profile_v2(
            composition.document,
            {manifest.plugin_id: manifest for manifest in composition.manifests},
            generation=desired.revision,
        )
        projected = project_service_closure_v2(
            snapshot, scope=canonical, required_services=self._requirements
        )
        publication = await self._coordinator.publish(
            canonical, projected, expected_desired=desired
        )
        return ScopedProfilePublicationResultV2(
            desired_revision=desired.revision, publication=publication
        )
