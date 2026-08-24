"""Transactional v2 generation and HTTP route/OpenAPI publication coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.domain.model.plugins.generated_v2 import (
    ControlPlaneEnvelopeV2,
    ProfileSnapshotV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.plugins.v2.builtin_http_routes import (
    REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS,
    BuiltinRouteGraphV2,
    build_builtin_route_graph_v2,
)
from src.infrastructure.plugins.v2.http_routes import (
    RoutePublicationV2,
    RouteTableBuilderV2,
    RouteTableRegistryV2,
)
from src.infrastructure.plugins.v2.reconciler import PreparedGenerationPublicationV2
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from src.infrastructure.plugins.v2.runtime import RuntimeGenerationV2
from src.infrastructure.plugins.v2.runtime_host import (
    PlatformPluginPublicationV2,
    PlatformPluginRuntimeHostV2,
)


@dataclass(frozen=True, kw_only=True)
class HttpRouteGenerationPublicationV2:
    """One attempted runtime generation and its accepted route companion, if any."""

    plugin_publication: PlatformPluginPublicationV2
    route_publication: RoutePublicationV2 | None
    graph: BuiltinRouteGraphV2 | None


class HttpRoutePublicationCoordinatorV2:
    """Stage route effects and OpenAPI before publishing their runtime generation."""

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        *,
        host: PlatformPluginRuntimeHostV2,
        registry: RouteTableRegistryV2,
        workspace_core_settings: object,
        dependency_overrides: Mapping[Callable[..., Any], Callable[..., Any]] | None = None,
    ) -> None:
        self._host = host
        self._registry = registry
        self._workspace_core_settings = workspace_core_settings
        self._dependency_overrides = dict(dependency_overrides or {})
        self._lock = asyncio.Lock()

    async def publish_snapshot(
        self,
        snapshot: ProfileSnapshotV2,
        envelope: ControlPlaneEnvelopeV2,
        *,
        on_commit: Callable[[BuiltinRouteGraphV2], None] | None = None,
    ) -> HttpRouteGenerationPublicationV2:
        """Publish any complete v2 snapshot with the same route/OpenAPI transaction."""
        async with self._lock:
            result = await self._publish_locked(snapshot, envelope)
            if result.plugin_publication.accepted and result.graph is not None:
                if on_commit is not None:
                    on_commit(result.graph)
            return result

    async def _publish_locked(
        self,
        snapshot: ProfileSnapshotV2,
        envelope: ControlPlaneEnvelopeV2,
    ) -> HttpRouteGenerationPublicationV2:
        staged_graph: BuiltinRouteGraphV2 | None = None
        staged_route_publication: RoutePublicationV2 | None = None

        async def stage_routes(
            generation: RuntimeGenerationV2,
        ) -> PreparedGenerationPublicationV2:
            nonlocal staged_graph, staged_route_publication
            builder = generation.resolve(
                ROUTE_TABLE_BUILDER_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )
            if not isinstance(builder, RouteTableBuilderV2):
                raise TypeError("plugin runtime v2 staged an invalid route table builder")
            contributed_routes = builder.freeze().definitions
            graph = build_builtin_route_graph_v2(
                workspace_core_settings=self._workspace_core_settings,
                route_definitions=contributed_routes,
                required_v2_row_ids=REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS,
                dependency_overrides=self._dependency_overrides,
            )
            route_publication = self._registry.stage(generation.descriptor, graph.table)
            staged_graph = graph
            staged_route_publication = route_publication
            return PreparedGenerationPublicationV2(
                commit=lambda: self._registry.activate(route_publication),
                rollback=lambda: self._registry.discard(route_publication),
            )

        publication = await self._host.apply(
            snapshot,
            envelope,
            publication_stager=stage_routes,
        )
        if not publication.accepted:
            return HttpRouteGenerationPublicationV2(
                plugin_publication=publication,
                route_publication=None,
                graph=None,
            )
        if staged_graph is None or staged_route_publication is None:
            raise RuntimeError("accepted plugin route generation has no staged route graph")
        return HttpRouteGenerationPublicationV2(
            plugin_publication=publication,
            route_publication=staged_route_publication,
            graph=staged_graph,
        )


__all__ = [
    "HttpRouteGenerationPublicationV2",
    "HttpRoutePublicationCoordinatorV2",
]
