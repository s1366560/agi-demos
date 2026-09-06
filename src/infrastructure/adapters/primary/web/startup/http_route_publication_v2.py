"""Transactional v2 generation and HTTP route/OpenAPI publication coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
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
from src.infrastructure.plugins.v2.bundle_archive import VerifiedBundleArchiveV2
from src.infrastructure.plugins.v2.http_routes import (
    RoutePublicationV2,
    RouteTableBuilderV2,
    RouteTableRegistryV2,
)
from src.infrastructure.plugins.v2.lifecycle_tasks import OwnedLifecycleTaskV2
from src.infrastructure.plugins.v2.reconciler import PreparedGenerationPublicationV2
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from src.infrastructure.plugins.v2.runtime import RuntimeGenerationV2, RuntimeV2Error
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
        initial_graph: BuiltinRouteGraphV2 | None = None,
    ) -> None:
        self._host = host
        self._registry = registry
        self._workspace_core_settings = workspace_core_settings
        self._dependency_overrides = dict(dependency_overrides or {})
        self._lock = asyncio.Lock()
        self._graph = initial_graph
        self._pending: HttpRouteGenerationPublicationV2 | None = None
        self._pending_on_commit: Callable[[BuiltinRouteGraphV2], None] | None = None

    async def publish_snapshot(
        self,
        snapshot: ProfileSnapshotV2,
        envelope: ControlPlaneEnvelopeV2,
        *,
        on_commit: Callable[[BuiltinRouteGraphV2], None] | None = None,
        verified_archives: Sequence[VerifiedBundleArchiveV2] | None = None,
        receipt_persister: Callable[[PlatformPluginPublicationV2], Awaitable[None]] | None = None,
    ) -> HttpRouteGenerationPublicationV2:
        """Publish routes and optionally persist receipts before allowing admission.

        Persistence and on_commit callbacks must be safe to retry after failure.
        Neither callback may reenter this coordinator or its host.
        """
        archives = None if verified_archives is None else tuple(verified_archives)
        results: list[HttpRouteGenerationPublicationV2] = []

        async def publish() -> None:
            async with self._lock:
                result = await self._publish_locked(
                    snapshot,
                    envelope,
                    verified_archives=archives,
                    receipt_persister=receipt_persister,
                    on_commit=on_commit,
                )
                if receipt_persister is None:
                    self._notify_commit(result, on_commit)
                results.append(result)

        if receipt_persister is None:
            await publish()
        else:
            await OwnedLifecycleTaskV2(publish, name="http-route-publication-receipt").wait()
        return results[0]

    def _route_result(
        self,
        publication: PlatformPluginPublicationV2,
    ) -> HttpRouteGenerationPublicationV2:
        if not publication.accepted:
            return HttpRouteGenerationPublicationV2(
                plugin_publication=publication,
                route_publication=None,
                graph=None,
            )
        current = self._host.manager.current
        routes = self._registry.current
        graph = self._graph
        if (
            current is None
            or routes is None
            or graph is None
            or routes.descriptor != current.descriptor
            or routes.table is not graph.table
        ):
            raise RuntimeV2Error(
                "route_publication_unavailable",
                "accepted runtime generation has no matching committed route graph",
            )
        return HttpRouteGenerationPublicationV2(
            plugin_publication=publication,
            route_publication=routes,
            graph=graph,
        )

    def _notify_commit(
        self,
        result: HttpRouteGenerationPublicationV2,
        callback: Callable[[BuiltinRouteGraphV2], None] | None,
    ) -> None:
        if result.plugin_publication.accepted and result.graph is not None and callback is not None:
            callback(result.graph)

    async def retry_pending_receipt(
        self,
        receipt_persister: Callable[[PlatformPluginPublicationV2], Awaitable[None]],
    ) -> HttpRouteGenerationPublicationV2:
        """Retry the actual retained receipt and graph without republishing routes."""
        results: list[HttpRouteGenerationPublicationV2] = []

        async def retry() -> None:
            async with self._lock:
                pending = self._pending
                if pending is None or self._host.pending_receipt is not pending.plugin_publication:
                    raise RuntimeV2Error(
                        "route_receipt_unavailable",
                        "no matching route receipt is pending",
                    )

                async def persist(publication: PlatformPluginPublicationV2) -> None:
                    if publication is not pending.plugin_publication:
                        raise RuntimeV2Error(
                            "route_receipt_mismatch", "pending route receipt changed"
                        )
                    if publication.accepted:
                        actual = self._route_result(publication)
                        if (
                            actual.graph is not pending.graph
                            or actual.route_publication is not pending.route_publication
                        ):
                            raise RuntimeV2Error(
                                "route_receipt_mismatch", "pending route graph changed"
                            )
                    await receipt_persister(publication)
                    self._notify_commit(pending, self._pending_on_commit)

                _ = await self._host.retry_pending_receipt(persist)
                self._pending = None
                self._pending_on_commit = None
                results.append(pending)

        await OwnedLifecycleTaskV2(retry, name="http-route-receipt-retry").wait()
        return results[0]

    async def _publish_locked(
        self,
        snapshot: ProfileSnapshotV2,
        envelope: ControlPlaneEnvelopeV2,
        *,
        verified_archives: Sequence[VerifiedBundleArchiveV2] | None = None,
        receipt_persister: Callable[[PlatformPluginPublicationV2], Awaitable[None]] | None = None,
        on_commit: Callable[[BuiltinRouteGraphV2], None] | None = None,
    ) -> HttpRouteGenerationPublicationV2:
        async def stage_routes(
            generation: RuntimeGenerationV2,
        ) -> PreparedGenerationPublicationV2:
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

            def commit() -> None:
                self._registry.activate(route_publication)
                self._graph = graph

            return PreparedGenerationPublicationV2(
                commit=commit,
                rollback=lambda: self._registry.discard(route_publication),
            )

        async def persist(publication: PlatformPluginPublicationV2) -> None:
            result = self._route_result(publication)
            self._pending = result
            self._pending_on_commit = on_commit
            if receipt_persister is None:
                raise RuntimeError("route receipt persister is unavailable")
            await receipt_persister(publication)
            self._notify_commit(result, on_commit)

        publication = await self._host.apply(
            snapshot,
            envelope,
            publication_stager=stage_routes,
            verified_archives=verified_archives,
            receipt_persister=persist if receipt_persister is not None else None,
        )
        result = self._route_result(publication)
        self._pending = None
        self._pending_on_commit = None
        return result


__all__ = [
    "HttpRouteGenerationPublicationV2",
    "HttpRoutePublicationCoordinatorV2",
]
