"""V2-owned production contributions for the builtin LLM providers HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.domain.llm_providers.models import (
    ProviderConfigResponse,
    ProviderHealth,
    ProviderTypeDescriptor,
    ProviderValidationResponse,
    TenantProviderMapping,
)
from src.infrastructure.adapters.primary.web.routers.llm_providers import (
    assign_provider_to_tenant,
    check_provider_health,
    create_provider,
    delete_provider,
    detect_env_providers,
    get_provider,
    get_provider_health,
    get_provider_usage,
    get_system_resilience_status,
    get_tenant_provider,
    list_catalog_models,
    list_models_for_provider_type,
    list_provider_types,
    list_providers,
    list_tenant_assignments,
    refresh_catalog_models,
    reset_circuit_breaker,
    search_catalog_models,
    test_provider_connection,
    unassign_provider_from_tenant,
    update_provider,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

LLM_PROVIDERS_HTTP_ROUTES_ENTRY_V2 = "builtin-llm-providers-http-routes"
LLM_PROVIDERS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/llm-providers-routes"
LLM_PROVIDERS_HTTP_ROUTES_ROW_V2 = "llm-providers"
_LLM_PROVIDERS_PREFIX_V2 = "/api/v1/llm-providers"


def _llm_providers_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=LLM_PROVIDERS_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("LLM Providers",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=LLM_PROVIDERS_HTTP_ROUTES_ROW_V2,
    )


def llm_providers_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``llm-providers`` inventory row."""
    prefix = _LLM_PROVIDERS_PREFIX_V2
    mapping: tuple[
        tuple[str, tuple[str, ...], Callable[..., Any], str, object | None, int | None],
        ...,
    ] = (
        (
            f"{prefix}/",
            ("POST",),
            create_provider,
            "create_provider",
            ProviderConfigResponse,
            201,
        ),
        (
            f"{prefix}/",
            ("GET",),
            list_providers,
            "list_providers",
            list[ProviderConfigResponse],
            None,
        ),
        (
            f"{prefix}/types",
            ("GET",),
            list_provider_types,
            "list_provider_types",
            list[ProviderTypeDescriptor],
            None,
        ),
        (
            f"{prefix}/models/catalog",
            ("GET",),
            list_catalog_models,
            "list_catalog_models",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/models/catalog/search",
            ("GET",),
            search_catalog_models,
            "search_catalog_models",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/models/catalog/refresh",
            ("POST",),
            refresh_catalog_models,
            "refresh_catalog_models",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/models/{{provider_type}}",
            ("GET",),
            list_models_for_provider_type,
            "list_models_for_provider_type",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/env-detection",
            ("GET",),
            detect_env_providers,
            "detect_env_providers",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/{{provider_id}}",
            ("GET",),
            get_provider,
            "get_provider",
            ProviderConfigResponse,
            None,
        ),
        (
            f"{prefix}/{{provider_id}}",
            ("PUT",),
            update_provider,
            "update_provider",
            ProviderConfigResponse,
            None,
        ),
        (
            f"{prefix}/{{provider_id}}",
            ("DELETE",),
            delete_provider,
            "delete_provider",
            None,
            204,
        ),
        (
            f"{prefix}/test-connection",
            ("POST",),
            test_provider_connection,
            "test_provider_connection",
            ProviderValidationResponse,
            None,
        ),
        (
            f"{prefix}/{{provider_id}}/health-check",
            ("POST",),
            check_provider_health,
            "check_provider_health",
            ProviderValidationResponse,
            None,
        ),
        (
            f"{prefix}/{{provider_id}}/health",
            ("GET",),
            get_provider_health,
            "get_provider_health",
            ProviderHealth,
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/assignments",
            ("GET",),
            list_tenant_assignments,
            "list_tenant_assignments",
            list[TenantProviderMapping],
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/providers/{{provider_id}}",
            ("POST",),
            assign_provider_to_tenant,
            "assign_provider_to_tenant",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/provider",
            ("GET",),
            get_tenant_provider,
            "get_tenant_provider",
            ProviderConfigResponse,
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/providers/{{provider_id}}",
            ("DELETE",),
            unassign_provider_from_tenant,
            "unassign_provider_from_tenant",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/{{provider_id}}/usage",
            ("GET",),
            get_provider_usage,
            "get_provider_usage",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/system/status",
            ("GET",),
            get_system_resilience_status,
            "get_system_resilience_status",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/system/reset-circuit-breaker/{{provider_type}}",
            ("POST",),
            reset_circuit_breaker,
            "reset_circuit_breaker",
            dict[str, Any],
            None,
        ),
    )
    return tuple(
        _llm_providers_route_v2(
            path=path,
            methods=methods,
            endpoint=endpoint,
            name=name,
            response_model=response_model,
            status_code=status_code,
        )
        for path, methods, endpoint, name, response_model, status_code in mapping
    )


def builtin_llm_providers_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register LLM provider routes as reversible effects of one V2 Fiber."""
    definitions = llm_providers_route_definitions_v2()

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

        await context.effect(setup, label=LLM_PROVIDERS_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=LLM_PROVIDERS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(LLM_PROVIDERS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "LLM_PROVIDERS_HTTP_ROUTES_ENTRY_V2",
    "LLM_PROVIDERS_HTTP_ROUTES_MODULE_V2",
    "LLM_PROVIDERS_HTTP_ROUTES_ROW_V2",
    "builtin_llm_providers_http_routes_definition_v2",
    "llm_providers_route_definitions_v2",
]
