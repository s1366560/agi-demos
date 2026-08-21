"""Protocol v2 plugin runtime startup and shutdown."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.types import Scope

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import (
    clear_process_generation_host_v2,
    install_process_generation_host_v2,
)
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableBuilderV2, RouteTableRegistryV2
from src.infrastructure.plugins.v2.legacy_http_route_bridge import project_legacy_http_routes_v2
from src.infrastructure.plugins.v2.reconciler import PreparedGenerationPublicationV2
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from src.infrastructure.plugins.v2.runtime import RuntimeGenerationV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import (
    PlatformPluginPublicationV2,
    PlatformPluginRuntimeHostV2,
)

from .http_route_publication_v2 import HttpRoutePublicationCoordinatorV2

logger = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_PROFILE_V2_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
DEFAULT_MANIFEST_V2_PATHS = (_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",)


async def initialize_plugin_runtime_v2(
    app: FastAPI,
    *,
    desired_http_route_rows: Sequence[Any] = (),
    session_factory: Callable[[], Any] | None = None,
) -> PlatformPluginRuntimeHostV2:
    """Compose and publish the required initial v2 generation."""
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    route_registry = RouteTableRegistryV2()
    route_graph = None
    route_publication = None
    try:
        workspace_core_settings = getattr(app.state, "workspace_core_settings", None)
        if workspace_core_settings is None:
            from src.configuration.workspace_core import get_workspace_core_settings

            workspace_core_settings = get_workspace_core_settings()

        async def stage_routes(
            generation: RuntimeGenerationV2,
        ) -> PreparedGenerationPublicationV2:
            nonlocal route_graph, route_publication
            route_builder = generation.resolve(
                ROUTE_TABLE_BUILDER_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )
            if not isinstance(route_builder, RouteTableBuilderV2):
                raise TypeError("plugin runtime v2 staged an invalid route table builder")
            contributed_routes = route_builder.freeze().definitions
            graph = build_builtin_route_graph_v2(
                workspace_core_settings=workspace_core_settings,
                route_definitions=contributed_routes,
            )
            staged = route_registry.stage(generation.descriptor, graph.table)
            route_graph = graph
            route_publication = staged
            return PreparedGenerationPublicationV2(
                commit=lambda: route_registry.activate(staged),
                rollback=lambda: route_registry.discard(staged),
            )

        durable_distribution = await _last_good_distribution_v2(session_factory)
        if durable_distribution is None:
            publication = await host.bootstrap(
                profile_path=DEFAULT_PROFILE_V2_PATH,
                manifest_paths=DEFAULT_MANIFEST_V2_PATHS,
                generation=1,
                version=1,
                profile_projector=lambda document: project_legacy_http_routes_v2(
                    document,
                    desired_http_route_rows,
                ),
                publication_stager=stage_routes,
            )
        else:
            publication = await host.apply_distribution(
                durable_distribution,
                publication_stager=stage_routes,
            )
        if not publication.accepted:
            await _record_startup_publication_v2(
                session_factory,
                publication,
                retain_requested_as_last_good=durable_distribution is not None,
            )
            failure = publication.receipt
            raise RuntimeV2Error(
                failure.error_code or "plugin_runtime_bootstrap_failed",
                failure.error_message or "plugin runtime v2 bootstrap failed",
            )
        distribution = host.current_distribution
        if distribution is None:
            raise RuntimeError("plugin runtime v2 published without a current distribution")
        generation = host.manager.current
        if generation is None:
            raise RuntimeError("plugin runtime v2 published without a current generation")
        if route_graph is None or route_publication is None:
            raise RuntimeError("plugin runtime v2 published without a staged route graph")
        if durable_distribution is None:
            await _record_startup_publication_v2(
                session_factory,
                publication,
            )
    except Exception:
        await host.close()
        raise

    app.state.platform_plugin_runtime_v2 = host
    app.state.platform_plugin_route_registry_v2 = route_registry
    app.state.platform_plugin_route_graph_v2 = route_graph
    app.state.platform_plugin_http_route_publication_v2 = HttpRoutePublicationCoordinatorV2(
        host=host,
        registry=route_registry,
        workspace_core_settings=workspace_core_settings,
    )
    install_process_generation_host_v2(host)
    logger.info(
        "Published plugin runtime v2 generation=%d digest=%s",
        publication.snapshot.generation,
        publication.snapshot.digest,
    )
    logger.info(
        "Published shadow HTTP route generation=%d rows=%d routes=%d",
        route_publication.descriptor.generation,
        len(route_graph.mounted_row_ids),
        len(route_graph.route_signatures),
    )
    return host


async def _last_good_distribution_v2(
    session_factory: Callable[[], Any] | None,
) -> Mapping[str, object] | None:
    if session_factory is None:
        return None
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
        PYTHON_API_DATA_PLANE_ID_V2,
        PlatformPluginRepositoryV2,
    )

    async with session_factory() as session:
        return await PlatformPluginRepositoryV2(session).last_good_distribution(
            PYTHON_API_DATA_PLANE_ID_V2
        )


async def _record_startup_publication_v2(
    session_factory: Callable[[], Any] | None,
    publication: PlatformPluginPublicationV2,
    *,
    retain_requested_as_last_good: bool = False,
) -> None:
    if session_factory is None:
        return
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
        PYTHON_API_DATA_PLANE_ID_V2,
        PlatformPluginRepositoryV2,
    )

    if (
        retain_requested_as_last_good
        and not publication.accepted
        and publication.receipt.applied_version is None
    ):
        publication = replace(
            publication,
            receipt=replace(
                publication.receipt,
                applied_version=publication.envelope.version,
                applied_digest=publication.snapshot.digest,
            ),
        )
    async with session_factory() as session:
        _ = await PlatformPluginRepositoryV2(session).record_publication_and_receipt(
            publication,
            data_plane_id=PYTHON_API_DATA_PLANE_ID_V2,
        )
        await session.commit()


async def shutdown_plugin_runtime_v2(app: FastAPI) -> None:
    """Retire the current v2 generation and wait for Fiber disposal."""
    host = getattr(app.state, "platform_plugin_runtime_v2", None)
    if not isinstance(host, PlatformPluginRuntimeHostV2):
        return
    clear_process_generation_host_v2(host)
    await host.close()
    app.state.platform_plugin_runtime_v2 = None
    app.state.platform_plugin_route_registry_v2 = None
    app.state.platform_plugin_route_graph_v2 = None
    app.state.platform_plugin_http_route_publication_v2 = None


def plugin_runtime_host_v2_from_scope(scope: Scope) -> PlatformPluginRuntimeHostV2:
    """Resolve the initialized host for the request generation middleware."""
    app = scope.get("app")
    host = getattr(getattr(app, "state", None), "platform_plugin_runtime_v2", None)
    if not isinstance(host, PlatformPluginRuntimeHostV2):
        raise RuntimeError("plugin runtime v2 is not initialized")
    return host
