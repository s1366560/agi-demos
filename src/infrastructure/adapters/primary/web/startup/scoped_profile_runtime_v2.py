"""Application-owned scoped publication, artifact loading and admission."""

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from functools import partial
from typing import TYPE_CHECKING, Any, cast

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.plugin_instance_service_v2 import PluginInstanceServiceV2
from src.application.services.scoped_installed_bundle_loader_v2 import ScopedInstalledBundleLoaderV2
from src.application.services.scoped_profile_initialization_service_v2 import (
    ScopedProfileInitializationServiceV2,
)
from src.application.services.scoped_profile_publication_service_v2 import (
    ScopedProfilePublicationResultV2,
    ScopedProfilePublicationServiceV2,
)
from src.domain.model.plugins.generated_v2 import ScopeV2, ServiceRequiredV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_recovery_repository_v2 import (
    PlatformPluginRecoveryRepositoryV2,
)
from src.infrastructure.plugins.v2.builtin_http_routes import (
    build_builtin_route_graph_v2,
    generation_route_definitions_v2,
)
from src.infrastructure.plugins.v2.bundle_archive import VerifiedBundleArchiveV2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.profile_composition_cache import ProfileCompositionCacheV2
from src.infrastructure.plugins.v2.reconciler import PreparedGenerationPublicationV2
from src.infrastructure.plugins.v2.runtime import RuntimeGenerationV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.scoped_builtin_runtime import (
    scoped_builtin_runtime_definitions_v2,
)
from src.infrastructure.plugins.v2.scoped_publication_coordinator import (
    ScopedPublicationCoordinatorV2,
)
from src.infrastructure.plugins.v2.scoped_runtime_registry import (
    ScopedRuntimeRegistryV2,
    ScopedRuntimeReservationV2,
)

if TYPE_CHECKING:
    from src.domain.ports.services.graph_store_port import GraphStorePort


