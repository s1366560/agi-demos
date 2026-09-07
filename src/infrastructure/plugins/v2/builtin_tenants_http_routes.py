"""V2-owned production contributions for the tenants HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import status

from src.application.schemas.tenant import (
    TenantListResponse,
    TenantResponse,
)
from src.infrastructure.adapters.primary.web.routers.tenants import (
    GenePolicyResponse,
    RegistryResponse,
    TestConnectionResponse,
    add_tenant_member,
    add_tenant_member_json,
    create_registry,
    create_tenant,
    delete_gene_policy,
    delete_registry,
    delete_tenant,
    get_tenant,
    get_tenant_analytics,
    get_tenant_stats,
    list_gene_policies,
    list_registries,
    list_tenant_members,
    list_tenants,
    remove_tenant_member,
    test_registry_connection,
    update_registry,
    update_tenant,
    update_tenant_member_role,
    upsert_gene_policy,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

TENANTS_HTTP_ROUTES_ENTRY_V2 = "builtin-tenants-http-routes"
TENANTS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/tenants-routes"
TENANTS_HTTP_ROUTES_ROW_V2 = "tenants"


def _tenants_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    status_code: int | None = None,
    response_model: object | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=TENANTS_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("tenants",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=TENANTS_HTTP_ROUTES_ROW_V2,
    )


def tenants_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``tenants`` inventory row."""
    tenant_path = "/api/v1/tenants/{tenant_id}"
    return (
        _tenants_route_v2(
            path="/api/v1/tenants/",
            methods=("POST",),
            endpoint=create_tenant,
            name="create_tenant",
            status_code=status.HTTP_201_CREATED,
            response_model=TenantResponse,
        ),
        _tenants_route_v2(
            path="/api/v1/tenants/",
            methods=("GET",),
            endpoint=list_tenants,
            name="list_tenants",
            response_model=TenantListResponse,
        ),
        _tenants_route_v2(
            path=tenant_path,
            methods=("GET",),
            endpoint=get_tenant,
            name="get_tenant",
            response_model=TenantResponse,
        ),
        _tenants_route_v2(
            path=tenant_path,
            methods=("PUT",),
            endpoint=update_tenant,
            name="update_tenant",
            response_model=TenantResponse,
        ),
        _tenants_route_v2(
            path=tenant_path,
            methods=("DELETE",),
            endpoint=delete_tenant,
            name="delete_tenant",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/members/{{user_id}}",
            methods=("POST",),
            endpoint=add_tenant_member,
            name="add_tenant_member",
            status_code=status.HTTP_201_CREATED,
            response_model=dict[str, Any],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/members",
            methods=("POST",),
            endpoint=add_tenant_member_json,
            name="add_tenant_member_json",
            status_code=status.HTTP_201_CREATED,
            response_model=dict[str, Any],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/members/{{user_id}}",
            methods=("PATCH",),
            endpoint=update_tenant_member_role,
            name="update_tenant_member_role",
            response_model=dict[str, Any],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/members/{{user_id}}",
            methods=("DELETE",),
            endpoint=remove_tenant_member,
            name="remove_tenant_member",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/members",
            methods=("GET",),
            endpoint=list_tenant_members,
            name="list_tenant_members",
            response_model=dict[str, Any],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/stats",
            methods=("GET",),
            endpoint=get_tenant_stats,
            name="get_tenant_stats",
            response_model=dict[str, Any],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/analytics",
            methods=("GET",),
            endpoint=get_tenant_analytics,
            name="get_tenant_analytics",
            response_model=dict[str, Any],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/gene-policies",
            methods=("GET",),
            endpoint=list_gene_policies,
            name="list_gene_policies",
            response_model=list[GenePolicyResponse],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/gene-policies/{{policy_key}}",
            methods=("PUT",),
            endpoint=upsert_gene_policy,
            name="upsert_gene_policy",
            response_model=GenePolicyResponse,
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/gene-policies/{{policy_key}}",
            methods=("DELETE",),
            endpoint=delete_gene_policy,
            name="delete_gene_policy",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/registries",
            methods=("GET",),
            endpoint=list_registries,
            name="list_registries",
            response_model=list[RegistryResponse],
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/registries",
            methods=("POST",),
            endpoint=create_registry,
            name="create_registry",
            status_code=status.HTTP_201_CREATED,
            response_model=RegistryResponse,
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/registries/{{registry_id}}",
            methods=("PUT",),
            endpoint=update_registry,
            name="update_registry",
            response_model=RegistryResponse,
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/registries/{{registry_id}}",
            methods=("DELETE",),
            endpoint=delete_registry,
            name="delete_registry",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _tenants_route_v2(
            path=f"{tenant_path}/registries/{{registry_id}}/test",
            methods=("POST",),
            endpoint=test_registry_connection,
            name="test_registry_connection",
            response_model=TestConnectionResponse,
        ),
    )


def builtin_tenants_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register tenants routes as reversible effects of one V2 Fiber."""
    definitions = tenants_route_definitions_v2()

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

        await context.effect(setup, label="builtin-tenants-http-routes")

    return PluginDefinitionV2(
        module_ref=TENANTS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(TENANTS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "TENANTS_HTTP_ROUTES_ENTRY_V2",
    "TENANTS_HTTP_ROUTES_MODULE_V2",
    "TENANTS_HTTP_ROUTES_ROW_V2",
    "builtin_tenants_http_routes_definition_v2",
    "tenants_route_definitions_v2",
]
