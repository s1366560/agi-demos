"""V2-owned production contributions for the builtin clusters HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import status

from src.application.schemas.acp_runner_schemas import (
    ACPRunnerPoolResponse,
    ACPRunnerTokenResponse,
)
from src.application.schemas.cluster_schemas import (
    ClusterHealthResponse,
    ClusterListResponse,
    ClusterResponse,
)
from src.infrastructure.adapters.primary.web.routers.clusters import (
    create_cluster,
    create_cluster_acp_runner_pool,
    create_cluster_acp_runner_registration_token,
    delete_cluster,
    get_cluster,
    get_cluster_health,
    list_cluster_acp_runner_pools,
    list_clusters,
    update_cluster,
    update_cluster_acp_runner_pool,
    update_health_status,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CLUSTERS_HTTP_ROUTES_ENTRY_V2 = "builtin-clusters-http-routes"
CLUSTERS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/clusters-routes"
CLUSTERS_HTTP_ROUTES_ROW_V2 = "clusters"
_CLUSTERS_PREFIX_V2 = "/api/v1/clusters"


def _cluster_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=CLUSTERS_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("Clusters",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=CLUSTERS_HTTP_ROUTES_ROW_V2,
    )


def cluster_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``clusters`` inventory row."""
    prefix = _CLUSTERS_PREFIX_V2
    return (
        _cluster_route_v2(
            path=f"{prefix}/",
            methods=("POST",),
            endpoint=create_cluster,
            name="create_cluster",
            response_model=ClusterResponse,
            status_code=status.HTTP_201_CREATED,
        ),
        _cluster_route_v2(
            path=f"{prefix}/",
            methods=("GET",),
            endpoint=list_clusters,
            name="list_clusters",
            response_model=ClusterListResponse,
        ),
        _cluster_route_v2(
            path=f"{prefix}/{{cluster_id}}",
            methods=("GET",),
            endpoint=get_cluster,
            name="get_cluster",
            response_model=ClusterResponse,
        ),
        _cluster_route_v2(
            path=f"{prefix}/{{cluster_id}}",
            methods=("PUT",),
            endpoint=update_cluster,
            name="update_cluster",
            response_model=ClusterResponse,
        ),
        _cluster_route_v2(
            path=f"{prefix}/{{cluster_id}}",
            methods=("DELETE",),
            endpoint=delete_cluster,
            name="delete_cluster",
            response_model=None,
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _cluster_route_v2(
            path=f"{prefix}/{{cluster_id}}/acp-runner-pools",
            methods=("GET",),
            endpoint=list_cluster_acp_runner_pools,
            name="list_cluster_acp_runner_pools",
            response_model=list[ACPRunnerPoolResponse],
        ),
        _cluster_route_v2(
            path=f"{prefix}/{{cluster_id}}/acp-runner-pools",
            methods=("POST",),
            endpoint=create_cluster_acp_runner_pool,
            name="create_cluster_acp_runner_pool",
            response_model=ACPRunnerPoolResponse,
            status_code=status.HTTP_201_CREATED,
        ),
        _cluster_route_v2(
            path=f"{prefix}/{{cluster_id}}/acp-runner-pools/{{pool_key}}",
            methods=("PUT",),
            endpoint=update_cluster_acp_runner_pool,
            name="update_cluster_acp_runner_pool",
            response_model=ACPRunnerPoolResponse,
        ),
        _cluster_route_v2(
            path=(f"{prefix}/{{cluster_id}}/acp-runner-pools/{{pool_key}}/registration-token"),
            methods=("POST",),
            endpoint=create_cluster_acp_runner_registration_token,
            name="create_cluster_acp_runner_registration_token",
            response_model=ACPRunnerTokenResponse,
        ),
        _cluster_route_v2(
            path=f"{prefix}/{{cluster_id}}/health",
            methods=("GET",),
            endpoint=get_cluster_health,
            name="get_cluster_health",
            response_model=ClusterHealthResponse,
        ),
        _cluster_route_v2(
            path=f"{prefix}/{{cluster_id}}/health",
            methods=("PUT",),
            endpoint=update_health_status,
            name="update_health_status",
            response_model=ClusterResponse,
        ),
    )


def builtin_clusters_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register cluster routes as reversible effects of one V2 Fiber."""
    definitions = cluster_route_definitions_v2()

    async def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        builder = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
        if not isinstance(builder, RouteTableBuilderV2):
            raise RuntimeV2Error(
                "invalid_route_table_builder",
                "route_table inject is not a protocol v2 route table builder",
            )

        async def setup() -> tuple[Callable[[], Awaitable[None]], ...]:
            disposers: list[Callable[[], Awaitable[None]]] = []
            try:
                for definition in definitions:
                    disposers.append(builder.contribute(definition))
            except Exception:
                for dispose in reversed(disposers):
                    await dispose()
                raise
            return tuple(disposers)

        await context.effect(setup, label=CLUSTERS_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=CLUSTERS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(CLUSTERS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "CLUSTERS_HTTP_ROUTES_ENTRY_V2",
    "CLUSTERS_HTTP_ROUTES_MODULE_V2",
    "CLUSTERS_HTTP_ROUTES_ROW_V2",
    "builtin_clusters_http_routes_definition_v2",
    "cluster_route_definitions_v2",
]
