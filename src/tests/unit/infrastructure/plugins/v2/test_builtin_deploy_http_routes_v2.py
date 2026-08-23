"""Production V2 ownership tests for the builtin deploy HTTP row."""

from __future__ import annotations

import pytest
from fastapi import status

from src.application.schemas.deploy_schemas import (
    DeployListResponse,
    DeployResponse,
)
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_deploy_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_deploy_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.deploy_route_definitions_v2()
    prefix = "/api/v1/deploys"

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
        (f"{prefix}/", ("POST",), "create_deploy", status.HTTP_201_CREATED, DeployResponse),
        (f"{prefix}/", ("GET",), "list_deploys", None, DeployListResponse),
        (
            f"{prefix}/instances/{{instance_id}}/latest",
            ("GET",),
            "get_latest_deploy",
            None,
            DeployResponse,
        ),
        (f"{prefix}/{{deploy_id}}", ("GET",), "get_deploy", None, DeployResponse),
        (
            f"{prefix}/{{deploy_id}}/success",
            ("POST",),
            "mark_deploy_success",
            None,
            DeployResponse,
        ),
        (
            f"{prefix}/{{deploy_id}}/failed",
            ("POST",),
            "mark_deploy_failed",
            None,
            DeployResponse,
        ),
        (
            f"{prefix}/{{deploy_id}}/cancel",
            ("POST",),
            "cancel_deploy",
            None,
            DeployResponse,
        ),
        (
            f"{prefix}/{{deploy_id}}/progress",
            ("GET",),
            "stream_deploy_progress",
            None,
            None,
        ),
    )
    assert {definition.tags for definition in definitions} == {("Deploys",)}
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.DEPLOY_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"deploy"}


def test_deploy_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="deploy-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.deploy_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("deploy",)


def test_deploy_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_deploy_http_routes_definition_v2()

    assert definition.module_ref == subject.DEPLOY_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
