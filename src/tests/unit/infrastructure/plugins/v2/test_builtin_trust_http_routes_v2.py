"""Production V2 ownership tests for the builtin trust HTTP row."""

from __future__ import annotations

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_trust_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_trust_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.trust_route_definitions_v2()
    prefix = "/api/v1/tenants/{tenant_id}/trust"

    assert tuple(
        (
            definition.path,
            definition.methods,
            definition.name,
            definition.status_code,
        )
        for definition in definitions
    ) == (
        (f"{prefix}/policies", ("GET",), "list_trust_policies", None),
        (f"{prefix}/policies", ("POST",), "create_trust_policy", 201),
        (
            f"{prefix}/policies/{{policy_id}}",
            ("DELETE",),
            "revoke_trust_policy",
            None,
        ),
        (f"{prefix}/policies/check", ("GET",), "check_trust", None),
        (
            f"{prefix}/approval-requests",
            ("POST",),
            "submit_approval_request",
            201,
        ),
        (
            f"{prefix}/approval-requests/{{record_id}}/resolve",
            ("POST",),
            "resolve_approval_request",
            None,
        ),
        (
            f"{prefix}/decision-records",
            ("GET",),
            "list_decision_records",
            None,
        ),
        (
            f"{prefix}/decision-records/{{record_id}}",
            ("GET",),
            "get_decision_record",
            None,
        ),
    )
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.TRUST_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"trust"}


def test_trust_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="trust-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.trust_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("trust",)


def test_trust_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_trust_http_routes_definition_v2()

    assert definition.module_ref == subject.TRUST_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
