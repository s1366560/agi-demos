"""Production V2 ownership tests for the builtin instances HTTP row."""

from __future__ import annotations

import pytest
from fastapi import status

from src.application.schemas.deploy_schemas import DeployResponse
from src.application.schemas.instance_schemas import (
    InstanceListResponse,
    InstanceMemberListResponse,
    InstanceMemberResponse,
    InstanceResponse,
    UserSearchResult,
)
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.routers.instances import (
    InstanceConfigResponse,
    InstanceLlmConfigResponse,
)
from src.infrastructure.plugins.v2 import builtin_instances_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_instances_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.instance_route_definitions_v2()
    prefix = "/api/v1/instances"

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
        (f"{prefix}/", ("POST",), "create_instance", status.HTTP_201_CREATED, InstanceResponse),
        (f"{prefix}/", ("GET",), "list_instances", None, InstanceListResponse),
        (f"{prefix}/{{instance_id}}", ("GET",), "get_instance", None, InstanceResponse),
        (f"{prefix}/{{instance_id}}", ("PUT",), "update_instance", None, InstanceResponse),
        (
            f"{prefix}/{{instance_id}}",
            ("DELETE",),
            "delete_instance",
            status.HTTP_204_NO_CONTENT,
            None,
        ),
        (
            f"{prefix}/{{instance_id}}/scale",
            ("POST",),
            "scale_instance",
            None,
            InstanceResponse,
        ),
        (
            f"{prefix}/{{instance_id}}/restart",
            ("POST",),
            "restart_instance",
            None,
            InstanceResponse,
        ),
        (
            f"{prefix}/{{instance_id}}/config",
            ("GET",),
            "get_config",
            None,
            InstanceConfigResponse,
        ),
        (
            f"{prefix}/{{instance_id}}/config",
            ("PUT",),
            "update_config",
            None,
            InstanceConfigResponse,
        ),
        (
            f"{prefix}/{{instance_id}}/config/pending",
            ("PUT",),
            "save_pending_config",
            None,
            InstanceResponse,
        ),
        (
            f"{prefix}/{{instance_id}}/config/apply",
            ("POST",),
            "apply_pending_config",
            None,
            DeployResponse,
        ),
        (
            f"{prefix}/{{instance_id}}/members",
            ("POST",),
            "add_member",
            status.HTTP_201_CREATED,
            InstanceMemberResponse,
        ),
        (
            f"{prefix}/{{instance_id}}/members/search-users",
            ("GET",),
            "search_users",
            None,
            list[UserSearchResult],
        ),
        (
            f"{prefix}/{{instance_id}}/members/{{member_id}}",
            ("PUT",),
            "update_member_role",
            None,
            InstanceMemberResponse,
        ),
        (
            f"{prefix}/{{instance_id}}/members/{{user_id}}",
            ("DELETE",),
            "remove_member",
            status.HTTP_204_NO_CONTENT,
            None,
        ),
        (
            f"{prefix}/{{instance_id}}/members",
            ("GET",),
            "list_members",
            None,
            InstanceMemberListResponse,
        ),
        (
            f"{prefix}/{{instance_id}}/llm-config",
            ("GET",),
            "get_instance_llm_config",
            None,
            InstanceLlmConfigResponse,
        ),
        (
            f"{prefix}/{{instance_id}}/llm-config",
            ("PUT",),
            "update_instance_llm_config",
            None,
            InstanceLlmConfigResponse,
        ),
    )
    assert {definition.tags for definition in definitions} == {("Instances",)}
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.INSTANCES_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"instances"}


def test_instances_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="instances-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.instance_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("instances",)


def test_instances_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_instances_http_routes_definition_v2()

    assert definition.module_ref == subject.INSTANCES_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
