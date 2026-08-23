"""V2-owned project sandbox HTTP and WebSocket route contributions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.routers.project_sandbox import (
    CleanupStaleResponse,
    ExecuteToolResponse,
    HealthCheckResponse,
    HttpServiceActionResponse,
    HttpServicePreviewSessionResponse,
    HttpServiceResponse,
    ListHttpServicesResponse,
    ListProjectSandboxesResponse,
    ProjectSandboxResponse,
    SandboxActionResponse,
    SandboxProxyAuthCookieResponse,
    SandboxStatsResponse,
    check_project_sandbox_health,
    cleanup_stale_sandboxes,
    create_project_http_service_preview_session,
    create_project_sandbox_desktop_session,
    download_project_sandbox_file,
    ensure_project_sandbox,
    execute_tool_in_project_sandbox,
    get_project_sandbox,
    get_project_sandbox_runtime_capabilities,
    get_project_sandbox_stats,
    list_project_http_services,
    list_project_sandbox_files,
    list_project_sandboxes,
    proxy_project_desktop,
    proxy_project_desktop_websocket,
    proxy_project_http_service,
    proxy_project_http_service_preview_host,
    proxy_project_http_service_preview_host_websocket,
    proxy_project_http_service_websocket,
    proxy_project_mcp_websocket,
    proxy_project_terminal_websocket,
    read_project_sandbox_file,
    register_project_http_service,
    restart_project_sandbox,
    seed_project_sandbox_proxy_auth_cookie,
    start_project_desktop,
    start_project_terminal,
    stop_project_desktop,
    stop_project_http_service,
    stop_project_terminal,
    sync_project_sandbox_status,
    terminate_project_sandbox,
)

from .http_routes import (
    RouteContributionV2,
    RouteDefinitionV2,
    RouteTableBuilderV2,
    WebSocketRouteDefinitionV2,
)
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .sandbox_http_service_registry import SandboxHttpServiceRegistryProtocolV2

PROJECT_SANDBOX_HTTP_ROUTES_ENTRY_V2 = "builtin-project-sandbox-http-routes"
PROJECT_SANDBOX_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/project-sandbox-routes"
PROJECT_SANDBOX_HTTP_ROUTES_ROW_V2 = "project-sandbox"
PROJECT_SANDBOX_PREVIEW_HTTP_ROUTES_ROW_V2 = "project-sandbox-preview"
PROJECT_SANDBOX_HTTP_SERVICE_REGISTRY_INJECT_V2 = "http_service_registry"
_PROJECT_SANDBOX_TAGS_V2 = ("project-sandbox",)
_PROJECT_SANDBOX_PREVIEW_TAGS_V2 = ("project-sandbox-preview",)
_PROXY_HTTP_METHODS_V2 = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


def _http_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    row_id: str = PROJECT_SANDBOX_HTTP_ROUTES_ROW_V2,
    tags: tuple[str, ...] = _PROJECT_SANDBOX_TAGS_V2,
    include_in_schema: bool = True,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=PROJECT_SANDBOX_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=tags,
        response_model=response_model,
        include_in_schema=include_in_schema,
        replaces_builtin_row_id=row_id,
    )


def _websocket_route_v2(
    *,
    path: str,
    endpoint: Callable[..., Any],
    name: str,
    row_id: str = PROJECT_SANDBOX_HTTP_ROUTES_ROW_V2,
) -> WebSocketRouteDefinitionV2:
    return WebSocketRouteDefinitionV2(
        owner_entry_id=PROJECT_SANDBOX_HTTP_ROUTES_ENTRY_V2,
        path=path,
        endpoint=endpoint,
        name=name,
        replaces_builtin_row_id=row_id,
    )


def project_sandbox_route_definitions_v2() -> tuple[RouteContributionV2, ...]:
    """Return the complete project sandbox and preview inventory rows."""
    prefix = "/api/v1/projects"
    project = f"{prefix}/{{project_id}}/sandbox"
    services = f"{project}/http-services"
    return (
        _http_route_v2(
            path=f"{project}/capabilities",
            methods=("GET",),
            endpoint=get_project_sandbox_runtime_capabilities,
            name="get_project_sandbox_runtime_capabilities",
            response_model=dict[str, Any],
        ),
        _http_route_v2(
            path=f"{project}/files",
            methods=("GET",),
            endpoint=list_project_sandbox_files,
            name="list_project_sandbox_files",
            response_model=dict[str, Any],
        ),
        _http_route_v2(
            path=f"{project}/files/content",
            methods=("GET",),
            endpoint=read_project_sandbox_file,
            name="read_project_sandbox_file",
            response_model=dict[str, Any],
        ),
        _http_route_v2(
            path=f"{project}/files/download",
            methods=("GET",),
            endpoint=download_project_sandbox_file,
            name="download_project_sandbox_file",
            response_model=None,
        ),
        _http_route_v2(
            path=f"{project}/desktop/session",
            methods=("POST",),
            endpoint=create_project_sandbox_desktop_session,
            name="create_project_sandbox_desktop_session",
            response_model=dict[str, Any],
        ),
        _http_route_v2(
            path=project,
            methods=("GET",),
            endpoint=get_project_sandbox,
            name="get_project_sandbox",
            response_model=ProjectSandboxResponse,
        ),
        _http_route_v2(
            path=f"{project}/proxy-auth-cookie",
            methods=("POST",),
            endpoint=seed_project_sandbox_proxy_auth_cookie,
            name="seed_project_sandbox_proxy_auth_cookie",
            response_model=SandboxProxyAuthCookieResponse,
        ),
        _http_route_v2(
            path=project,
            methods=("POST",),
            endpoint=ensure_project_sandbox,
            name="ensure_project_sandbox",
            response_model=ProjectSandboxResponse,
        ),
        _http_route_v2(
            path=f"{project}/health",
            methods=("GET",),
            endpoint=check_project_sandbox_health,
            name="check_project_sandbox_health",
            response_model=HealthCheckResponse,
        ),
        _http_route_v2(
            path=f"{project}/stats",
            methods=("GET",),
            endpoint=get_project_sandbox_stats,
            name="get_project_sandbox_stats",
            response_model=SandboxStatsResponse,
        ),
        _http_route_v2(
            path=f"{project}/execute",
            methods=("POST",),
            endpoint=execute_tool_in_project_sandbox,
            name="execute_tool_in_project_sandbox",
            response_model=ExecuteToolResponse,
        ),
        _http_route_v2(
            path=f"{project}/restart",
            methods=("POST",),
            endpoint=restart_project_sandbox,
            name="restart_project_sandbox",
            response_model=SandboxActionResponse,
        ),
        _http_route_v2(
            path=project,
            methods=("DELETE",),
            endpoint=terminate_project_sandbox,
            name="terminate_project_sandbox",
            response_model=SandboxActionResponse,
        ),
        _http_route_v2(
            path=f"{project}/sync",
            methods=("GET",),
            endpoint=sync_project_sandbox_status,
            name="sync_project_sandbox_status",
            response_model=ProjectSandboxResponse,
        ),
        _http_route_v2(
            path=f"{prefix}/sandboxes",
            methods=("GET",),
            endpoint=list_project_sandboxes,
            name="list_project_sandboxes",
            response_model=ListProjectSandboxesResponse,
        ),
        _http_route_v2(
            path=f"{prefix}/sandboxes/cleanup",
            methods=("POST",),
            endpoint=cleanup_stale_sandboxes,
            name="cleanup_stale_sandboxes",
            response_model=CleanupStaleResponse,
        ),
        _http_route_v2(
            path=f"{project}/desktop",
            methods=("POST",),
            endpoint=start_project_desktop,
            name="start_project_desktop",
            response_model=dict[str, Any],
        ),
        _http_route_v2(
            path=f"{project}/desktop",
            methods=("DELETE",),
            endpoint=stop_project_desktop,
            name="stop_project_desktop",
            response_model=dict[str, Any],
        ),
        _http_route_v2(
            path=f"{project}/terminal",
            methods=("POST",),
            endpoint=start_project_terminal,
            name="start_project_terminal",
            response_model=dict[str, Any],
        ),
        _http_route_v2(
            path=f"{project}/terminal",
            methods=("DELETE",),
            endpoint=stop_project_terminal,
            name="stop_project_terminal",
            response_model=dict[str, Any],
        ),
        _http_route_v2(
            path=services,
            methods=("POST",),
            endpoint=register_project_http_service,
            name="register_project_http_service",
            response_model=HttpServiceResponse,
        ),
        _http_route_v2(
            path=services,
            methods=("GET",),
            endpoint=list_project_http_services,
            name="list_project_http_services",
            response_model=ListHttpServicesResponse,
        ),
        _http_route_v2(
            path=f"{services}/{{service_id}}/preview-session",
            methods=("POST",),
            endpoint=create_project_http_service_preview_session,
            name="create_project_http_service_preview_session",
            response_model=HttpServicePreviewSessionResponse,
        ),
        _http_route_v2(
            path=f"{services}/{{service_id}}",
            methods=("DELETE",),
            endpoint=stop_project_http_service,
            name="stop_project_http_service",
            response_model=HttpServiceActionResponse,
        ),
        _http_route_v2(
            path=f"{services}/{{service_id}}/proxy/{{path:path}}",
            methods=_PROXY_HTTP_METHODS_V2,
            endpoint=proxy_project_http_service,
            name="proxy_project_http_service",
            response_model=Any,
            include_in_schema=False,
        ),
        _http_route_v2(
            path=f"{services}/{{service_id}}/proxy",
            methods=_PROXY_HTTP_METHODS_V2,
            endpoint=proxy_project_http_service,
            name="proxy_project_http_service",
            response_model=Any,
            include_in_schema=False,
        ),
        _websocket_route_v2(
            path=f"{services}/{{service_id}}/proxy/ws/{{path:path}}",
            endpoint=proxy_project_http_service_websocket,
            name="proxy_project_http_service_websocket",
        ),
        _websocket_route_v2(
            path=f"{services}/{{service_id}}/proxy/ws",
            endpoint=proxy_project_http_service_websocket,
            name="proxy_project_http_service_websocket",
        ),
        _http_route_v2(
            path=f"{project}/desktop/proxy/{{path:path}}",
            methods=("GET",),
            endpoint=proxy_project_desktop,
            name="proxy_project_desktop",
            response_model=Any,
        ),
        _websocket_route_v2(
            path=f"{project}/desktop/proxy/websockify",
            endpoint=proxy_project_desktop_websocket,
            name="proxy_project_desktop_websocket",
        ),
        _websocket_route_v2(
            path=f"{project}/terminal/proxy/ws",
            endpoint=proxy_project_terminal_websocket,
            name="proxy_project_terminal_websocket",
        ),
        _websocket_route_v2(
            path=f"{project}/mcp/proxy",
            endpoint=proxy_project_mcp_websocket,
            name="proxy_project_mcp_websocket",
        ),
        _http_route_v2(
            path="/{path:path}",
            methods=_PROXY_HTTP_METHODS_V2,
            endpoint=proxy_project_http_service_preview_host,
            name="proxy_project_http_service_preview_host",
            response_model=Any,
            row_id=PROJECT_SANDBOX_PREVIEW_HTTP_ROUTES_ROW_V2,
            tags=_PROJECT_SANDBOX_PREVIEW_TAGS_V2,
            include_in_schema=False,
        ),
        _websocket_route_v2(
            path="/{path:path}",
            endpoint=proxy_project_http_service_preview_host_websocket,
            name="proxy_project_http_service_preview_host_websocket",
            row_id=PROJECT_SANDBOX_PREVIEW_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_project_sandbox_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register both sandbox route rows as one reversible V2 Consumer Fiber."""

    async def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        builder = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
        if not isinstance(builder, RouteTableBuilderV2):
            raise RuntimeV2Error(
                "invalid_route_table_builder",
                "route_table inject is not a protocol v2 route table builder",
            )
        registry = context.require(PROJECT_SANDBOX_HTTP_SERVICE_REGISTRY_INJECT_V2)
        if not isinstance(registry, SandboxHttpServiceRegistryProtocolV2):
            raise RuntimeV2Error(
                "invalid_sandbox_http_service_registry",
                "http_service_registry inject is not a sandbox HTTP service registry",
            )
        definitions = project_sandbox_route_definitions_v2()

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

        await context.effect(setup, label=PROJECT_SANDBOX_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=PROJECT_SANDBOX_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(PROJECT_SANDBOX_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "PROJECT_SANDBOX_HTTP_ROUTES_ENTRY_V2",
    "PROJECT_SANDBOX_HTTP_ROUTES_MODULE_V2",
    "PROJECT_SANDBOX_HTTP_ROUTES_ROW_V2",
    "PROJECT_SANDBOX_HTTP_SERVICE_REGISTRY_INJECT_V2",
    "PROJECT_SANDBOX_PREVIEW_HTTP_ROUTES_ROW_V2",
    "builtin_project_sandbox_http_routes_definition_v2",
    "project_sandbox_route_definitions_v2",
]
