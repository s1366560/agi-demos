"""Production V2 ownership tests for the builtin plugin marketplace HTTP row."""

from __future__ import annotations

import pytest

from src.application.schemas.plugin_marketplace import (
    MarketplacePackageApprovalResponse,
    MarketplacePackageCatalogEntry,
    MarketplacePackageDetailResponse,
    MarketplacePackageResponse,
    MarketplacePackageRevocationResponse,
    MarketplacePackageUninstallResponse,
)
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_plugin_marketplace_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_plugin_marketplace_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.plugin_marketplace_route_definitions_v2()
    prefix = "/api/v1/plugin-marketplace/packages"

    assert tuple(
        (
            definition.path,
            definition.methods,
            definition.name,
            definition.response_model,
            definition.status_code,
        )
        for definition in definitions
        if definition.path.startswith(prefix)
    ) == (
        (prefix, ("GET",), "list_packages", list[MarketplacePackageCatalogEntry], None),
        (
            f"{prefix}/{{plugin_id}}",
            ("GET",),
            "get_package",
            MarketplacePackageDetailResponse,
            None,
        ),
        (
            f"{prefix}/{{plugin_id}}/install",
            ("POST",),
            "install_package",
            MarketplacePackageResponse,
            202,
        ),
        (
            f"{prefix}/{{plugin_id}}/approve",
            ("POST",),
            "approve_package",
            MarketplacePackageApprovalResponse,
            None,
        ),
        (
            f"{prefix}/{{plugin_id}}/revoke",
            ("POST",),
            "revoke_package",
            MarketplacePackageRevocationResponse,
            None,
        ),
        (
            f"{prefix}/{{plugin_id}}/uninstall",
            ("POST",),
            "uninstall_package",
            MarketplacePackageUninstallResponse,
            None,
        ),
    )
    assert {definition.tags for definition in definitions} == {("Plugin Marketplace",)}
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.PLUGIN_MARKETPLACE_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {
        "plugin-marketplace"
    }


def test_plugin_marketplace_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="plugin-marketplace-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.plugin_marketplace_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("plugin-marketplace",)


def test_plugin_marketplace_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_plugin_marketplace_http_routes_definition_v2()

    assert definition.module_ref == subject.PLUGIN_MARKETPLACE_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
