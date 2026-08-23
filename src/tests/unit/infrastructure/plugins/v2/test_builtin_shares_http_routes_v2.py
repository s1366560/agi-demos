"""Production V2 ownership tests for the builtin shares HTTP row."""

from __future__ import annotations

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_shares_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2


def test_shares_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.shares_route_definitions_v2()

    assert tuple(
        (definition.path, definition.methods, definition.name) for definition in definitions
    ) == (
        ("/api/v1/memories/{memory_id}/shares", ("POST",), "create_share"),
        ("/api/v1/memories/{memory_id}/shares", ("GET",), "list_shares"),
        (
            "/api/v1/memories/{memory_id}/shares/{share_id}",
            ("DELETE",),
            "delete_share",
        ),
        ("/api/v1/shared/{share_token}", ("GET",), "get_shared_memory"),
    )
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.SHARES_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"shares"}


def test_shares_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="shares-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.shares_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("shares",)


def test_shares_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_shares_http_routes_definition_v2()

    assert definition.module_ref == subject.SHARES_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
