"""V2-owned production contributions for the tenant SMTP configuration HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import status

from src.application.schemas.smtp_schemas import SmtpConfigResponse
from src.infrastructure.adapters.primary.web.routers.smtp_config import (
    delete_smtp_config,
    get_smtp_config,
    test_smtp_config,
    upsert_smtp_config,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SMTP_CONFIG_HTTP_ROUTES_ENTRY_V2 = "builtin-smtp-config-http-routes"
SMTP_CONFIG_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/smtp-config-routes"
SMTP_CONFIG_HTTP_ROUTES_ROW_V2 = "smtp-config"


def smtp_config_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``smtp-config`` inventory row."""
    return (
        RouteDefinitionV2(
            owner_entry_id=SMTP_CONFIG_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/tenants/{tenant_id}/smtp-config",
            methods=("GET",),
            endpoint=get_smtp_config,
            name="get_smtp_config",
            tags=("smtp-config",),
            response_model=SmtpConfigResponse | None,
            replaces_builtin_row_id=SMTP_CONFIG_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=SMTP_CONFIG_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/tenants/{tenant_id}/smtp-config",
            methods=("PUT",),
            endpoint=upsert_smtp_config,
            name="upsert_smtp_config",
            tags=("smtp-config",),
            response_model=SmtpConfigResponse,
            replaces_builtin_row_id=SMTP_CONFIG_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=SMTP_CONFIG_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/tenants/{tenant_id}/smtp-config",
            methods=("DELETE",),
            endpoint=delete_smtp_config,
            name="delete_smtp_config",
            tags=("smtp-config",),
            status_code=status.HTTP_204_NO_CONTENT,
            replaces_builtin_row_id=SMTP_CONFIG_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=SMTP_CONFIG_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/tenants/{tenant_id}/smtp-config/test",
            methods=("POST",),
            endpoint=test_smtp_config,
            name="test_smtp_config",
            tags=("smtp-config",),
            status_code=status.HTTP_200_OK,
            response_model=dict[str, str],
            replaces_builtin_row_id=SMTP_CONFIG_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_smtp_config_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register tenant SMTP routes as reversible effects of one V2 Fiber."""
    definitions = smtp_config_route_definitions_v2()

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

        await context.effect(setup, label="builtin-smtp-config-http-routes")

    return PluginDefinitionV2(
        module_ref=SMTP_CONFIG_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SMTP_CONFIG_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "SMTP_CONFIG_HTTP_ROUTES_ENTRY_V2",
    "SMTP_CONFIG_HTTP_ROUTES_MODULE_V2",
    "SMTP_CONFIG_HTTP_ROUTES_ROW_V2",
    "builtin_smtp_config_http_routes_definition_v2",
    "smtp_config_route_definitions_v2",
]
