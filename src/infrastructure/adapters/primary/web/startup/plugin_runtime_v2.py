"""Protocol v2 plugin runtime startup and shutdown."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from starlette.types import Scope

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableBuilderV2, RouteTableRegistryV2
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

logger = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_PROFILE_V2_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
DEFAULT_MANIFEST_V2_PATHS = (_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",)


async def initialize_plugin_runtime_v2(app: FastAPI) -> PlatformPluginRuntimeHostV2:
    """Compose and publish the required initial v2 generation."""
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=DEFAULT_PROFILE_V2_PATH,
        manifest_paths=DEFAULT_MANIFEST_V2_PATHS,
        generation=1,
        version=1,
    )
    if not publication.accepted:
        await host.close()
        raise RuntimeError(
            "plugin runtime v2 bootstrap failed: "
            f"{publication.receipt.error_code}: {publication.receipt.error_message}"
        )
    app.state.platform_plugin_runtime_v2 = host
    distribution = host.current_distribution
    if distribution is None:
        await host.close()
        raise RuntimeError("plugin runtime v2 published without a current distribution")
    generation = host.manager.current
    if generation is None:
        await host.close()
        raise RuntimeError("plugin runtime v2 published without a current generation")
    route_builder = generation.resolve(
        ROUTE_TABLE_BUILDER_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    if not isinstance(route_builder, RouteTableBuilderV2):
        await host.close()
        raise RuntimeError("plugin runtime v2 published an invalid route table builder")
    contributed_routes = route_builder.freeze().definitions
    workspace_core_settings = getattr(app.state, "workspace_core_settings", None)
    if workspace_core_settings is None:
        from src.configuration.workspace_core import get_workspace_core_settings

        workspace_core_settings = get_workspace_core_settings()
    route_graph = build_builtin_route_graph_v2(
        workspace_core_settings=workspace_core_settings,
        route_definitions=contributed_routes,
    )
    route_registry = RouteTableRegistryV2()
    route_publication = await route_registry.publish(distribution.descriptor, route_graph.table)
    app.state.platform_plugin_route_registry_v2 = route_registry
    app.state.platform_plugin_route_graph_v2 = route_graph
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


async def shutdown_plugin_runtime_v2(app: FastAPI) -> None:
    """Retire the current v2 generation and wait for Fiber disposal."""
    host = getattr(app.state, "platform_plugin_runtime_v2", None)
    if not isinstance(host, PlatformPluginRuntimeHostV2):
        return
    await host.close()
    app.state.platform_plugin_runtime_v2 = None
    app.state.platform_plugin_route_registry_v2 = None
    app.state.platform_plugin_route_graph_v2 = None


def plugin_runtime_host_v2_from_scope(scope: Scope) -> PlatformPluginRuntimeHostV2:
    """Resolve the initialized host for the request generation middleware."""
    app = scope.get("app")
    host = getattr(getattr(app, "state", None), "platform_plugin_runtime_v2", None)
    if not isinstance(host, PlatformPluginRuntimeHostV2):
        raise RuntimeError("plugin runtime v2 is not initialized")
    return host
