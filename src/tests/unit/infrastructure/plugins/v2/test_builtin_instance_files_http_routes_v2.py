"""Production V2 ownership tests for the builtin instance-files HTTP row."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_instance_files_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_instance_files_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.instance_file_route_definitions_v2()
    prefix = "/api/v1/instances/{instance_id}/files"

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
        (prefix, ("GET",), "list_files", None, dict[str, Any]),
        (
            f"{prefix}/{{file_path:path}}/content",
            ("GET",),
            "preview_file",
            None,
            dict[str, Any],
        ),
        (
            f"{prefix}/{{file_path:path}}/download",
            ("GET",),
            "download_file",
            None,
            None,
        ),
        (
            prefix,
            ("POST",),
            "create_file",
            status.HTTP_201_CREATED,
            dict[str, Any],
        ),
        (f"{prefix}/upload", ("POST",), "upload_file", None, dict[str, Any]),
        (
            f"{prefix}/{{file_path:path}}",
            ("DELETE",),
            "delete_file",
            status.HTTP_204_NO_CONTENT,
            None,
        ),
    )
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.INSTANCE_FILES_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"instance-files"}


def test_instance_files_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="instance-files-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.instance_file_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("instance-files",)


def test_instance_files_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_instance_files_http_routes_definition_v2()

    assert definition.module_ref == subject.INSTANCE_FILES_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
