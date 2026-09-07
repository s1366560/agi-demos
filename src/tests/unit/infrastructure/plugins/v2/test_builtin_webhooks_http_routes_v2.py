"""Production V2 ownership tests for the builtin webhooks HTTP row."""

from __future__ import annotations

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_webhooks_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_webhooks_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.webhooks_route_definitions_v2()

    assert tuple(
        (definition.path, definition.methods, definition.name) for definition in definitions
    ) == (
        (
            "/api/v1/webhooks/feishu/workspace-message",
            ("POST",),
            "feishu_workspace_message",
        ),
    )
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.WEBHOOKS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"webhooks"}


def test_webhooks_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="webhooks-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.webhooks_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("webhooks",)


def test_webhooks_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_webhooks_http_routes_definition_v2()

    assert definition.module_ref == subject.WEBHOOKS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
