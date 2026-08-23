"""Production V2 ownership tests for the builtin subagents HTTP row."""

from __future__ import annotations

from typing import Any

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.routers.subagents import (
    FilesystemSubAgentListResponse,
    SubAgentListResponse,
    SubAgentMatchResponse,
    SubAgentResponse,
    SubAgentStatsResponse,
    TemplateListResponse,
    TemplateResponse,
)
from src.infrastructure.plugins.v2 import builtin_subagents_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_subagents_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.subagents_route_definitions_v2()
    prefix = "/api/v1/subagents"

    assert tuple(
        (
            definition.path,
            definition.methods,
            definition.name,
            definition.response_model,
            definition.status_code,
        )
        for definition in definitions
    ) == (
        (f"{prefix}/", ("POST",), "create_subagent", SubAgentResponse, 201),
        (f"{prefix}/", ("GET",), "list_subagents", SubAgentListResponse, None),
        (
            f"{prefix}/filesystem",
            ("GET",),
            "list_filesystem_subagents",
            FilesystemSubAgentListResponse,
            None,
        ),
        (
            f"{prefix}/filesystem/{{name}}/import",
            ("POST",),
            "import_filesystem_subagent",
            SubAgentResponse,
            201,
        ),
        (
            f"{prefix}/templates/list",
            ("GET",),
            "list_subagent_templates",
            TemplateListResponse,
            None,
        ),
        (f"{prefix}/templates/", ("POST",), "create_template", TemplateResponse, 201),
        (
            f"{prefix}/templates/categories",
            ("GET",),
            "list_template_categories",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/templates/{{template_id}}",
            ("GET",),
            "get_template",
            TemplateResponse,
            None,
        ),
        (
            f"{prefix}/templates/{{template_id}}",
            ("PUT",),
            "update_template",
            TemplateResponse,
            None,
        ),
        (
            f"{prefix}/templates/{{template_id}}",
            ("DELETE",),
            "delete_template",
            None,
            204,
        ),
        (
            f"{prefix}/templates/{{template_id}}/install",
            ("POST",),
            "install_template",
            SubAgentResponse,
            201,
        ),
        (
            f"{prefix}/templates/from-subagent/{{subagent_id}}",
            ("POST",),
            "export_subagent_as_template",
            TemplateResponse,
            201,
        ),
        (
            f"{prefix}/{{subagent_id}}",
            ("GET",),
            "get_subagent",
            SubAgentResponse,
            None,
        ),
        (
            f"{prefix}/{{subagent_id}}",
            ("PUT",),
            "update_subagent",
            SubAgentResponse,
            None,
        ),
        (f"{prefix}/{{subagent_id}}", ("DELETE",), "delete_subagent", None, 204),
        (
            f"{prefix}/{{subagent_id}}/enable",
            ("PATCH",),
            "toggle_subagent_enabled",
            SubAgentResponse,
            None,
        ),
        (
            f"{prefix}/{{subagent_id}}/stats",
            ("GET",),
            "get_subagent_stats",
            SubAgentStatsResponse,
            None,
        ),
        (f"{prefix}/match", ("POST",), "match_subagent", SubAgentMatchResponse, None),
        (f"{prefix}/templates/seed", ("POST",), "seed_templates", dict[str, Any], None),
    )
    assert {definition.tags for definition in definitions} == {("SubAgents",)}
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.SUBAGENTS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"subagents"}


def test_subagents_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="subagents-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.subagents_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("subagents",)


def test_subagents_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_subagents_http_routes_definition_v2()

    assert definition.module_ref == subject.SUBAGENTS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
