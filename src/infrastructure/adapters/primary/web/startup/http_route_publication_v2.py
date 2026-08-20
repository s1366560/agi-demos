"""Transactional v2 generation and HTTP route/OpenAPI publication coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.http_routes import HttpRouteMountError
from src.infrastructure.plugins.v2.builtin_http_routes import (
    BuiltinRouteGraphV2,
    build_builtin_route_graph_v2,
)
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, compose_profile_v2
from src.infrastructure.plugins.v2.http_routes import (
    RoutePublicationV2,
    RouteTableBuilderV2,
    RouteTableRegistryV2,
)
from src.infrastructure.plugins.v2.legacy_http_route_bridge import (
    LegacyHttpRouteRowV2,
    configured_legacy_http_routes_v2,
    project_legacy_http_routes_v2,
)
from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.infrastructure.plugins.v2.reconciler import PreparedGenerationPublicationV2
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from src.infrastructure.plugins.v2.runtime import RuntimeGenerationV2
from src.infrastructure.plugins.v2.runtime_host import (
    PlatformPluginPublicationV2,
    PlatformPluginRuntimeHostV2,
)


class HttpRoutePublicationRejectedV2(HttpRouteMountError):
    """A route generation NACK carrying the durable publication evidence."""

    def __init__(self, publication: PlatformPluginPublicationV2) -> None:
        self.publication = publication
        super().__init__(
            publication.receipt.error_message or "plugin route generation staging failed"
        )


@dataclass(frozen=True, kw_only=True)
class HttpRouteReconcilePublicationV2:
    """One successful desired-route generation publication."""

    mounted: int
    unmounted: int
    route_publication: RoutePublicationV2
    graph: BuiltinRouteGraphV2 | None
    plugin_publication: PlatformPluginPublicationV2 | None


class HttpRoutePublicationCoordinatorV2:
    """Stage route effects and OpenAPI before publishing their runtime generation."""

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        *,
        host: PlatformPluginRuntimeHostV2,
        registry: RouteTableRegistryV2,
        workspace_core_settings: object,
    ) -> None:
        self._host = host
        self._registry = registry
        self._workspace_core_settings = workspace_core_settings
        self._lock = asyncio.Lock()

    async def reconcile(
        self,
        desired_rows: Sequence[Any],
        *,
        on_commit: Callable[[BuiltinRouteGraphV2], None] | None = None,
    ) -> HttpRouteReconcilePublicationV2:
        """Publish a new digest only after its private route graph is fully valid."""
        async with self._lock:
            distribution = self._host.current_distribution
            if distribution is None:
                raise HttpRouteMountError("plugin runtime v2 has no current distribution")
            current_routes = configured_legacy_http_routes_v2(distribution.snapshot.entries)
            document = ProfileDocumentV2(
                profile_id=distribution.snapshot.profile_id,
                entries=distribution.snapshot.entries,
            )
            projected = project_legacy_http_routes_v2(document, desired_rows)
            requested_routes = configured_legacy_http_routes_v2(projected.entries)
            mounted, unmounted = _route_change_counts(current_routes, requested_routes)
            if current_routes == requested_routes:
                current = self._registry.current
                if current is None:
                    raise HttpRouteMountError("plugin route table v2 has no current publication")
                return HttpRouteReconcilePublicationV2(
                    mounted=0,
                    unmounted=0,
                    route_publication=current,
                    graph=None,
                    plugin_publication=None,
                )

            manifests = {
                manifest.plugin_id: manifest for manifest in distribution.snapshot.manifests
            }
            snapshot = compose_profile_v2(
                projected,
                manifests,
                generation=distribution.descriptor.generation + 1,
            )
            envelope = control_envelope_v2(
                snapshot,
                version=distribution.envelope.version + 1,
            )
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
                raise HttpRoutePublicationRejectedV2(publication)
            if staged_graph is None or staged_route_publication is None:
                raise RuntimeError("accepted plugin route generation has no staged route graph")
            if on_commit is not None:
                on_commit(staged_graph)
            return HttpRouteReconcilePublicationV2(
                mounted=mounted,
                unmounted=unmounted,
                route_publication=staged_route_publication,
                graph=staged_graph,
                plugin_publication=publication,
            )


def _route_change_counts(
    previous: Sequence[LegacyHttpRouteRowV2],
    requested: Sequence[LegacyHttpRouteRowV2],
) -> tuple[int, int]:
    old = {(row.method, row.path): row for row in previous if row.enabled}
    new = {(row.method, row.path): row for row in requested if row.enabled}
    changed = {key for key in old.keys() & new.keys() if old[key] != new[key]}
    mounted = len(new.keys() - old.keys())
    unmounted = len(old.keys() - new.keys()) + len(changed)
    return mounted, unmounted


__all__ = [
    "HttpRoutePublicationCoordinatorV2",
    "HttpRoutePublicationRejectedV2",
    "HttpRouteReconcilePublicationV2",
]
