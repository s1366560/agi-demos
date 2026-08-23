"""Production V2 ownership tests for the builtin tenant-skill-configs HTTP row."""

from __future__ import annotations

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_tenant_skill_configs_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_tenant_skill_configs_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.tenant_skill_config_route_definitions_v2()
    prefix = "/api/v1/tenant/skills/config"

    assert tuple(
        (definition.path, definition.methods, definition.name) for definition in definitions
    ) == (
        (f"{prefix}/", ("GET",), "list_tenant_skill_configs"),
        (f"{prefix}/{{system_skill_name}}", ("GET",), "get_tenant_skill_config"),
        (f"{prefix}/disable", ("POST",), "disable_system_skill"),
        (f"{prefix}/override", ("POST",), "override_system_skill"),
        (f"{prefix}/enable", ("POST",), "enable_system_skill"),
        (f"{prefix}/{{system_skill_name}}", ("DELETE",), "delete_tenant_skill_config"),
        (f"{prefix}/status/{{system_skill_name}}", ("GET",), "get_skill_status"),
    )
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.TENANT_SKILL_CONFIGS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {
        "tenant-skill-configs"
    }


def test_tenant_skill_configs_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="tenant-skill-configs-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.tenant_skill_config_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("tenant-skill-configs",)


def test_tenant_skill_configs_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_tenant_skill_configs_http_routes_definition_v2()

    assert definition.module_ref == subject.TENANT_SKILL_CONFIGS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
