"""Production V2 ownership tests for the builtin observability HTTP row."""

from __future__ import annotations

from typing import Any

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_observability_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_observability_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.observability_route_definitions_v2()
    prefix = "/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/observability"

    assert tuple(
        (definition.path, definition.methods, definition.name, definition.response_model)
        for definition in definitions
    ) == (
        (
            f"{prefix}/messages/trace/{{trace_id}}",
            ("GET",),
            "get_message_trace",
            list[dict[str, Any]],
        ),
        (f"{prefix}/messages/metrics", ("GET",), "get_message_metrics", dict[str, Any]),
        (
            f"{prefix}/messages/metrics/nodes/{{node_id}}",
            ("GET",),
            "get_node_metrics",
            dict[str, Any],
        ),
        (
            f"{prefix}/messages/heatmap",
            ("GET",),
            "get_message_heatmap",
            list[dict[str, Any]],
        ),
        (
            f"{prefix}/messages/dead-letters",
            ("GET",),
            "list_dead_letters",
            list[dict[str, Any]],
        ),
        (
            f"{prefix}/messages/dead-letters/{{dead_letter_id}}/retry",
            ("POST",),
            "retry_dead_letter",
            dict[str, Any],
        ),
        (
            f"{prefix}/messages/circuit-breakers",
            ("GET",),
            "list_circuit_breakers",
            list[dict[str, Any]],
        ),
        (f"{prefix}/messages/events", ("GET",), "list_events", list[dict[str, Any]]),
        (
            f"{prefix}/messages/{{message_id}}/reconstruct",
            ("GET",),
            "reconstruct_message",
            dict[str, Any],
        ),
        (f"{prefix}/messages/queue-stats", ("GET",), "get_queue_stats", dict[str, Any]),
        (
            f"{prefix}/nodes/{{node_id}}/card",
            ("GET",),
            "get_node_card",
            dict[str, Any],
        ),
        (f"{prefix}/nodes/discover", ("GET",), "discover_nodes", list[dict[str, Any]]),
        (
            f"{prefix}/nodes/{{node_id}}/card",
            ("PUT",),
            "update_node_card",
            dict[str, Any],
        ),
        (
            f"{prefix}/nodes/{{node_id}}/messages",
            ("POST",),
            "post_node_message",
            dict[str, Any],
        ),
        (f"{prefix}/nodes/types", ("GET",), "list_node_types", list[dict[str, str]]),
        (f"{prefix}/messages/alerts", ("GET",), "get_alerts", dict[str, Any]),
    )
    assert {definition.tags for definition in definitions} == {("observability",)}
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.OBSERVABILITY_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"observability"}


def test_observability_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="observability-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.observability_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("observability",)


def test_observability_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_observability_http_routes_definition_v2()

    assert definition.module_ref == subject.OBSERVABILITY_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
