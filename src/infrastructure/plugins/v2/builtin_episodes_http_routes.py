"""V2-owned production contributions for the episodes HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.graph_application_authority_v2 import (
    graph_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.episodes import (
    EpisodeDetail,
    EpisodeResponse,
    create_episode,
    delete_episode,
    get_episode,
    health_check,
    list_episodes,
)
from src.infrastructure.adapters.primary.web.workflow_application_authority_v2 import (
    workflow_engine_authority_dependency_v2,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

EPISODES_HTTP_ROUTES_ENTRY_V2 = "builtin-episodes-http-routes"
EPISODES_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/episodes-routes"
EPISODES_HTTP_ROUTES_ROW_V2 = "episodes"


def _episodes_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=EPISODES_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("episodes",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=EPISODES_HTTP_ROUTES_ROW_V2,
    )


def episodes_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``episodes`` inventory row."""
    prefix = "/api/v1/episodes"
    return (
        _episodes_route_v2(
            path=f"{prefix}/",
            methods=("POST",),
            endpoint=create_episode,
            name="create_episode",
            response_model=EpisodeResponse,
            status_code=202,
        ),
        _episodes_route_v2(
            path=f"{prefix}/by-name/{{episode_name}}",
            methods=("GET",),
            endpoint=get_episode,
            name="get_episode",
            response_model=EpisodeDetail,
        ),
        _episodes_route_v2(
            path=f"{prefix}/",
            methods=("GET",),
            endpoint=list_episodes,
            name="list_episodes",
            response_model=dict[str, Any],
        ),
        _episodes_route_v2(
            path=f"{prefix}/by-name/{{episode_name}}",
            methods=("DELETE",),
            endpoint=delete_episode,
            name="delete_episode",
            response_model=dict[str, Any],
        ),
        _episodes_route_v2(
            path=f"{prefix}/health",
            methods=("GET",),
            endpoint=health_check,
            name="health_check",
            response_model=dict,
        ),
    )


def builtin_episodes_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register episodes routes as reversible effects of one V2 Fiber."""
    definitions = episodes_route_definitions_v2()

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

        await context.effect(setup, label=EPISODES_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=EPISODES_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(EPISODES_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "EPISODES_HTTP_ROUTES_ENTRY_V2",
    "EPISODES_HTTP_ROUTES_MODULE_V2",
    "EPISODES_HTTP_ROUTES_ROW_V2",
    "builtin_episodes_http_routes_definition_v2",
    "episodes_route_definitions_v2",
    "get_current_user",
    "graph_application_authority_dependency_v2",
    "workflow_engine_authority_dependency_v2",
]
