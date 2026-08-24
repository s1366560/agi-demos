"""Production V2 ownership tests for the MCP HTTP row."""

from __future__ import annotations

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_mcp_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2


def test_mcp_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.mcp_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("GET", "/api/v1/mcp/apps"),
        ("POST", "/api/v1/mcp/apps/proxy/tool-call"),
        ("GET", "/api/v1/mcp/apps/{app_id}"),
        ("DELETE", "/api/v1/mcp/apps/{app_id}"),
        ("GET", "/api/v1/mcp/apps/{app_id}/resource"),
        ("POST", "/api/v1/mcp/apps/{app_id}/tool-call"),
        ("POST", "/api/v1/mcp/apps/{app_id}/refresh"),
        ("POST", "/api/v1/mcp/apps/resources/read"),
        ("POST", "/api/v1/mcp/apps/resources/list"),
        ("POST", "/api/v1/mcp/create"),
        ("GET", "/api/v1/mcp/list"),
        ("GET", "/api/v1/mcp/{server_id}"),
        ("PUT", "/api/v1/mcp/{server_id}"),
        ("DELETE", "/api/v1/mcp/{server_id}"),
        ("POST", "/api/v1/mcp/{server_id}/sync"),
        ("POST", "/api/v1/mcp/{server_id}/test"),
        ("POST", "/api/v1/mcp/reconcile/{project_id}"),
        ("GET", "/api/v1/mcp/health/summary"),
        ("GET", "/api/v1/mcp/{server_id}/health"),
        ("GET", "/api/v1/mcp/{server_id}/prompts"),
        ("POST", "/api/v1/mcp/{server_id}/log-level"),
        ("GET", "/api/v1/mcp/{server_id}/logs"),
        ("GET", "/api/v1/mcp/tools/all"),
        ("POST", "/api/v1/mcp/tools/call"),
        ("POST", "/api/v1/mcp"),
        ("GET", "/api/v1/mcp"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.MCP_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"mcp"}


def test_mcp_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="mcp-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.mcp_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("mcp",)


def test_mcp_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_mcp_http_routes_definition_v2()

    assert definition.module_ref == subject.MCP_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
