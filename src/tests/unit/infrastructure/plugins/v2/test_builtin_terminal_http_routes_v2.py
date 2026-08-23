"""Production V2 ownership tests for the builtin terminal HTTP/WS row."""

from __future__ import annotations

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_terminal_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.http_routes import (
    RouteDefinitionV2,
    WebSocketRouteDefinitionV2,
)

pytestmark = pytest.mark.unit


def test_terminal_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.terminal_route_definitions_v2()

    assert tuple(
        (definition.path, definition.methods, definition.name) for definition in definitions
    ) == (
        (
            "/api/v1/terminal/{sandbox_id}/create",
            ("POST",),
            "create_terminal_session",
        ),
        (
            "/api/v1/terminal/{sandbox_id}/sessions",
            ("GET",),
            "list_terminal_sessions",
        ),
        (
            "/api/v1/terminal/{sandbox_id}/sessions/{session_id}",
            ("DELETE",),
            "close_terminal_session",
        ),
        (
            "/api/v1/terminal/{sandbox_id}/ws",
            ("WEBSOCKET",),
            "terminal_websocket",
        ),
    )
    assert all(isinstance(definition, RouteDefinitionV2) for definition in definitions[:3])
    assert isinstance(definitions[3], WebSocketRouteDefinitionV2)
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.TERMINAL_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"terminal"}


def test_terminal_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="terminal-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.terminal_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("terminal",)


def test_terminal_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_terminal_http_routes_definition_v2()

    assert definition.module_ref == subject.TERMINAL_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
