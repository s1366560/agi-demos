"""Production V2 ownership tests for the Sandbox HTTP row."""

from __future__ import annotations

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_sandbox_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2


def test_sandbox_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.sandbox_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("POST", "/api/v1/sandbox/projects/{project_id}/token"),
        ("POST", "/api/v1/sandbox/token/validate"),
        ("DELETE", "/api/v1/sandbox/projects/{project_id}/tokens"),
        ("GET", "/api/v1/sandbox/profiles"),
        ("GET", "/api/v1/sandbox/{sandbox_id}/health"),
        ("POST", "/api/v1/sandbox/create"),
        ("GET", "/api/v1/sandbox/list"),
        ("GET", "/api/v1/sandbox/{sandbox_id}"),
        ("DELETE", "/api/v1/sandbox/{sandbox_id}"),
        ("POST", "/api/v1/sandbox/cleanup"),
        ("POST", "/api/v1/sandbox/{sandbox_id}/connect"),
        ("GET", "/api/v1/sandbox/{sandbox_id}/tools"),
        ("GET", "/api/v1/sandbox/{sandbox_id}/tools/agent"),
        ("POST", "/api/v1/sandbox/{sandbox_id}/call"),
        ("POST", "/api/v1/sandbox/{sandbox_id}/read"),
        ("POST", "/api/v1/sandbox/{sandbox_id}/write"),
        ("POST", "/api/v1/sandbox/{sandbox_id}/bash"),
        ("POST", "/api/v1/sandbox/{sandbox_id}/desktop"),
        ("DELETE", "/api/v1/sandbox/{sandbox_id}/desktop"),
        ("GET", "/api/v1/sandbox/{sandbox_id}/desktop"),
        ("POST", "/api/v1/sandbox/{sandbox_id}/terminal"),
        ("DELETE", "/api/v1/sandbox/{sandbox_id}/terminal"),
        ("GET", "/api/v1/sandbox/{sandbox_id}/terminal"),
        ("GET", "/api/v1/sandbox/events/{project_id}"),
        ("GET", "/api/v1/sandbox/"),
        ("GET", "/api/v1/sandbox"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.SANDBOX_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"sandbox"}


def test_sandbox_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="sandbox-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.sandbox_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("sandbox",)


def test_sandbox_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_sandbox_http_routes_definition_v2()

    assert definition.module_ref == subject.SANDBOX_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
