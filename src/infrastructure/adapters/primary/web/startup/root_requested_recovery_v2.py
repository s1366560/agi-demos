"""Resume an exact committed ROOT request after interruption before its first receipt."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.scoped_installed_bundle_loader_v2 import ScopedInstalledBundleLoaderV2
from src.domain.model.plugins.generated_v2 import (
    DesiredBundleSetV2,
    ProfileSourceV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_recovery_repository_v2 import (
    PlatformPluginRecoveryRepositoryV2,
    ScopedRecoveryStateV2,
)
from src.infrastructure.plugins.v2.bundle_archive import VerifiedBundleArchiveV2
from src.infrastructure.plugins.v2.composer import compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import compose_profile_sources_v2
from src.infrastructure.plugins.v2.production_bundle import (
    ProductionBundleSourcesV2,
    production_bundle_sources_v2,
)
from src.infrastructure.plugins.v2.reconciler import GenerationPublicationStagerV2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import (
    PlatformPluginDistributionV2,
    PlatformPluginPublicationV2,
    PlatformPluginRuntimeHostV2,
)
from src.infrastructure.plugins.v2.scope import scope_key_v2


@dataclass(frozen=True)
class _PendingRootV2:
    state: ScopedRecoveryStateV2
    desired: DesiredBundleSetV2
    source: ProfileSourceV2


async def _read_pending(
    session_factory: Callable[[], Any],
    sources: ProductionBundleSourcesV2,
    policy: PlatformPluginPublicationPolicyV2,
    *,
    expected_state: ScopedRecoveryStateV2 | None = None,
    accepted_state: ScopedRecoveryStateV2 | None = None,
) -> _PendingRootV2 | None:
    root = ScopeV2(kind=ScopeKindV2.ROOT)
    async with session_factory() as session:
        state = await PlatformPluginRecoveryRepositoryV2(session).read(
            root,
            PYTHON_API_DATA_PLANE_ID_V2,
        )
        if expected_state is not None and state not in (expected_state, accepted_state):
            raise RuntimeV2Error("root_recovery_changed", "ROOT request changed during recovery")
        if state.latest is None or (state.latest_receipt is not None and accepted_state is None):
            return None
        row = (
            await session.scalars(
                select(PlatformPluginV2PublicationModel).where(
                    PlatformPluginV2PublicationModel.scope_key == scope_key_v2(root),
                    PlatformPluginV2PublicationModel.nonce == state.latest.envelope.nonce,
                )
            )
        ).one()
        if set(row.required_data_plane_ids) != set(policy.required_data_plane_ids):
            raise RuntimeV2Error("root_recovery_policy_changed", "ROOT request policy changed")
        desired = await PlatformPluginPublicationSourceRepositoryV2(session).read(
            scope=root,
            publication_id=row.id,
        )
        if desired is None:
            raise RuntimeV2Error(
                "root_receipt_pending", "pending ROOT request has no source binding"
            )
        current = await PlatformPluginDesiredBundleSetRepositoryV2(session).current_desired_set(
            root
        )
        if current is None or current.desired_set != desired:
            raise RuntimeV2Error("root_recovery_changed", "pending ROOT desired source changed")
        reference = desired.profile_source
        source = await PlatformPluginProfileSourceRepositoryV2(session).read_exact(
            scope=root,
            source_id=reference.source_id,
            revision=reference.revision,
            digest=reference.digest,
        )
        if source is None:
            baseline = sources.profile_source
            if (reference.source_id, reference.revision, reference.digest) != (
                baseline.source_id,
                baseline.revision,
                baseline.digest,
            ):
                raise RuntimeV2Error(
                    "root_profile_source_missing", "exact ROOT source is unavailable"
                )
            source = baseline
        return _PendingRootV2(state, desired, source)


@dataclass(frozen=True)
class VerifiedRootRequestRecoveryV2:
    distribution: PlatformPluginDistributionV2
    archives: tuple[VerifiedBundleArchiveV2, ...]
    check_authority: Callable[[], Awaitable[None]]
    check_receipt_authority: Callable[[PlatformPluginPublicationV2], Awaitable[None]]


async def load_requested_root_recovery_v2(
    *,
    session_factory: Callable[[], Any],
    latest_distribution: Mapping[str, object] | None,
    durable_distribution: Mapping[str, object] | None,
    trusted_public_keys: tuple[str, ...],
    allowed_registries: frozenset[str],
    publication_policy: PlatformPluginPublicationPolicyV2,
) -> VerifiedRootRequestRecoveryV2 | None:
    """Load a verified candidate and a recheck bound to its exact durable authority."""
    if (
        latest_distribution is None
        or PYTHON_API_DATA_PLANE_ID_V2 not in publication_policy.required_data_plane_ids
    ):
        return None
    sources = production_bundle_sources_v2()
    pending = await _read_pending(session_factory, sources, publication_policy)
    if pending is None:
        return None
    latest = pending.state.latest
    retained = pending.state.last_good
    if (
        latest is None
        or latest.to_payload() != latest_distribution
        or (None if retained is None else retained.to_payload()) != durable_distribution
    ):
        raise RuntimeV2Error("root_recovery_changed", "ROOT request changed before recovery")
    loader = ScopedInstalledBundleLoaderV2(
        session_factory=cast(async_sessionmaker[AsyncSession], session_factory),
        production_sources=sources,
        trusted_public_keys=trusted_public_keys,
        allowed_registries=allowed_registries,
    )
    archives = tuple([await loader(reference) for reference in pending.desired.bundles])
    composition = compose_profile_sources_v2(
        desired_set=pending.desired,
        bundles=tuple(archive.manifest for archive in archives),
        profile_source=pending.source,
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    recomposed = compose_profile_v2(
        composition.document,
        {manifest.plugin_id: manifest for manifest in composition.manifests},
        generation=latest.snapshot.generation,
    )
    if recomposed != latest.snapshot:
        raise RuntimeV2Error(
            "root_recovery_snapshot_mismatch", "ROOT request differs from its source"
        )

    async def check_authority() -> None:
        if (
            await _read_pending(
                session_factory, sources, publication_policy, expected_state=pending.state
            )
            != pending
        ):
            raise RuntimeV2Error("root_recovery_changed", "ROOT request changed during recovery")

    async def check_receipt_authority(publication: PlatformPluginPublicationV2) -> None:
        if publication.snapshot != latest.snapshot or publication.envelope != latest.envelope:
            raise RuntimeV2Error("root_recovery_changed", "ROOT recovery receipt changed")
        receipted = ScopedRecoveryStateV2(
            scope=pending.state.scope,
            latest=latest,
            last_good=latest if publication.accepted else pending.state.last_good,
            latest_receipt=publication.receipt,
            source=pending.desired if publication.accepted else pending.state.source,
        )
        observed = await _read_pending(
            session_factory,
            sources,
            publication_policy,
            expected_state=pending.state,
            accepted_state=receipted,
        )
        if (
            observed is None
            or observed.desired != pending.desired
            or observed.source != pending.source
        ):
            raise RuntimeV2Error("root_recovery_changed", "ROOT request changed during recovery")

    await check_authority()
    return VerifiedRootRequestRecoveryV2(latest, archives, check_authority, check_receipt_authority)


async def recover_requested_root_startup_v2(
    host: PlatformPluginRuntimeHostV2,
    *,
    session_factory: Callable[[], Any],
    latest_distribution: Mapping[str, object] | None,
    durable_distribution: Mapping[str, object] | None,
    trusted_public_keys: tuple[str, ...],
    allowed_registries: frozenset[str],
    publication_stager: GenerationPublicationStagerV2,
    publication_policy: PlatformPluginPublicationPolicyV2,
) -> PlatformPluginPublicationV2 | None:
    """Apply only the bound request, without allocating or replacing its identity."""
    prepared = await load_requested_root_recovery_v2(
        session_factory=session_factory,
        latest_distribution=latest_distribution,
        durable_distribution=durable_distribution,
        trusted_public_keys=trusted_public_keys,
        allowed_registries=allowed_registries,
        publication_policy=publication_policy,
    )
    if prepared is None:
        return None
    publication = await host.apply_distribution(
        prepared.distribution.to_payload(),
        publication_stager=publication_stager,
        verified_archives=prepared.archives,
    )
    await prepared.check_authority()
    return publication
