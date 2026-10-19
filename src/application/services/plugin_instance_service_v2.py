"""Instance management over the existing ProfileSource, desired and publication stores."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.scoped_profile_initialization_service_v2 import (
    ScopedProfileInitializationServiceV2,
)
from src.domain.model.plugins.generated_v2 import (
    BundleReferenceV2,
    DesiredBundleSetV2,
    ProfileSnapshotV2,
    ProfileSourceV2,
    ScopeV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_recovery_repository_v2 import (
    PlatformPluginRecoveryRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.bundle_archive import VerifiedBundleArchiveV2
from src.infrastructure.plugins.v2.composer import compose_profile_v2
from src.infrastructure.plugins.v2.instance_configuration import (
    instance_rows_v2,
    revise_instance_source_v2,
    validate_instance_candidate_v2,
)
from src.infrastructure.plugins.v2.layer_composer import compose_profile_sources_v2
from src.infrastructure.plugins.v2.profile_composition_cache import ProfileCompositionCacheV2
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error
from src.infrastructure.plugins.v2.scope import scope_v2_to_payload


@dataclass(frozen=True, kw_only=True)
class InstanceConfigurationV2:
    desired: DesiredBundleSetV2
    source: ProfileSourceV2
    snapshot: ProfileSnapshotV2


class PluginInstanceServiceV2:
    """Internal service: callers authorize reads/writes before selecting this scope."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        initializer: ScopedProfileInitializationServiceV2,
        load_bundle: Callable[[BundleReferenceV2], Awaitable[VerifiedBundleArchiveV2]],
        publish: Callable[[], Awaitable[object]],
        scope: ScopeV2,
        composition_cache: ProfileCompositionCacheV2 | None = None,
    ) -> None:
        self._sessions = session_factory
        self._initializer = initializer
        self._load_bundle = load_bundle
        self._publish = publish
        self._composition_cache = composition_cache
        self.scope = scope

    async def initialize(self, actor_id: str) -> None:
        await self._initializer.ensure_initialized(self.scope, actor_id=actor_id)

    async def configuration(
        self, desired: DesiredBundleSetV2 | None = None
    ) -> InstanceConfigurationV2:
        async with self._sessions() as session:
            if desired is None:
                current = await PlatformPluginDesiredBundleSetRepositoryV2(
                    session
                ).current_desired_set(self.scope)
                if current is None:
                    raise RuntimeV2Error("scope_desired_missing", "scope configuration is missing")
                desired = current.desired_set
            reference = desired.profile_source
            source = await PlatformPluginProfileSourceRepositoryV2(session).read_exact(
                scope=self.scope,
                source_id=reference.source_id,
                revision=reference.revision,
                digest=reference.digest,
            )
            if source is None:
                raise RuntimeV2Error("scope_profile_source_missing", "scope source is missing")
        return InstanceConfigurationV2(
            desired=desired, source=source, snapshot=await self.compose(desired, source)
        )

    async def compose(
        self, desired: DesiredBundleSetV2, source: ProfileSourceV2
    ) -> ProfileSnapshotV2:
        archives = [await self._load_bundle(ref) for ref in desired.bundles]
        if any(not isinstance(archive, VerifiedBundleArchiveV2) for archive in archives):
            raise RuntimeV2Error("scope_bundle_unverified", "verified installed bundles required")
        if self._composition_cache is not None:
            return self._composition_cache.compose(
                desired=desired,
                source=source,
                bundles=tuple(archive.manifest for archive in archives),
                scope=self.scope,
            )
        composed = compose_profile_sources_v2(
            desired_set=desired,
            bundles=[archive.manifest for archive in archives],
            profile_source=source,
            scope=self.scope,
        )
        return compose_profile_v2(
            composed.document,
            {manifest.plugin_id: manifest for manifest in composed.manifests},
            generation=desired.revision,
        )

    async def effective_snapshot(self) -> ProfileSnapshotV2:
        """Always reconstruct the accepted source of this scope, including after restart."""
        await self._publish_pending_revision()
        async with self._sessions() as session:
            state = await PlatformPluginRecoveryRepositoryV2(session).read(
                self.scope, PYTHON_API_DATA_PLANE_ID_V2
            )
            await session.commit()
        if state.source is None:
            # First use publishes this private scope; a failure must never expose a parent view.
            await self._publish()
            async with self._sessions() as session:
                state = await PlatformPluginRecoveryRepositoryV2(session).read(
                    self.scope, PYTHON_API_DATA_PLANE_ID_V2
                )
                await session.commit()
        if state.source is None:
            raise RuntimeV2Error("scope_not_admitted", "scope has no accepted configuration")
        return (await self.configuration(state.source)).snapshot

    async def view(self) -> dict[str, Any]:
        await self._publish_pending_revision()
        configuration = await self.configuration()
        async with self._sessions() as session:
            repository = PlatformPluginRepositoryV2(session, scope=self.scope)
            readiness = await repository.latest_publication_readiness()
            state = await PlatformPluginRecoveryRepositoryV2(session).read(
                self.scope, PYTHON_API_DATA_PLANE_ID_V2
            )
            await session.commit()
        active = None if state.source is None else (await self.configuration(state.source)).snapshot
        publication = {
            "status": "unpublished" if readiness is None else readiness.status.value,
            "publication_id": None if readiness is None else readiness.publication_id,
            "generation": None if readiness is None else readiness.generation,
        }
        if readiness is not None and readiness.generation != configuration.desired.revision:
            publication["status"] = "reconciling"
        return {
            "scope": scope_v2_to_payload(self.scope),
            "revision": configuration.desired.revision,
            "publication": publication,
            "instances": instance_rows_v2(
                configuration.snapshot,
                scope=self.scope,
                publication_status=str(publication["status"]),
                active_snapshot=active,
            ),
        }

    async def _publish_pending_revision(self) -> None:
        """Reconcile deployment upgrades without retrying an already rejected candidate."""
        async with self._sessions() as session:
            desired = await PlatformPluginDesiredBundleSetRepositoryV2(session).current_desired_set(
                self.scope
            )
            readiness = await PlatformPluginRepositoryV2(
                session, scope=self.scope
            ).latest_publication_readiness()
            await session.commit()
        if desired is not None and (
            readiness is None or readiness.generation != desired.desired_set.revision
        ):
            await self._publish()

    async def apply(
        self,
        *,
        actor_id: str,
        expected_revision: int,
        changes: Sequence[Mapping[str, Any]],
        authorize: Callable[[AsyncSession], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        current = await self.configuration()
        source, desired = revise_instance_source_v2(
            source=current.source,
            desired=current.desired,
            snapshot=current.snapshot,
            scope=self.scope,
            expected_revision=expected_revision,
            changes=changes,
        )
        candidate = await self.compose(desired, source)
        validate_instance_candidate_v2(candidate)
        async with self._sessions() as session:
            if authorize is not None:
                await authorize(session)
            # Both rows share the existing scope lock and commit atomically.
            await PlatformPluginProfileSourceRepositoryV2(session).record_source(
                scope=self.scope,
                source=source,
                expected_revision=current.source.revision,
            )
            await PlatformPluginDesiredBundleSetRepositoryV2(session).record_desired_set(
                scope=self.scope,
                desired_set=desired,
                expected_revision=expected_revision,
                actor_id=actor_id,
            )
            await session.commit()
        await self._publish()
        return await self.view()
