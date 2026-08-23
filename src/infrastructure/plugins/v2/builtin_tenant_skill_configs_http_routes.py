"""V2-owned production contributions for the builtin tenant skill-config HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import status

from src.infrastructure.adapters.primary.web.routers.tenant_skill_configs import (
    TenantSkillConfigListResponse,
    TenantSkillConfigResponse,
    delete_tenant_skill_config,
    disable_system_skill,
    enable_system_skill,
    get_skill_status,
    get_tenant_skill_config,
    list_tenant_skill_configs,
    override_system_skill,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

TENANT_SKILL_CONFIGS_HTTP_ROUTES_ENTRY_V2 = "builtin-tenant-skill-configs-http-routes"
TENANT_SKILL_CONFIGS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/tenant-skill-configs-routes"
TENANT_SKILL_CONFIGS_HTTP_ROUTES_ROW_V2 = "tenant-skill-configs"
_TENANT_SKILL_CONFIGS_PREFIX_V2 = "/api/v1/tenant/skills/config"


def _tenant_skill_config_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=TENANT_SKILL_CONFIGS_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("Tenant Skill Config",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=TENANT_SKILL_CONFIGS_HTTP_ROUTES_ROW_V2,
    )


def tenant_skill_config_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``tenant-skill-configs`` inventory row."""
    prefix = _TENANT_SKILL_CONFIGS_PREFIX_V2
    return (
        _tenant_skill_config_route_v2(
            path=f"{prefix}/",
            methods=("GET",),
            endpoint=list_tenant_skill_configs,
            name="list_tenant_skill_configs",
            response_model=TenantSkillConfigListResponse,
        ),
        _tenant_skill_config_route_v2(
            path=f"{prefix}/{{system_skill_name}}",
            methods=("GET",),
            endpoint=get_tenant_skill_config,
            name="get_tenant_skill_config",
            response_model=TenantSkillConfigResponse,
        ),
        _tenant_skill_config_route_v2(
            path=f"{prefix}/disable",
            methods=("POST",),
            endpoint=disable_system_skill,
            name="disable_system_skill",
            response_model=TenantSkillConfigResponse,
            status_code=status.HTTP_201_CREATED,
        ),
        _tenant_skill_config_route_v2(
            path=f"{prefix}/override",
            methods=("POST",),
            endpoint=override_system_skill,
            name="override_system_skill",
            response_model=TenantSkillConfigResponse,
            status_code=status.HTTP_201_CREATED,
        ),
        _tenant_skill_config_route_v2(
            path=f"{prefix}/enable",
            methods=("POST",),
            endpoint=enable_system_skill,
            name="enable_system_skill",
            response_model=None,
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _tenant_skill_config_route_v2(
            path=f"{prefix}/{{system_skill_name}}",
            methods=("DELETE",),
            endpoint=delete_tenant_skill_config,
            name="delete_tenant_skill_config",
            response_model=None,
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _tenant_skill_config_route_v2(
            path=f"{prefix}/status/{{system_skill_name}}",
            methods=("GET",),
            endpoint=get_skill_status,
            name="get_skill_status",
            response_model=dict[str, Any],
        ),
    )


def builtin_tenant_skill_configs_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register tenant skill-config routes as reversible effects of one V2 Fiber."""
    definitions = tenant_skill_config_route_definitions_v2()

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

        await context.effect(setup, label=TENANT_SKILL_CONFIGS_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=TENANT_SKILL_CONFIGS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(TENANT_SKILL_CONFIGS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "TENANT_SKILL_CONFIGS_HTTP_ROUTES_ENTRY_V2",
    "TENANT_SKILL_CONFIGS_HTTP_ROUTES_MODULE_V2",
    "TENANT_SKILL_CONFIGS_HTTP_ROUTES_ROW_V2",
    "builtin_tenant_skill_configs_http_routes_definition_v2",
    "tenant_skill_config_route_definitions_v2",
]
