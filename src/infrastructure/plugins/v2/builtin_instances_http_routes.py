"""V2-owned production contributions for the builtin instances HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import status

from src.application.schemas.deploy_schemas import DeployResponse
from src.application.schemas.instance_schemas import (
    InstanceListResponse,
    InstanceMemberListResponse,
    InstanceMemberResponse,
    InstanceResponse,
    UserSearchResult,
)
from src.infrastructure.adapters.primary.web.routers.instances import (
    InstanceConfigResponse,
    InstanceLlmConfigResponse,
    add_member,
    apply_pending_config,
    create_instance,
    delete_instance,
    get_config,
    get_instance,
    get_instance_llm_config,
    list_instances,
    list_members,
    remove_member,
    restart_instance,
    save_pending_config,
    scale_instance,
    search_users,
    update_config,
    update_instance,
    update_instance_llm_config,
    update_member_role,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

INSTANCES_HTTP_ROUTES_ENTRY_V2 = "builtin-instances-http-routes"
INSTANCES_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/instances-routes"
INSTANCES_HTTP_ROUTES_ROW_V2 = "instances"
_INSTANCES_PREFIX_V2 = "/api/v1/instances"


def _instance_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=INSTANCES_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("Instances",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=INSTANCES_HTTP_ROUTES_ROW_V2,
    )


def instance_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``instances`` inventory row."""
    prefix = _INSTANCES_PREFIX_V2
    return (
        _instance_route_v2(
            path=f"{prefix}/",
            methods=("POST",),
            endpoint=create_instance,
            name="create_instance",
            response_model=InstanceResponse,
            status_code=status.HTTP_201_CREATED,
        ),
        _instance_route_v2(
            path=f"{prefix}/",
            methods=("GET",),
            endpoint=list_instances,
            name="list_instances",
            response_model=InstanceListResponse,
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}",
            methods=("GET",),
            endpoint=get_instance,
            name="get_instance",
            response_model=InstanceResponse,
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}",
            methods=("PUT",),
            endpoint=update_instance,
            name="update_instance",
            response_model=InstanceResponse,
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}",
            methods=("DELETE",),
            endpoint=delete_instance,
            name="delete_instance",
            response_model=None,
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}/scale",
            methods=("POST",),
            endpoint=scale_instance,
            name="scale_instance",
            response_model=InstanceResponse,
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}/restart",
            methods=("POST",),
            endpoint=restart_instance,
            name="restart_instance",
            response_model=InstanceResponse,
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}/config",
            methods=("GET",),
            endpoint=get_config,
            name="get_config",
            response_model=InstanceConfigResponse,
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}/config",
            methods=("PUT",),
            endpoint=update_config,
            name="update_config",
            response_model=InstanceConfigResponse,
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}/config/pending",
            methods=("PUT",),
            endpoint=save_pending_config,
            name="save_pending_config",
            response_model=InstanceResponse,
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}/config/apply",
            methods=("POST",),
            endpoint=apply_pending_config,
            name="apply_pending_config",
            response_model=DeployResponse,
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}/members",
            methods=("POST",),
            endpoint=add_member,
            name="add_member",
            response_model=InstanceMemberResponse,
            status_code=status.HTTP_201_CREATED,
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}/members/search-users",
            methods=("GET",),
            endpoint=search_users,
            name="search_users",
            response_model=list[UserSearchResult],
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}/members/{{member_id}}",
            methods=("PUT",),
            endpoint=update_member_role,
            name="update_member_role",
            response_model=InstanceMemberResponse,
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}/members/{{user_id}}",
            methods=("DELETE",),
            endpoint=remove_member,
            name="remove_member",
            response_model=None,
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}/members",
            methods=("GET",),
            endpoint=list_members,
            name="list_members",
            response_model=InstanceMemberListResponse,
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}/llm-config",
            methods=("GET",),
            endpoint=get_instance_llm_config,
            name="get_instance_llm_config",
            response_model=InstanceLlmConfigResponse,
        ),
        _instance_route_v2(
            path=f"{prefix}/{{instance_id}}/llm-config",
            methods=("PUT",),
            endpoint=update_instance_llm_config,
            name="update_instance_llm_config",
            response_model=InstanceLlmConfigResponse,
        ),
    )


def builtin_instances_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register instance routes as reversible effects of one V2 Fiber."""
    definitions = instance_route_definitions_v2()

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

        await context.effect(setup, label=INSTANCES_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=INSTANCES_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(INSTANCES_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "INSTANCES_HTTP_ROUTES_ENTRY_V2",
    "INSTANCES_HTTP_ROUTES_MODULE_V2",
    "INSTANCES_HTTP_ROUTES_ROW_V2",
    "builtin_instances_http_routes_definition_v2",
    "instance_route_definitions_v2",
]
