"""V2-owned production contributions for the builtin instance-channels HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import status

from src.infrastructure.adapters.primary.web.routers.instance_channels import (
    create_channel,
    delete_channel,
    list_channels,
    test_channel_connection,
    update_channel,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

INSTANCE_CHANNELS_HTTP_ROUTES_ENTRY_V2 = "builtin-instance-channels-http-routes"
INSTANCE_CHANNELS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/instance-channels-routes"
INSTANCE_CHANNELS_HTTP_ROUTES_ROW_V2 = "instance-channels"
_INSTANCE_CHANNELS_PREFIX_V2 = "/api/v1/instances/{instance_id}/channels"


def _instance_channel_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=INSTANCE_CHANNELS_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("Instance Channels",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=INSTANCE_CHANNELS_HTTP_ROUTES_ROW_V2,
    )


def instance_channel_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``instance-channels`` inventory row."""
    prefix = _INSTANCE_CHANNELS_PREFIX_V2
    return (
        _instance_channel_route_v2(
            path=prefix,
            methods=("GET",),
            endpoint=list_channels,
            name="list_channels",
            response_model=dict[str, Any],
        ),
        _instance_channel_route_v2(
            path=prefix,
            methods=("POST",),
            endpoint=create_channel,
            name="create_channel",
            response_model=dict[str, Any],
            status_code=status.HTTP_201_CREATED,
        ),
        _instance_channel_route_v2(
            path=f"{prefix}/{{channel_id}}",
            methods=("PUT",),
            endpoint=update_channel,
            name="update_channel",
            response_model=dict[str, Any],
        ),
        _instance_channel_route_v2(
            path=f"{prefix}/{{channel_id}}",
            methods=("DELETE",),
            endpoint=delete_channel,
            name="delete_channel",
            response_model=None,
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _instance_channel_route_v2(
            path=f"{prefix}/{{channel_id}}/test",
            methods=("POST",),
            endpoint=test_channel_connection,
            name="test_channel_connection",
            response_model=dict[str, str],
        ),
    )


def builtin_instance_channels_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register instance-channel routes as reversible effects of one V2 Fiber."""
    definitions = instance_channel_route_definitions_v2()

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

        await context.effect(setup, label=INSTANCE_CHANNELS_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=INSTANCE_CHANNELS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(INSTANCE_CHANNELS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "INSTANCE_CHANNELS_HTTP_ROUTES_ENTRY_V2",
    "INSTANCE_CHANNELS_HTTP_ROUTES_MODULE_V2",
    "INSTANCE_CHANNELS_HTTP_ROUTES_ROW_V2",
    "builtin_instance_channels_http_routes_definition_v2",
    "instance_channel_route_definitions_v2",
]
