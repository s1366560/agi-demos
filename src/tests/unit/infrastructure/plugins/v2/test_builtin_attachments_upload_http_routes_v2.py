"""Production V2 ownership tests for the builtin attachment-upload HTTP row."""

from __future__ import annotations

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_attachments_upload_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_attachments_upload_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.attachments_upload_route_definitions_v2()
    prefix = "/api/v1/attachments"

    assert tuple(
        (definition.path, definition.methods, definition.name) for definition in definitions
    ) == (
        (f"{prefix}/upload/initiate", ("POST",), "initiate_multipart_upload"),
        (f"{prefix}/upload/part", ("POST",), "upload_part"),
        (f"{prefix}/upload/complete", ("POST",), "complete_multipart_upload"),
        (f"{prefix}/upload/abort", ("POST",), "abort_multipart_upload"),
        (f"{prefix}/upload/simple", ("POST",), "upload_simple"),
        (prefix, ("GET",), "list_attachments"),
        (f"{prefix}/{{attachment_id}}", ("GET",), "get_attachment"),
        (
            f"{prefix}/{{attachment_id}}/download",
            ("GET",),
            "download_attachment",
        ),
        (f"{prefix}/{{attachment_id}}", ("DELETE",), "delete_attachment"),
    )
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.ATTACHMENTS_UPLOAD_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {
        "attachments-upload"
    }


def test_attachments_upload_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="attachments-upload-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.attachments_upload_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("attachments-upload",)


def test_attachments_upload_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_attachments_upload_http_routes_definition_v2()

    assert definition.module_ref == subject.ATTACHMENTS_UPLOAD_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