class ScopedProfileRuntimeV2:
    """Internal authorized consumers declare roots and own returned operation reservations."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        coordinator: ScopedPublicationCoordinatorV2,
        bundle_loader: ScopedInstalledBundleLoaderV2,
        initializer: ScopedProfileInitializationServiceV2,
    ) -> None:
        super().__init__()
        self._sessions = session_factory
        self._coordinator = coordinator
        self._loader = bundle_loader
        self._initializer = initializer
        self._composition_cache = ProfileCompositionCacheV2()
        self._closed = False

    def project_graph(
        self, payload: dict[str, Any], *, actor_id: str
    ) -> AbstractAsyncContextManager[tuple[ScopeV2, "GraphStorePort"]]:
        from .project_graph_lease import project_graph_lease

        return project_graph_lease(self._sessions, self, payload, actor_id=actor_id)

    async def prepare_current(
        self,
        scope: ScopeV2,
        *,
        actor_id: str,
        required_services: Sequence[ServiceRequiredV2],
    ) -> ScopedProfilePublicationResultV2:
        """Initialize missing configuration after authorization, then publish its exact source."""
        if self._closed:
            raise RuntimeV2Error("scoped_runtime_closed", "scoped runtime is closed")
        _ = await self._initializer.ensure_initialized(scope, actor_id=actor_id)
        from src.application.services.marketplace_signed_scope_v2 import (
            reconcile_signed_session_scope,
        )

        async with self._sessions() as session:
            await reconcile_signed_session_scope(session, scope, actor_id)
        return await self.publish_current(scope, required_services=required_services)

    async def publish_current(
        self, scope: ScopeV2, *, required_services: Sequence[ServiceRequiredV2]
    ) -> ScopedProfilePublicationResultV2:
        if self._closed:
            raise RuntimeV2Error("scoped_runtime_closed", "scoped runtime is closed")
        return await ScopedProfilePublicationServiceV2(
            session_factory=self._sessions,
            coordinator=self._coordinator,
            load_verified_bundle=partial(self._loader, scope=scope),
            required_services=required_services,
        ).publish_current(scope)

    async def acquire(self, scope: ScopeV2) -> ScopedRuntimeReservationV2:
        if self._closed:
            raise RuntimeV2Error("scoped_runtime_closed", "scoped runtime is closed")
        try:
            return await self._coordinator.acquire_bound(scope)
        except RuntimeV2Error as error:
            if error.code != "scope_not_admitted":
                raise
        await self.restore_existing(scope)
        return await self._coordinator.acquire_bound(scope)

    def instances(self, scope: ScopeV2) -> PluginInstanceServiceV2:
        """Return a manager for a scope already authorized by its HTTP caller."""
        from src.infrastructure.plugins.v2.agent_turn_requirements_v2 import (
            AGENT_TURN_REQUIRED_SERVICES_V2,
        )

        if self._closed:
            raise RuntimeV2Error("scoped_runtime_closed", "scoped runtime is closed")
        return PluginInstanceServiceV2(
            session_factory=self._sessions,
            initializer=self._initializer,
            load_bundle=partial(self._loader, scope=scope),
            scope=scope,
            composition_cache=self._composition_cache,
            publish=partial(
                self.publish_current, scope, required_services=AGENT_TURN_REQUIRED_SERVICES_V2
            ),
        )

    async def restore_existing(self, scope: ScopeV2) -> None:
        """Recover only historically bound authority after the consumer has authorized scope."""
        if self._closed:
            raise RuntimeV2Error("scoped_runtime_closed", "scoped runtime is closed")
        async with self._sessions() as session:
            state = await PlatformPluginRecoveryRepositoryV2(session).read(
                scope=scope, data_plane_id=PYTHON_API_DATA_PLANE_ID_V2
            )
        if state.source is None or state.last_good is None or state.latest_receipt is None:
            raise RuntimeV2Error(
                "scope_recovery_unavailable", "scope lacks bound recovery authority"
            )
        archives: list[VerifiedBundleArchiveV2] = []
        for reference in state.source.bundles:
            archive = cast(object, await self._loader(reference, scope=scope))
            if not isinstance(archive, VerifiedBundleArchiveV2):
                raise RuntimeV2Error(
                    "scope_bundle_unverified", "recovery requires verified archives"
                )
            archives.append(archive)
        try:
            _ = await self._coordinator.restore_last_good(
                scope, expected_state=state, verified_archives=archives
            )
        except RuntimeV2Error as error:
            if error.code != "scope_recovery_conflict":
                raise
            # Another authorized caller may have restored this scope while archives loaded.
            reservation = await self._coordinator.acquire_bound(scope)
            await reservation.lease.release()

    async def close(self) -> None:
        self._closed = True
        self._composition_cache.clear()
        await self._coordinator.close()


async def _noop_route_rollback() -> None:
    return None


def _noop_route_publication() -> PreparedGenerationPublicationV2:
    return PreparedGenerationPublicationV2(commit=lambda: None, rollback=_noop_route_rollback)


async def publish_scoped_generation_routes_v2(
    app: FastAPI,
    scope: ScopeV2,
    generation: RuntimeGenerationV2,
) -> PreparedGenerationPublicationV2:
    """Stage this scoped generation's own HTTP table without replacing the root one.

    Chat turns pin the scoped generation. system_api reads that generation's
    published OpenAPI. Copying the root table would cross the generation boundary.
    """
    definitions = generation_route_definitions_v2(generation, scope, optional=True)
    if definitions is None:
        return _noop_route_publication()
    registry = getattr(app.state, "platform_plugin_route_registry_v2", None)
    if not isinstance(registry, RouteTableRegistryV2):
        raise RuntimeV2Error(
            "route_registry_unavailable", "scoped HTTP publication requires a route registry"
        )
    graph = build_builtin_route_graph_v2(
        workspace_core_settings=None,
        route_definitions=definitions,
        dependency_overrides=app.dependency_overrides,
    )
    registry.stage_scoped(generation, graph.table)
    # A failed candidate and a drained generation both dispose their staged companions.
    return _noop_route_publication()


def initialize_scoped_profile_runtime_v2(
    app: FastAPI,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: object | None,
) -> ScopedProfileRuntimeV2:
    if getattr(app.state, "scoped_profile_runtime_v2", None) is not None:
        raise RuntimeError("scoped profile runtime is already initialized")
    host = getattr(app.state, "platform_plugin_runtime_v2", None)
    if not isinstance(host, PlatformPluginRuntimeHostV2) or host.current_distribution is None:
        raise RuntimeError("root plugin runtime must be initialized first")
    keys = getattr(app.state, "plugin_marketplace_trusted_public_keys_v2", None)
    registries = getattr(app.state, "plugin_marketplace_allowed_registries_v2", None)
    if not isinstance(keys, tuple) or not all(
        isinstance(key, str) for key in cast(tuple[object, ...], keys)
    ):
        raise TypeError("deployment plugin trust keys are not initialized")
    if not isinstance(registries, frozenset) or not all(
        isinstance(value, str) for value in cast(frozenset[object], registries)
    ):
        raise TypeError("deployment plugin registries are not initialized")
    sources = production_bundle_sources_v2()
    loader = ScopedInstalledBundleLoaderV2(
        session_factory=session_factory,
        production_sources=sources,
        trusted_public_keys=cast(tuple[str, ...], keys),
        allowed_registries=cast(frozenset[str], registries),
    )
    registry = ScopedRuntimeRegistryV2(
        definitions_factory=lambda scope: scoped_builtin_runtime_definitions_v2(
            scope,
            sandbox_owner_host=host,
            redis_client=redis_client,
            billing_schema_sessions=session_factory,
        ),
        route_publisher=partial(publish_scoped_generation_routes_v2, app),
    )
    runtime = ScopedProfileRuntimeV2(
        session_factory=session_factory,
        coordinator=ScopedPublicationCoordinatorV2(
            session_factory=session_factory, registry=registry
        ),
        bundle_loader=loader,
        initializer=ScopedProfileInitializationServiceV2(
            session_factory=session_factory, production_sources=sources
        ),
    )
    app.state.scoped_profile_runtime_v2 = runtime
    return runtime


async def shutdown_scoped_profile_runtime_v2(app: FastAPI) -> None:
    runtime = getattr(app.state, "scoped_profile_runtime_v2", None)
    if runtime is None:
        return
    if not isinstance(runtime, ScopedProfileRuntimeV2):
        raise TypeError("application scoped runtime has an invalid type")
    await runtime.close()
    app.state.scoped_profile_runtime_v2 = None
