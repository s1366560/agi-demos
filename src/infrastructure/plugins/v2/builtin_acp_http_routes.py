"""V2-owned production contributions for the builtin ACP HTTP/WebSocket row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.application.schemas.acp_runner_schemas import (
    ACPRunnerInstanceResponse,
    ACPRunnerPoolResponse,
)
from src.infrastructure.acp.client import (
    ExternalACPAgentSummary,
    ExternalACPPromptResult,
    ExternalACPSessionResult,
    ExternalACPSessionSummary,
)
from src.infrastructure.adapters.primary.web.routers.acp import (
    ExternalACPAckResponse,
    TenantACPStatusResponse,
    TenantExternalACPAgentResponse,
    TenantExternalACPTestResponse,
    acp_runner_connect_endpoint,
    acp_websocket_endpoint,
    cancel_external_agent_session,
    cancel_tenant_external_agent_session,
    close_external_agent_session,
    close_tenant_external_agent_session,
    create_external_agent_session,
    create_tenant_external_agent,
    create_tenant_external_agent_session,
    delete_tenant_external_agent,
    get_tenant_acp_status,
    get_tenant_external_agent,
    list_external_agents,
    list_tenant_acp_runner_instances,
    list_tenant_acp_runner_pools,
    list_tenant_external_agent_sessions,
    list_tenant_external_agents,
    prompt_external_agent_session,
    prompt_tenant_external_agent_session,
    test_tenant_external_agent,
    update_tenant_external_agent,
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

ACP_HTTP_ROUTES_ENTRY_V2 = "builtin-acp-http-routes"
ACP_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/acp-routes"
ACP_HTTP_ROUTES_ROW_V2 = "acp"
_ACP_PREFIX_V2 = "/api/v1/acp"


def _acp_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=ACP_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("acp",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=ACP_HTTP_ROUTES_ROW_V2,
    )


def acp_route_definitions_v2() -> tuple[RouteContributionV2, ...]:
    """Return the complete, explicitly claimed ``acp`` inventory row."""
    prefix = _ACP_PREFIX_V2
    tenant_external_agent_sessions = (
        f"{prefix}/tenants/{{tenant_id}}/external-agents/{{agent_key}}/sessions"
    )
    websocket_definitions: tuple[RouteContributionV2, ...] = (
        WebSocketRouteDefinitionV2(
            owner_entry_id=ACP_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}/ws",
            endpoint=acp_websocket_endpoint,
            name="acp_websocket_endpoint",
            replaces_builtin_row_id=ACP_HTTP_ROUTES_ROW_V2,
        ),
        WebSocketRouteDefinitionV2(
            owner_entry_id=ACP_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}/runners/connect",
            endpoint=acp_runner_connect_endpoint,
            name="acp_runner_connect_endpoint",
            replaces_builtin_row_id=ACP_HTTP_ROUTES_ROW_V2,
        ),
    )
    http_mapping: tuple[
        tuple[str, tuple[str, ...], Callable[..., Any], str, object | None, int | None],
        ...,
    ] = (
        (
            f"{prefix}/tenants/{{tenant_id}}/status",
            ("GET",),
            get_tenant_acp_status,
            "get_tenant_acp_status",
            TenantACPStatusResponse,
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/runner-pools",
            ("GET",),
            list_tenant_acp_runner_pools,
            "list_tenant_acp_runner_pools",
            list[ACPRunnerPoolResponse],
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/runner-instances",
            ("GET",),
            list_tenant_acp_runner_instances,
            "list_tenant_acp_runner_instances",
            list[ACPRunnerInstanceResponse],
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents",
            ("GET",),
            list_tenant_external_agents,
            "list_tenant_external_agents",
            list[TenantExternalACPAgentResponse],
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents",
            ("POST",),
            create_tenant_external_agent,
            "create_tenant_external_agent",
            TenantExternalACPAgentResponse,
            201,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents/{{agent_key}}",
            ("GET",),
            get_tenant_external_agent,
            "get_tenant_external_agent",
            TenantExternalACPAgentResponse,
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents/{{agent_key}}",
            ("PUT",),
            update_tenant_external_agent,
            "update_tenant_external_agent",
            TenantExternalACPAgentResponse,
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents/{{agent_key}}",
            ("DELETE",),
            delete_tenant_external_agent,
            "delete_tenant_external_agent",
            ExternalACPAckResponse,
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/sessions",
            ("GET",),
            list_tenant_external_agent_sessions,
            "list_tenant_external_agent_sessions",
            list[ExternalACPSessionSummary],
            None,
        ),
        (
            tenant_external_agent_sessions,
            ("POST",),
            create_tenant_external_agent_session,
            "create_tenant_external_agent_session",
            ExternalACPSessionResult,
            201,
        ),
        (
            f"{tenant_external_agent_sessions}/{{session_id}}/prompt",
            ("POST",),
            prompt_tenant_external_agent_session,
            "prompt_tenant_external_agent_session",
            ExternalACPPromptResult,
            None,
        ),
        (
            f"{tenant_external_agent_sessions}/{{session_id}}/cancel",
            ("POST",),
            cancel_tenant_external_agent_session,
            "cancel_tenant_external_agent_session",
            ExternalACPAckResponse,
            None,
        ),
        (
            f"{tenant_external_agent_sessions}/{{session_id}}",
            ("DELETE",),
            close_tenant_external_agent_session,
            "close_tenant_external_agent_session",
            ExternalACPAckResponse,
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents/{{agent_key}}/test",
            ("POST",),
            test_tenant_external_agent,
            "test_tenant_external_agent",
            TenantExternalACPTestResponse,
            None,
        ),
        (
            f"{prefix}/external-agents",
            ("GET",),
            list_external_agents,
            "list_external_agents",
            list[ExternalACPAgentSummary],
            None,
        ),
        (
            f"{prefix}/external-agents/{{agent_id}}/sessions",
            ("POST",),
            create_external_agent_session,
            "create_external_agent_session",
            ExternalACPSessionResult,
            201,
        ),
        (
            f"{prefix}/external-agents/{{agent_id}}/sessions/{{session_id}}/prompt",
            ("POST",),
            prompt_external_agent_session,
            "prompt_external_agent_session",
            ExternalACPPromptResult,
            None,
        ),
        (
            f"{prefix}/external-agents/{{agent_id}}/sessions/{{session_id}}/cancel",
            ("POST",),
            cancel_external_agent_session,
            "cancel_external_agent_session",
            ExternalACPAckResponse,
            None,
        ),
        (
            f"{prefix}/external-agents/{{agent_id}}/sessions/{{session_id}}",
            ("DELETE",),
            close_external_agent_session,
            "close_external_agent_session",
            ExternalACPAckResponse,
            None,
        ),
    )
    return (
        *websocket_definitions,
        *(
            _acp_route_v2(
                path=path,
                methods=methods,
                endpoint=endpoint,
                name=name,
                response_model=response_model,
                status_code=status_code,
            )
            for path, methods, endpoint, name, response_model, status_code in http_mapping
        ),
    )


def builtin_acp_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register ACP routes as reversible effects of one V2 Fiber."""
    definitions = acp_route_definitions_v2()

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

        await context.effect(setup, label=ACP_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=ACP_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ACP_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "ACP_HTTP_ROUTES_ENTRY_V2",
    "ACP_HTTP_ROUTES_MODULE_V2",
    "ACP_HTTP_ROUTES_ROW_V2",
    "acp_route_definitions_v2",
    "builtin_acp_http_routes_definition_v2",
]
