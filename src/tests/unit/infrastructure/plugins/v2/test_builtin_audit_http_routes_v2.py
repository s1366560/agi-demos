"""Production V2 ownership tests for the builtin audit HTTP row."""

from __future__ import annotations

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_audit_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_audit_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.audit_route_definitions_v2()
    prefix = "/api/v1/tenants/{tenant_id}/audit-logs"

    assert tuple(
        (definition.path, definition.methods, definition.name) for definition in definitions
    ) == (
        (prefix, ("GET",), "list_audit_logs"),
        (f"{prefix}/filter", ("GET",), "list_audit_logs_filtered"),
        (f"{prefix}/runtime-hooks", ("GET",), "list_runtime_hook_audit_logs"),
        (f"{prefix}/export", ("GET",), "export_audit_logs"),
        (
            f"{prefix}/runtime-hooks/summary",
            ("GET",),
            "get_runtime_hook_audit_summary",
        ),
    )
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.AUDIT_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"audit"}


def test_audit_row_registers_production_handlers_without_forwarding_wrappers() -> None:
    definitions = subject.audit_route_definitions_v2()

    assert tuple(definition.endpoint for definition in definitions) == (
        subject.list_audit_logs,
        subject.list_audit_logs_filtered,
        subject.list_runtime_hook_audit_logs,
        subject.export_audit_logs,
        subject.get_runtime_hook_audit_summary,
    )


def test_audit_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="audit-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.audit_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("audit",)


def test_audit_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_audit_http_routes_definition_v2()

    assert definition.module_ref == subject.AUDIT_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
