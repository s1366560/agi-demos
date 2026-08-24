"""Production V2 ownership tests for the builtin ACP HTTP/WebSocket row."""

from __future__ import annotations

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_acp_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.http_routes import (
    WEBSOCKET_ROUTE_METHOD_V2,
    RouteDefinitionV2,
    WebSocketRouteDefinitionV2,
)

pytestmark = pytest.mark.unit


def test_acp_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.acp_route_definitions_v2()
    prefix = "/api/v1/acp"

    assert tuple(
        (
            definition.path,
            definition.methods,
            definition.name,
            definition.status_code if isinstance(definition, RouteDefinitionV2) else None,
        )
        for definition in definitions
    ) == (
        (f"{prefix}/ws", (WEBSOCKET_ROUTE_METHOD_V2,), "acp_websocket_endpoint", None),
        (
            f"{prefix}/runners/connect",
            (WEBSOCKET_ROUTE_METHOD_V2,),
            "acp_runner_connect_endpoint",
            None,
        ),
        (f"{prefix}/tenants/{{tenant_id}}/status", ("GET",), "get_tenant_acp_status", None),
        (
            f"{prefix}/tenants/{{tenant_id}}/runner-pools",
            ("GET",),
            "list_tenant_acp_runner_pools",
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/runner-instances",
            ("GET",),
            "list_tenant_acp_runner_instances",
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents",
            ("GET",),
            "list_tenant_external_agents",
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents",
            ("POST",),
            "create_tenant_external_agent",
            201,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents/{{agent_key}}",
            ("GET",),
            "get_tenant_external_agent",
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents/{{agent_key}}",
            ("PUT",),
            "update_tenant_external_agent",
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents/{{agent_key}}",
            ("DELETE",),
            "delete_tenant_external_agent",
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/sessions",
            ("GET",),
            "list_tenant_external_agent_sessions",
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents/{{agent_key}}/sessions",
            ("POST",),
            "create_tenant_external_agent_session",
            201,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents/{{agent_key}}/sessions/"
            "{session_id}/prompt",
            ("POST",),
            "prompt_tenant_external_agent_session",
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents/{{agent_key}}/sessions/"
            "{session_id}/cancel",
            ("POST",),
            "cancel_tenant_external_agent_session",
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents/{{agent_key}}/sessions/{{session_id}}",
            ("DELETE",),
            "close_tenant_external_agent_session",
            None,
        ),
        (
            f"{prefix}/tenants/{{tenant_id}}/external-agents/{{agent_key}}/test",
            ("POST",),
            "test_tenant_external_agent",
            None,
        ),
        (f"{prefix}/external-agents", ("GET",), "list_external_agents", None),
        (
            f"{prefix}/external-agents/{{agent_id}}/sessions",
            ("POST",),
            "create_external_agent_session",
            201,
        ),
        (
            f"{prefix}/external-agents/{{agent_id}}/sessions/{{session_id}}/prompt",
            ("POST",),
            "prompt_external_agent_session",
            None,
        ),
        (
            f"{prefix}/external-agents/{{agent_id}}/sessions/{{session_id}}/cancel",
            ("POST",),
            "cancel_external_agent_session",
            None,
        ),
        (
            f"{prefix}/external-agents/{{agent_id}}/sessions/{{session_id}}",
            ("DELETE",),
            "close_external_agent_session",
            None,
        ),
    )
    assert all(isinstance(definition, WebSocketRouteDefinitionV2) for definition in definitions[:2])
    assert all(isinstance(definition, RouteDefinitionV2) for definition in definitions[2:])
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.ACP_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"acp"}


def test_acp_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="acp-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.acp_route_definitions_v2(),
    )

    assert claimed.route_signatures == tuple(
        (
            definition.path,
            definition.name,
            ()
            if definition.methods == ("WEBSOCKET",)
            else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert claimed.v2_owned_row_ids == ("acp",)


def test_acp_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_acp_http_routes_definition_v2()

    assert definition.module_ref == subject.ACP_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
