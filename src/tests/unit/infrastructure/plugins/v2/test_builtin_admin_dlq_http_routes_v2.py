"""Production V2 ownership tests for the builtin admin DLQ HTTP row."""

from __future__ import annotations

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_admin_dlq_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_admin_dlq_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.admin_dlq_route_definitions_v2()
    prefix = "/api/v1/admin/dlq"

    assert tuple(
        (definition.path, definition.methods, definition.name) for definition in definitions
    ) == (
        (f"{prefix}/messages", ("GET",), "list_messages"),
        (f"{prefix}/messages/{{message_id}}", ("GET",), "get_message"),
        (
            f"{prefix}/messages/{{message_id}}/retry",
            ("POST",),
            "retry_message",
        ),
        (f"{prefix}/messages/retry", ("POST",), "retry_messages"),
        (
            f"{prefix}/messages/{{message_id}}",
            ("DELETE",),
            "discard_message",
        ),
        (f"{prefix}/messages/discard", ("POST",), "discard_messages"),
        (f"{prefix}/stats", ("GET",), "get_stats"),
        (f"{prefix}/cleanup/expired", ("POST",), "cleanup_expired"),
        (f"{prefix}/cleanup/resolved", ("POST",), "cleanup_resolved"),
    )
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.ADMIN_DLQ_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"admin-dlq"}


def test_admin_dlq_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="admin-dlq-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.admin_dlq_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("admin-dlq",)


def test_admin_dlq_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_admin_dlq_http_routes_definition_v2()

    assert definition.module_ref == subject.ADMIN_DLQ_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
