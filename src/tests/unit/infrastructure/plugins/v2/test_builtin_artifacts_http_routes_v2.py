"""Production V2 ownership tests for the builtin artifacts HTTP row."""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.routers.artifacts import (
    MAX_EDITABLE_ARTIFACT_REQUEST_BYTES,
    ArtifactContentBodyLimitRoute,
)
from src.infrastructure.plugins.v2 import builtin_artifacts_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.http_routes import install_route_definitions_v2

pytestmark = pytest.mark.unit


def test_artifacts_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.artifact_route_definitions_v2()
    prefix = "/api/v1/artifacts"

    assert tuple(
        (definition.path, definition.methods, definition.name) for definition in definitions
    ) == (
        (prefix, ("GET",), "list_artifacts"),
        (f"{prefix}/{{artifact_id}}", ("GET",), "get_artifact"),
        (f"{prefix}/{{artifact_id}}/download", ("GET",), "download_artifact"),
        (f"{prefix}/{{artifact_id}}/content", ("GET",), "get_artifact_content"),
        (
            f"{prefix}/{{artifact_id}}/content/bytes",
            ("GET",),
            "get_artifact_content_bytes",
        ),
        (f"{prefix}/{{artifact_id}}/refresh-url", ("POST",), "refresh_artifact_url"),
        (f"{prefix}/{{artifact_id}}/content", ("PUT",), "update_artifact_content"),
        (f"{prefix}/{{artifact_id}}", ("DELETE",), "delete_artifact"),
        (f"{prefix}/categories/list", ("GET",), "list_categories"),
    )
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.ARTIFACTS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"artifacts"}
    assert {definition.route_class_override for definition in definitions} == {
        ArtifactContentBodyLimitRoute
    }


def test_artifacts_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="artifacts-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.artifact_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("artifacts",)


@pytest.mark.parametrize(
    "content,headers",
    (
        (
            b"{" + b"x" * MAX_EDITABLE_ARTIFACT_REQUEST_BYTES + b"}",
            {"Content-Type": "application/json"},
        ),
        (
            iter((b"{", b"x" * MAX_EDITABLE_ARTIFACT_REQUEST_BYTES, b"}")),
            {"Content-Type": "application/json", "Transfer-Encoding": "chunked"},
        ),
    ),
)
def test_artifacts_v2_routes_bound_content_before_json_parsing(
    content: bytes | Iterable[bytes],
    headers: dict[str, str],
) -> None:
    app = FastAPI()
    install_route_definitions_v2(app, subject.artifact_route_definitions_v2())

    with TestClient(app) as client:
        response = client.put(
            "/api/v1/artifacts/artifact-1/content",
            content=content,
            headers=headers,
        )

    assert response.status_code == 413, response.text
    assert response.json() == {
        "detail": "Artifact content request exceeds the size limit",
        "reason_code": "artifact_content_request_size_limit",
        "max_bytes": MAX_EDITABLE_ARTIFACT_REQUEST_BYTES,
    }


def test_artifacts_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_artifacts_http_routes_definition_v2()

    assert definition.module_ref == subject.ARTIFACTS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
