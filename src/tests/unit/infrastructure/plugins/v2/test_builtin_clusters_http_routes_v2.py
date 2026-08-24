"""Production V2 ownership tests for the builtin clusters HTTP row."""

from __future__ import annotations

import pytest
from fastapi import status

from src.application.schemas.acp_runner_schemas import (
    ACPRunnerPoolResponse,
    ACPRunnerTokenResponse,
)
from src.application.schemas.cluster_schemas import (
    ClusterHealthResponse,
    ClusterListResponse,
    ClusterResponse,
)
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_clusters_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_clusters_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.cluster_route_definitions_v2()
    prefix = "/api/v1/clusters"

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
        (f"{prefix}/", ("POST",), "create_cluster", status.HTTP_201_CREATED, ClusterResponse),
        (f"{prefix}/", ("GET",), "list_clusters", None, ClusterListResponse),
        (f"{prefix}/{{cluster_id}}", ("GET",), "get_cluster", None, ClusterResponse),
        (f"{prefix}/{{cluster_id}}", ("PUT",), "update_cluster", None, ClusterResponse),
        (
            f"{prefix}/{{cluster_id}}",
            ("DELETE",),
            "delete_cluster",
            status.HTTP_204_NO_CONTENT,
            None,
        ),
        (
            f"{prefix}/{{cluster_id}}/acp-runner-pools",
            ("GET",),
            "list_cluster_acp_runner_pools",
            None,
            list[ACPRunnerPoolResponse],
        ),
        (
            f"{prefix}/{{cluster_id}}/acp-runner-pools",
            ("POST",),
            "create_cluster_acp_runner_pool",
            status.HTTP_201_CREATED,
            ACPRunnerPoolResponse,
        ),
        (
            f"{prefix}/{{cluster_id}}/acp-runner-pools/{{pool_key}}",
            ("PUT",),
            "update_cluster_acp_runner_pool",
            None,
            ACPRunnerPoolResponse,
        ),
        (
            f"{prefix}/{{cluster_id}}/acp-runner-pools/{{pool_key}}/registration-token",
            ("POST",),
            "create_cluster_acp_runner_registration_token",
            None,
            ACPRunnerTokenResponse,
        ),
        (
            f"{prefix}/{{cluster_id}}/health",
            ("GET",),
            "get_cluster_health",
            None,
            ClusterHealthResponse,
        ),
        (
            f"{prefix}/{{cluster_id}}/health",
            ("PUT",),
            "update_health_status",
            None,
            ClusterResponse,
        ),
    )
    assert {definition.tags for definition in definitions} == {("Clusters",)}
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.CLUSTERS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"clusters"}


def test_clusters_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="clusters-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.cluster_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("clusters",)


def test_clusters_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_clusters_http_routes_definition_v2()

    assert definition.module_ref == subject.CLUSTERS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
