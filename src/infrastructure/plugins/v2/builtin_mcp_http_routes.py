"""V2-owned production contribution for the MCP HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.mcp_application_authority_v2 import (
    mcp_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.mcp import (
    create_mcp_server_root,
    list_mcp_servers_root,
)
from src.infrastructure.adapters.primary.web.routers.mcp.apps import (
    MCPResourceListResponse,
    MCPResourceReadResponse,
    delete_mcp_app,
    get_mcp_app,
    get_mcp_app_resource,
    list_mcp_apps,
    proxy_resource_list,
    proxy_resource_read,
    proxy_tool_call,
    proxy_tool_call_direct,
    refresh_mcp_app_resource,
)
from src.infrastructure.adapters.primary.web.routers.mcp.schemas import (
    MCPAppResourceResponse,
    MCPAppResponse,
    MCPAppToolCallResponse,
    MCPHealthSummary,
    MCPReconcileResultResponse,
    MCPServerHealthStatus,
    MCPServerResponse,
    MCPServerTestResult,
    MCPToolCallResponse,
    MCPToolListResponse,
)
from src.infrastructure.adapters.primary.web.routers.mcp.servers import (
    create_mcp_server,
    delete_mcp_server,
    get_mcp_health_summary,
    get_mcp_server,
    get_mcp_server_health,
    list_mcp_server_logs,
    list_mcp_server_prompts,
    list_mcp_servers,
    reconcile_mcp_project,
    set_mcp_server_log_level,
    sync_mcp_server_tools,
    test_mcp_server_connection,
    update_mcp_server,
)
from src.infrastructure.adapters.primary.web.routers.mcp.tools import (
    call_mcp_tool,
    list_all_mcp_tools,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

MCP_HTTP_ROUTES_ENTRY_V2 = "builtin-mcp-http-routes"
MCP_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/mcp-routes"
MCP_HTTP_ROUTES_ROW_V2 = "mcp"
_MCP_SERVER_TAGS_V2 = ("MCP Servers",)
_MCP_APP_TAGS_V2 = ("MCP Servers", "MCP Apps")


def _mcp_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    tags: tuple[str, ...] = _MCP_SERVER_TAGS_V2,
    status_code: int | None = None,
    include_in_schema: bool = True,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=MCP_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=tags,
        status_code=status_code,
        response_model=response_model,
        include_in_schema=include_in_schema,
        replaces_builtin_row_id=MCP_HTTP_ROUTES_ROW_V2,
    )


def mcp_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return all 26 routes explicitly claimed from the ``mcp`` inventory row."""
    prefix = "/api/v1/mcp"
    apps_prefix = f"{prefix}/apps"
    return (
        _mcp_route_v2(
            path=apps_prefix,
            methods=("GET",),
            endpoint=list_mcp_apps,
            name="list_mcp_apps",
            tags=_MCP_APP_TAGS_V2,
            response_model=list[MCPAppResponse],
        ),
        _mcp_route_v2(
            path=f"{apps_prefix}/proxy/tool-call",
            methods=("POST",),
            endpoint=proxy_tool_call_direct,
            name="proxy_tool_call_direct",
            tags=_MCP_APP_TAGS_V2,
            response_model=MCPAppToolCallResponse,
        ),
        _mcp_route_v2(
            path=f"{apps_prefix}/{{app_id}}",
            methods=("GET",),
            endpoint=get_mcp_app,
            name="get_mcp_app",
            tags=_MCP_APP_TAGS_V2,
            response_model=MCPAppResponse,
        ),
        _mcp_route_v2(
            path=f"{apps_prefix}/{{app_id}}/resource",
            methods=("GET",),
            endpoint=get_mcp_app_resource,
            name="get_mcp_app_resource",
            tags=_MCP_APP_TAGS_V2,
            response_model=MCPAppResourceResponse,
        ),
        _mcp_route_v2(
            path=f"{apps_prefix}/{{app_id}}/tool-call",
            methods=("POST",),
            endpoint=proxy_tool_call,
            name="proxy_tool_call",
            tags=_MCP_APP_TAGS_V2,
            response_model=MCPAppToolCallResponse,
        ),
        _mcp_route_v2(
            path=f"{apps_prefix}/{{app_id}}",
            methods=("DELETE",),
            endpoint=delete_mcp_app,
            name="delete_mcp_app",
            tags=_MCP_APP_TAGS_V2,
            response_model=dict[str, Any],
        ),
        _mcp_route_v2(
            path=f"{apps_prefix}/{{app_id}}/refresh",
            methods=("POST",),
            endpoint=refresh_mcp_app_resource,
            name="refresh_mcp_app_resource",
            tags=_MCP_APP_TAGS_V2,
            response_model=MCPAppResponse,
        ),
        _mcp_route_v2(
            path=f"{apps_prefix}/resources/read",
            methods=("POST",),
            endpoint=proxy_resource_read,
            name="proxy_resource_read",
            tags=_MCP_APP_TAGS_V2,
            response_model=MCPResourceReadResponse,
        ),
        _mcp_route_v2(
            path=f"{apps_prefix}/resources/list",
            methods=("POST",),
            endpoint=proxy_resource_list,
            name="proxy_resource_list",
            tags=_MCP_APP_TAGS_V2,
            response_model=MCPResourceListResponse,
        ),
        _mcp_route_v2(
            path=f"{prefix}/create",
            methods=("POST",),
            endpoint=create_mcp_server,
            name="create_mcp_server",
            status_code=201,
            response_model=MCPServerResponse,
        ),
        _mcp_route_v2(
            path=f"{prefix}/list",
            methods=("GET",),
            endpoint=list_mcp_servers,
            name="list_mcp_servers",
            response_model=list[MCPServerResponse],
        ),
        _mcp_route_v2(
            path=f"{prefix}/{{server_id}}",
            methods=("GET",),
            endpoint=get_mcp_server,
            name="get_mcp_server",
            response_model=MCPServerResponse,
        ),
        _mcp_route_v2(
            path=f"{prefix}/{{server_id}}",
            methods=("PUT",),
            endpoint=update_mcp_server,
            name="update_mcp_server",
            response_model=MCPServerResponse,
        ),
        _mcp_route_v2(
            path=f"{prefix}/{{server_id}}",
            methods=("DELETE",),
            endpoint=delete_mcp_server,
            name="delete_mcp_server",
            status_code=204,
            response_model=None,
        ),
        _mcp_route_v2(
            path=f"{prefix}/{{server_id}}/sync",
            methods=("POST",),
            endpoint=sync_mcp_server_tools,
            name="sync_mcp_server_tools",
            response_model=MCPServerResponse,
        ),
        _mcp_route_v2(
            path=f"{prefix}/{{server_id}}/test",
            methods=("POST",),
            endpoint=test_mcp_server_connection,
            name="test_mcp_server_connection",
            response_model=MCPServerTestResult,
        ),
        _mcp_route_v2(
            path=f"{prefix}/reconcile/{{project_id}}",
            methods=("POST",),
            endpoint=reconcile_mcp_project,
            name="reconcile_mcp_project",
            response_model=MCPReconcileResultResponse,
        ),
        _mcp_route_v2(
            path=f"{prefix}/health/summary",
            methods=("GET",),
            endpoint=get_mcp_health_summary,
            name="get_mcp_health_summary",
            response_model=MCPHealthSummary,
        ),
        _mcp_route_v2(
            path=f"{prefix}/{{server_id}}/health",
            methods=("GET",),
            endpoint=get_mcp_server_health,
            name="get_mcp_server_health",
            response_model=MCPServerHealthStatus,
        ),
        _mcp_route_v2(
            path=f"{prefix}/{{server_id}}/prompts",
            methods=("GET",),
            endpoint=list_mcp_server_prompts,
            name="list_mcp_server_prompts",
            response_model=dict[str, list[dict[str, Any]]],
        ),
        _mcp_route_v2(
            path=f"{prefix}/{{server_id}}/log-level",
            methods=("POST",),
            endpoint=set_mcp_server_log_level,
            name="set_mcp_server_log_level",
            response_model=dict[str, Any],
        ),
        _mcp_route_v2(
            path=f"{prefix}/{{server_id}}/logs",
            methods=("GET",),
            endpoint=list_mcp_server_logs,
            name="list_mcp_server_logs",
            response_model=dict[str, list[dict[str, Any]]],
        ),
        _mcp_route_v2(
            path=f"{prefix}/tools/all",
            methods=("GET",),
            endpoint=list_all_mcp_tools,
            name="list_all_mcp_tools",
            response_model=MCPToolListResponse,
        ),
        _mcp_route_v2(
            path=f"{prefix}/tools/call",
            methods=("POST",),
            endpoint=call_mcp_tool,
            name="call_mcp_tool",
            response_model=MCPToolCallResponse,
        ),
        _mcp_route_v2(
            path=prefix,
            methods=("POST",),
            endpoint=create_mcp_server_root,
            name="create_mcp_server_root",
            response_model=MCPServerResponse,
            include_in_schema=False,
        ),
        _mcp_route_v2(
            path=prefix,
            methods=("GET",),
            endpoint=list_mcp_servers_root,
            name="list_mcp_servers_root",
            response_model=list[MCPServerResponse],
            include_in_schema=False,
        ),
    )


def builtin_mcp_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the MCP row as one reversible V2 effect."""
    definitions = mcp_route_definitions_v2()

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

        await context.effect(setup, label=MCP_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=MCP_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(MCP_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "MCP_HTTP_ROUTES_ENTRY_V2",
    "MCP_HTTP_ROUTES_MODULE_V2",
    "MCP_HTTP_ROUTES_ROW_V2",
    "builtin_mcp_http_routes_definition_v2",
    "mcp_application_authority_dependency_v2",
    "mcp_route_definitions_v2",
]
