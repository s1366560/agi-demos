"""Production V2 ownership tests for the builtin admin DLQ HTTP row."""

from __future__ import annotations

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.routers import admin_dlq as admin_dlq_router
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


def test_admin_dlq_row_registers_production_handlers_without_forwarding_wrappers() -> None:
    definitions = subject.admin_dlq_route_definitions_v2()

    assert tuple(definition.endpoint for definition in definitions) == (
        admin_dlq_router.list_messages,
        admin_dlq_router.get_message,
        admin_dlq_router.retry_message,
        admin_dlq_router.retry_messages,
        admin_dlq_router.discard_message,
        admin_dlq_router.discard_messages,
        admin_dlq_router.get_stats,
        admin_dlq_router.cleanup_expired,
        admin_dlq_router.cleanup_resolved,
    )


def test_admin_dlq_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="admin-dlq-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.admin_dlq_route_definitions_v2(),
    )

    assert claimed.route_signatures == tuple(
        (
            definition.path,
            definition.name,
            () if definition.methods == ("WEBSOCKET",) else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert claimed.v2_owned_row_ids == ("admin-dlq",)


def test_admin_dlq_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_admin_dlq_http_routes_definition_v2()

    assert definition.module_ref == subject.ADMIN_DLQ_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
