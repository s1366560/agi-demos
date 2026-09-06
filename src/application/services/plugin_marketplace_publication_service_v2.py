"""Recompose and publish the root protocol-v2 generation after marketplace mutation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.domain.model.plugins.generated_v2 import (
    BundleManifestV2,
    BundleReferenceV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.primary.web.startup.http_route_publication_v2 import (
    HttpRoutePublicationCoordinatorV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.builtin_http_routes import BuiltinRouteGraphV2
from src.infrastructure.plugins.v2.composer import compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import compose_profile_sources_v2
from src.infrastructure.plugins.v2.production_bundle import (
    ProductionBundleSourcesV2,
)
from src.infrastructure.plugins.v2.protocol import (
    control_envelope_v2,
    parse_control_envelope_v2,
    parse_profile_snapshot_v2,
)
from src.infrastructure.plugins.v2.runtime_host import (
    PlatformPluginPublicationV2,
    PlatformPluginRuntimeHostV2,
)

from .installed_verified_bundle_loader_v2 import (
    InstalledVerifiedBundleLoaderV2,
    MarketplacePublicationV2Error as MarketplacePublicationV2Error,
)
from .plugin_marketplace_install_service import MarketplaceArtifactClient


@dataclass(frozen=True, kw_only=True)
class MarketplacePublicationResultV2:
    """One desired revision and its exact local ACK/NACK publication."""

    desired_revision: int
    publication: PlatformPluginPublicationV2


class PluginMarketplacePublicationServiceV2:
    """Resolve exact Bundle bytes, compose one candidate, and publish through v2 only."""

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        *,
        desired_repository: PlatformPluginDesiredBundleSetRepositoryV2,
        source_repository: PlatformPluginProfileSourceRepositoryV2,
        governance_repository: PlatformPluginGovernanceRepository,
        publication_repository: PlatformPluginRepositoryV2,
        artifact_client: MarketplaceArtifactClient,
        production_sources: ProductionBundleSourcesV2,
        trusted_public_keys: tuple[str, ...],
        host: PlatformPluginRuntimeHostV2,
        route_coordinator: HttpRoutePublicationCoordinatorV2,
        publication_policy: PlatformPluginPublicationPolicyV2,
        on_route_commit: Callable[[BuiltinRouteGraphV2], None] | None = None,
        allowed_registries: frozenset[str] | None = None,
    ) -> None:
        self._desired_repository = desired_repository
        self._source_repository = source_repository
        self._publication_repository = publication_repository
        self._production_sources = production_sources
        self._bundle_loader = InstalledVerifiedBundleLoaderV2(
            governance_repository=governance_repository,
            artifact_client=artifact_client,
            production_sources=production_sources,
            trusted_public_keys=trusted_public_keys,
            allowed_registries=allowed_registries,
        )
        self._host = host
        self._route_coordinator = route_coordinator
        self._publication_policy = publication_policy
        self._on_route_commit = on_route_commit

    async def publish_current(self) -> MarketplacePublicationResultV2:
        """Publish the current root DesiredBundleSet and durably record its local receipt."""
        scope = ScopeV2(kind=ScopeKindV2.ROOT)
        desired_record = await self._desired_repository.current_desired_set(scope)
        if desired_record is None:
            raise MarketplacePublicationV2Error(
                "desired_bundle_set_missing",
                "protocol v2 marketplace desired Bundle set is not initialized",
            )
        reference = desired_record.desired_set.profile_source
        source = await self._source_repository.read_exact(
            scope=scope,
            source_id=reference.source_id,
            revision=reference.revision,
            digest=reference.digest,
        )
        if source is None:
            baseline = self._production_sources.profile_source
            if (reference.source_id, reference.revision, reference.digest) != (
                baseline.source_id,
                baseline.revision,
                baseline.digest,
            ):
                raise MarketplacePublicationV2Error(
                    "profile_source_missing", "exact ROOT profile source is missing"
                )
            source = baseline
        bundles = tuple(
            [await self._load_bundle(reference) for reference in desired_record.desired_set.bundles]
        )
        composition = compose_profile_sources_v2(
            desired_set=desired_record.desired_set,
            bundles=bundles,
            profile_source=source,
            scope=scope,
        )
        generation, version = await self._next_publication_counters()
        snapshot = compose_profile_v2(
            composition.document,
            {manifest.plugin_id: manifest for manifest in composition.manifests},
            generation=generation,
        )
        result = await self._route_coordinator.publish_snapshot(
            snapshot,
            control_envelope_v2(snapshot, version=version),
            on_commit=self._on_route_commit,
        )
        publication = result.plugin_publication
        if PYTHON_API_DATA_PLANE_ID_V2 in self._publication_policy.required_data_plane_ids:
            _ = await self._publication_repository.record_publication_and_receipt(
                publication,
                data_plane_id=PYTHON_API_DATA_PLANE_ID_V2,
                policy=self._publication_policy,
            )
        else:
            _ = await self._publication_repository.record_publication(
                publication,
                policy=self._publication_policy,
            )
        return MarketplacePublicationResultV2(
            desired_revision=desired_record.desired_set.revision,
            publication=publication,
        )

    async def _load_bundle(self, reference: BundleReferenceV2) -> BundleManifestV2:
        return (await self._bundle_loader.load(reference)).manifest

    async def _next_publication_counters(self) -> tuple[int, int]:
        current = self._host.current_distribution
        if current is None:
            raise MarketplacePublicationV2Error(
                "plugin_runtime_uninitialized",
                "protocol v2 runtime has no active generation",
            )
        generation = current.snapshot.generation
        version = current.envelope.version
        latest = await self._publication_repository.latest_requested_distribution()
        if latest is not None:
            latest_snapshot = parse_profile_snapshot_v2(latest.get("snapshot"))
            latest_envelope = parse_control_envelope_v2(latest.get("envelope"))
            generation = max(generation, latest_snapshot.generation)
            version = max(version, latest_envelope.version)
        return generation + 1, version + 1


__all__ = [
    "MarketplacePublicationResultV2",
    "MarketplacePublicationV2Error",
    "PluginMarketplacePublicationServiceV2",
]
