"""V2-owned production contributions for the builtin deploy HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import status

from src.application.schemas.deploy_schemas import DeployListResponse, DeployResponse
from src.infrastructure.adapters.primary.web.routers.deploy import (
    cancel_deploy,
    create_deploy,
    get_deploy,
    get_latest_deploy,
    list_deploys,
    mark_deploy_failed,
    mark_deploy_success,
    stream_deploy_progress,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

DEPLOY_HTTP_ROUTES_ENTRY_V2 = "builtin-deploy-http-routes"
DEPLOY_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/deploy-routes"
DEPLOY_HTTP_ROUTES_ROW_V2 = "deploy"
_DEPLOY_PREFIX_V2 = "/api/v1/deploys"


def _deploy_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=DEPLOY_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("Deploys",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=DEPLOY_HTTP_ROUTES_ROW_V2,
    )


def deploy_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``deploy`` inventory row."""
    prefix = _DEPLOY_PREFIX_V2
    return (
        _deploy_route_v2(
            path=f"{prefix}/",
            methods=("POST",),
            endpoint=create_deploy,
            name="create_deploy",
            response_model=DeployResponse,
            status_code=status.HTTP_201_CREATED,
        ),
        _deploy_route_v2(
            path=f"{prefix}/",
            methods=("GET",),
            endpoint=list_deploys,
            name="list_deploys",
            response_model=DeployListResponse,
        ),
        _deploy_route_v2(
            path=f"{prefix}/instances/{{instance_id}}/latest",
            methods=("GET",),
            endpoint=get_latest_deploy,
            name="get_latest_deploy",
            response_model=DeployResponse,
        ),
        _deploy_route_v2(
            path=f"{prefix}/{{deploy_id}}",
            methods=("GET",),
            endpoint=get_deploy,
            name="get_deploy",
            response_model=DeployResponse,
        ),
        _deploy_route_v2(
            path=f"{prefix}/{{deploy_id}}/success",
            methods=("POST",),
            endpoint=mark_deploy_success,
            name="mark_deploy_success",
            response_model=DeployResponse,
        ),
        _deploy_route_v2(
            path=f"{prefix}/{{deploy_id}}/failed",
            methods=("POST",),
            endpoint=mark_deploy_failed,
            name="mark_deploy_failed",
            response_model=DeployResponse,
        ),
        _deploy_route_v2(
            path=f"{prefix}/{{deploy_id}}/cancel",
            methods=("POST",),
            endpoint=cancel_deploy,
            name="cancel_deploy",
            response_model=DeployResponse,
        ),
        _deploy_route_v2(
            path=f"{prefix}/{{deploy_id}}/progress",
            methods=("GET",),
            endpoint=stream_deploy_progress,
            name="stream_deploy_progress",
            response_model=None,
        ),
    )


def builtin_deploy_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register deploy routes as reversible effects of one V2 Fiber."""
    definitions = deploy_route_definitions_v2()

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

        await context.effect(setup, label=DEPLOY_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=DEPLOY_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(DEPLOY_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "DEPLOY_HTTP_ROUTES_ENTRY_V2",
    "DEPLOY_HTTP_ROUTES_MODULE_V2",
    "DEPLOY_HTTP_ROUTES_ROW_V2",
    "builtin_deploy_http_routes_definition_v2",
    "deploy_route_definitions_v2",
]
