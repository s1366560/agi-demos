"""V2-owned production contributions for the builtin channels HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.routers import channels

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CHANNELS_HTTP_ROUTES_ENTRY_V2 = "builtin-channels-http-routes"
CHANNELS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/channels-routes"
CHANNELS_HTTP_ROUTES_ROW_V2 = "channels"
_CHANNELS_PREFIX_V2 = "/api/v1/channels"

type ChannelsRouteSpecV2 = tuple[
    Callable[..., Any],
    object | None,
    str,
    str,
    str | None,
    str | None,
]

_CHANNELS_ROUTE_SPECS_V2: tuple[ChannelsRouteSpecV2, ...] = (
    (
        channels.list_project_plugins,
        channels.RuntimePluginListResponse,
        "GET",
        "/projects/{project_id}/plugins",
        None,
        None,
    ),
    (
        channels.list_tenant_plugins,
        channels.RuntimePluginListResponse,
        "GET",
        "/tenants/{tenant_id}/plugins",
        None,
        None,
    ),
    (
        channels.get_tenant_plugin_config_schema,
        channels.PluginConfigSchemaResponse,
        "GET",
        "/tenants/{tenant_id}/plugins/{plugin_name}/config-schema",
        None,
        None,
    ),
    (
        channels.get_tenant_plugin_config,
        channels.PluginConfigResponse,
        "GET",
        "/tenants/{tenant_id}/plugins/{plugin_name}/config",
        None,
        None,
    ),
    (
        channels.update_tenant_plugin_config,
        channels.PluginConfigResponse,
        "PUT",
        "/tenants/{tenant_id}/plugins/{plugin_name}/config",
        None,
        None,
    ),
    (
        channels.list_tenant_channel_plugin_catalog,
        channels.ChannelPluginCatalogResponse,
        "GET",
        "/tenants/{tenant_id}/plugins/channel-catalog",
        None,
        None,
    ),
    (
        channels.get_tenant_channel_plugin_schema,
        channels.ChannelPluginConfigSchemaResponse,
        "GET",
        "/tenants/{tenant_id}/plugins/channel-catalog/{channel_type}/schema",
        None,
        None,
    ),
    (
        channels.install_tenant_plugin,
        channels.PluginActionResponse,
        "POST",
        "/tenants/{tenant_id}/plugins/install",
        None,
        None,
    ),
    (
        channels.enable_tenant_plugin,
        channels.PluginActionResponse,
        "POST",
        "/tenants/{tenant_id}/plugins/{plugin_name}/enable",
        None,
        None,
    ),
    (
        channels.disable_tenant_plugin,
        channels.PluginActionResponse,
        "POST",
        "/tenants/{tenant_id}/plugins/{plugin_name}/disable",
        None,
        None,
    ),
    (
        channels.uninstall_tenant_plugin,
        channels.PluginActionResponse,
        "POST",
        "/tenants/{tenant_id}/plugins/{plugin_name}/uninstall",
        None,
        None,
    ),
    (
        channels.reload_tenant_plugins,
        channels.PluginActionResponse,
        "POST",
        "/tenants/{tenant_id}/plugins/reload",
        None,
        None,
    ),
    (
        channels.list_project_channel_plugin_catalog,
        channels.ChannelPluginCatalogResponse,
        "GET",
        "/projects/{project_id}/plugins/channel-catalog",
        None,
        None,
    ),
    (
        channels.get_project_channel_plugin_schema,
        channels.ChannelPluginConfigSchemaResponse,
        "GET",
        "/projects/{project_id}/plugins/channel-catalog/{channel_type}/schema",
        None,
        None,
    ),
    (
        channels.install_project_plugin,
        channels.PluginActionResponse,
        "POST",
        "/projects/{project_id}/plugins/install",
        None,
        None,
    ),
    (
        channels.enable_project_plugin,
        channels.PluginActionResponse,
        "POST",
        "/projects/{project_id}/plugins/{plugin_name}/enable",
        None,
        None,
    ),
    (
        channels.disable_project_plugin,
        channels.PluginActionResponse,
        "POST",
        "/projects/{project_id}/plugins/{plugin_name}/disable",
        None,
        None,
    ),
    (
        channels.uninstall_project_plugin,
        channels.PluginActionResponse,
        "POST",
        "/projects/{project_id}/plugins/{plugin_name}/uninstall",
        None,
        None,
    ),
    (
        channels.reload_project_plugins,
        channels.PluginActionResponse,
        "POST",
        "/projects/{project_id}/plugins/reload",
        None,
        None,
    ),
    (
        channels.create_config,
        channels.ChannelConfigResponse,
        "POST",
        "/projects/{project_id}/configs",
        None,
        None,
    ),
    (
        channels.list_configs,
        channels.ChannelConfigList,
        "GET",
        "/projects/{project_id}/configs",
        None,
        None,
    ),
    (
        channels.get_config,
        channels.ChannelConfigResponse,
        "GET",
        "/configs/{config_id}",
        None,
        None,
    ),
    (
        channels.update_config,
        channels.ChannelConfigResponse,
        "PUT",
        "/configs/{config_id}",
        None,
        None,
    ),
    (channels.delete_config, None, "DELETE", "/configs/{config_id}", None, None),
    (channels.test_config, dict, "POST", "/configs/{config_id}/test", None, None),
    (
        channels.get_project_channel_observability_summary,
        channels.ChannelObservabilitySummaryResponse,
        "GET",
        "/projects/{project_id}/observability/summary",
        None,
        None,
    ),
    (
        channels.list_project_channel_outbox,
        channels.ChannelOutboxListResponse,
        "GET",
        "/projects/{project_id}/observability/outbox",
        None,
        None,
    ),
    (
        channels.list_project_channel_session_bindings,
        channels.ChannelSessionBindingListResponse,
        "GET",
        "/projects/{project_id}/observability/session-bindings",
        None,
        None,
    ),
    (
        channels.get_connection_status,
        channels.ChannelStatusResponse,
        "GET",
        "/configs/{config_id}/status",
        None,
        None,
    ),
    (
        channels.list_all_connection_status,
        list[channels.ChannelStatusResponse],
        "GET",
        "/status",
        None,
        None,
    ),
    (
        channels.push_message_to_channel,
        channels.PushMessageResponse,
        "POST",
        "/conversations/{conversation_id}/push",
        "Push message to channel",
        "Send an agent-initiated message to the channel bound to a conversation.",
    ),
)

_STATUS_CODES_V2: dict[Callable[..., Any], int] = {
    channels.create_config: 201,
    channels.delete_config: 204,
}


def _channels_route_v2(
    endpoint: Callable[..., Any],
    response_model: object | None,
    method: str,
    path: str,
    summary: str | None,
    description: str | None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=CHANNELS_HTTP_ROUTES_ENTRY_V2,
        path=f"{_CHANNELS_PREFIX_V2}{path}",
        methods=(method,),
        endpoint=endpoint,
        name=endpoint.__name__,
        tags=("channels",),
        summary=summary,
        description=description,
        status_code=_STATUS_CODES_V2.get(endpoint),
        response_model=response_model,
        replaces_builtin_row_id=CHANNELS_HTTP_ROUTES_ROW_V2,
    )


def channels_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``channels`` inventory row."""
    return tuple(_channels_route_v2(*spec) for spec in _CHANNELS_ROUTE_SPECS_V2)


def builtin_channels_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register channels routes as reversible effects of one V2 Fiber."""
    definitions = channels_route_definitions_v2()

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

        await context.effect(setup, label=CHANNELS_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=CHANNELS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(CHANNELS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "CHANNELS_HTTP_ROUTES_ENTRY_V2",
    "CHANNELS_HTTP_ROUTES_MODULE_V2",
    "CHANNELS_HTTP_ROUTES_ROW_V2",
    "builtin_channels_http_routes_definition_v2",
    "channels_route_definitions_v2",
]
