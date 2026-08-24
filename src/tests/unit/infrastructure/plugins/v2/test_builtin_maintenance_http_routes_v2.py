"""Production V2 ownership tests for the builtin maintenance HTTP row."""

from __future__ import annotations

from typing import Any

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_maintenance_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_maintenance_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.maintenance_route_definitions_v2()
    prefix = "/api/v1/maintenance"

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
            f"{prefix}/refresh/incremental",
            ("POST",),
            "incremental_refresh",
            None,
            dict[str, Any],
        ),
        (f"{prefix}/deduplicate", ("POST",), "deduplicate_entities", None, dict[str, Any]),
        (
            f"{prefix}/invalidate-edges",
            ("POST",),
            "invalidate_stale_edges",
            None,
            dict[str, Any],
        ),
        (f"{prefix}/status", ("GET",), "get_maintenance_status", None, dict[str, Any]),
        (f"{prefix}/optimize", ("POST",), "optimize_graph", None, Any),
        (
            f"{prefix}/embeddings/status",
            ("GET",),
            "get_embedding_status",
            None,
            dict[str, Any],
        ),
        (
            f"{prefix}/embeddings/rebuild",
            ("POST",),
            "rebuild_embeddings",
            None,
            dict[str, Any],
        ),
        (
            f"{prefix}/embeddings/dimensions/check",
            ("GET",),
            "check_embedding_dimensions",
            None,
            dict[str, Any],
        ),
        (
            f"{prefix}/embeddings/validate",
            ("GET",),
            "validate_embeddings",
            None,
            dict[str, Any],
        ),
        (
            f"{prefix}/embeddings/native/status",
            ("GET",),
            "get_native_embedding_status",
            None,
            dict[str, Any],
        ),
        (
            f"{prefix}/embeddings/native/migrate",
            ("POST",),
            "migrate_embeddings",
            None,
            dict[str, Any],
        ),
    )
    assert {definition.tags for definition in definitions} == {("maintenance",)}
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.MAINTENANCE_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"maintenance"}


def test_maintenance_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="maintenance-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.maintenance_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("maintenance",)


def test_maintenance_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_maintenance_http_routes_definition_v2()

    assert definition.module_ref == subject.MAINTENANCE_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
