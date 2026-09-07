"""Production V2 ownership tests for the builtin instance-templates HTTP row."""

from __future__ import annotations

import pytest
from fastapi import status

from src.application.schemas.instance_template_schemas import (
    InstanceTemplateListResponse,
    InstanceTemplateResponse,
    TemplateItemResponse,
)
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_instance_templates_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_instance_templates_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.instance_template_route_definitions_v2()
    prefix = "/api/v1/instance-templates"

    assert tuple(
        (
            definition.path,
            definition.methods,
            definition.name,
            definition.status_code,
            definition.response_model,
        )
        for definition in definitions
    ) == (
        (
            f"{prefix}/",
            ("POST",),
            "create_template",
            status.HTTP_201_CREATED,
            InstanceTemplateResponse,
        ),
        (f"{prefix}/", ("GET",), "list_templates", None, InstanceTemplateListResponse),
        (
            f"{prefix}/{{template_id}}",
            ("GET",),
            "get_template",
            None,
            InstanceTemplateResponse,
        ),
        (
            f"{prefix}/{{template_id}}",
            ("PUT",),
            "update_template",
            None,
            InstanceTemplateResponse,
        ),
        (
            f"{prefix}/{{template_id}}",
            ("DELETE",),
            "delete_template",
            status.HTTP_204_NO_CONTENT,
            None,
        ),
        (
            f"{prefix}/{{template_id}}/publish",
            ("POST",),
            "publish_template",
            None,
            InstanceTemplateResponse,
        ),
        (
            f"{prefix}/{{template_id}}/unpublish",
            ("POST",),
            "unpublish_template",
            None,
            InstanceTemplateResponse,
        ),
        (
            f"{prefix}/{{template_id}}/clone",
            ("POST",),
            "clone_template",
            status.HTTP_201_CREATED,
            InstanceTemplateResponse,
        ),
        (
            f"{prefix}/{{template_id}}/items",
            ("POST",),
            "add_template_item",
            status.HTTP_201_CREATED,
            TemplateItemResponse,
        ),
        (
            f"{prefix}/{{template_id}}/items/{{item_id}}",
            ("DELETE",),
            "remove_template_item",
            status.HTTP_204_NO_CONTENT,
            None,
        ),
        (
            f"{prefix}/{{template_id}}/items",
            ("GET",),
            "list_template_items",
            None,
            list[TemplateItemResponse],
        ),
    )
    assert {definition.tags for definition in definitions} == {("Instance Templates",)}
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.INSTANCE_TEMPLATES_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {
        "instance-templates"
    }


def test_instance_templates_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="instance-templates-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.instance_template_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("instance-templates",)


def test_instance_templates_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_instance_templates_http_routes_definition_v2()

    assert definition.module_ref == subject.INSTANCE_TEMPLATES_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
