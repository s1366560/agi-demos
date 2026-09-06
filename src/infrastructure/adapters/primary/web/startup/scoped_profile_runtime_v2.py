"""Application-owned scoped publication, artifact loading and admission."""

from collections.abc import Sequence
from typing import cast

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.scoped_installed_bundle_loader_v2 import ScopedInstalledBundleLoaderV2
from src.application.services.scoped_profile_publication_service_v2 import (
    ScopedProfilePublicationResultV2,
    ScopedProfilePublicationServiceV2,
)
from src.domain.model.plugins.generated_v2 import ScopeV2, ServiceRequiredV2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
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


class ScopedProfileRuntimeV2:
    """Internal authorized consumers declare roots and own returned operation reservations."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        coordinator: ScopedPublicationCoordinatorV2,
        bundle_loader: ScopedInstalledBundleLoaderV2,
    ) -> None:
        super().__init__()
        self._sessions = session_factory
        self._coordinator = coordinator
        self._loader = bundle_loader
        self._closed = False

    async def publish_current(
        self, scope: ScopeV2, *, required_services: Sequence[ServiceRequiredV2]
    ) -> ScopedProfilePublicationResultV2:
        if self._closed:
            raise RuntimeV2Error("scoped_runtime_closed", "scoped runtime is closed")
        return await ScopedProfilePublicationServiceV2(
            session_factory=self._sessions,
            coordinator=self._coordinator,
            load_verified_bundle=self._loader,
            required_services=required_services,
        ).publish_current(scope)

    async def acquire(self, scope: ScopeV2) -> ScopedRuntimeReservationV2:
        if self._closed:
            raise RuntimeV2Error("scoped_runtime_closed", "scoped runtime is closed")
        return await self._coordinator.acquire_bound(scope)

    async def close(self) -> None:
        self._closed = True
        await self._coordinator.close()


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
    loader = ScopedInstalledBundleLoaderV2(
        session_factory=session_factory,
        production_sources=production_bundle_sources_v2(),
        trusted_public_keys=cast(tuple[str, ...], keys),
        allowed_registries=cast(frozenset[str], registries),
    )
    registry = ScopedRuntimeRegistryV2(
        definitions_factory=lambda scope: scoped_builtin_runtime_definitions_v2(
            scope, sandbox_owner_host=host, redis_client=redis_client
        )
    )
    runtime = ScopedProfileRuntimeV2(
        session_factory=session_factory,
        coordinator=ScopedPublicationCoordinatorV2(
            session_factory=session_factory, registry=registry
        ),
        bundle_loader=loader,
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
