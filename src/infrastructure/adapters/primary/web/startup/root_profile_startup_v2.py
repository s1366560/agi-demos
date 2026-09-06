"""Persistent ROOT startup consumes exact configuration rather than activation overlays."""

from collections.abc import Callable, Mapping
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.root_profile_initialization_service_v2 import (
    RootProfileInitializationServiceV2,
)
from src.application.services.scoped_installed_bundle_loader_v2 import ScopedInstalledBundleLoaderV2
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.root_startup_request_v2 import (
    prepare_root_startup_request_v2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import compose_profile_sources_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import (
    parse_profile_snapshot_v2,
)
from src.infrastructure.plugins.v2.reconciler import GenerationPublicationStagerV2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import (
    PlatformPluginPublicationV2,
    PlatformPluginRuntimeHostV2,
)


async def publish_configured_root_startup_v2(
    host: PlatformPluginRuntimeHostV2,
    *,
    session_factory: Callable[[], Any],
    durable_distribution: Mapping[str, object] | None,
    latest_distribution: Mapping[str, object] | None,
    workspace_core_enabled: bool,
    agent_pool_runtime_enabled: bool,
    agent_pool_runtime_config: Mapping[str, object],
    trusted_public_keys: tuple[str, ...],
    allowed_registries: frozenset[str],
    publication_stager: GenerationPublicationStagerV2,
    publication_policy: PlatformPluginPublicationPolicyV2,
) -> tuple[PlatformPluginPublicationV2, bool]:
    sources = production_bundle_sources_v2()
    root = ScopeV2(kind=ScopeKindV2.ROOT)
    if durable_distribution is not None:
        async with session_factory() as session:
            existing = await PlatformPluginDesiredBundleSetRepositoryV2(
                session
            ).current_desired_set(root)
        if existing is None:
            raise RuntimeV2Error(
                "root_profile_migration_required",
                "durable ROOT runtime has no desired configuration; explicit migration is required",
            )
    desired_record = await RootProfileInitializationServiceV2(
        session_factory=cast(async_sessionmaker[AsyncSession], session_factory),
        production_sources=sources,
    ).ensure_initialized(
        workspace_core_enabled=workspace_core_enabled,
        agent_pool_runtime_enabled=agent_pool_runtime_enabled,
        agent_pool_runtime_config=agent_pool_runtime_config,
    )
    desired = desired_record.desired_set
    ref = desired.profile_source
    async with session_factory() as session:
        source = await PlatformPluginProfileSourceRepositoryV2(session).read_exact(
            scope=root, source_id=ref.source_id, revision=ref.revision, digest=ref.digest
        )
    if source is None:
        baseline = sources.profile_source
        if (ref.source_id, ref.revision, ref.digest) != (
            baseline.source_id,
            baseline.revision,
            baseline.digest,
        ):
            raise RuntimeV2Error("root_profile_source_missing", "exact ROOT source is unavailable")
        source = baseline
    loader = ScopedInstalledBundleLoaderV2(
        session_factory=cast(async_sessionmaker[AsyncSession], session_factory),
        production_sources=sources,
        trusted_public_keys=trusted_public_keys,
        allowed_registries=allowed_registries,
    )
    archives = [await loader(reference) for reference in desired.bundles]
    composition = compose_profile_sources_v2(
        desired_set=desired,
        bundles=tuple(archive.manifest for archive in archives),
        profile_source=source,
        scope=root,
    )
    manifests = {manifest.plugin_id: manifest for manifest in composition.manifests}
    previous = (
        parse_profile_snapshot_v2(durable_distribution.get("snapshot"))
        if durable_distribution is not None
        else None
    )
    candidate = compose_profile_v2(
        composition.document,
        manifests,
        generation=previous.generation if previous is not None else 1,
    )
    if (
        durable_distribution is not None
        and previous is not None
        and candidate.digest == previous.digest
    ):
        return (
            await host.apply_distribution(
                durable_distribution,
                publication_stager=publication_stager,
                verified_archives=archives,
            ),
            False,
        )
    generation = 0
    for distribution in (durable_distribution, latest_distribution):
        if distribution is not None:
            snapshot = parse_profile_snapshot_v2(distribution.get("snapshot"))
            generation = max(generation, snapshot.generation)
    candidate = compose_profile_v2(composition.document, manifests, generation=generation + 1)
    candidate, envelope = await prepare_root_startup_request_v2(
        session_factory=session_factory,
        candidate=candidate,
        desired=desired,
        archives=archives,
        policy=publication_policy,
    )
    return (
        await host.apply(
            candidate,
            envelope,
            publication_stager=publication_stager,
            verified_archives=archives,
        ),
        True,
    )
