"""Production V2 ownership tests for the builtin platform plugins HTTP row."""

from __future__ import annotations

import pytest

from src.application.schemas.platform_plugins import (
    PlatformPluginApplyStateResponse,
    PlatformPluginApplyStateResponseV2,
    PlatformPluginCutoverApprovalResponse,
    PlatformPluginCutoverReadinessResponse,
    PlatformPluginCutoverRevocationResponse,
    PlatformPluginDesiredBundleSetResponseV2,
    PlatformPluginDistributionResponseV2,
    PlatformPluginHttpRouteReconcileResponse,
    PlatformPluginHttpRouteResponse,
    PlatformPluginPublicationReadinessResponseV2,
    PlatformPluginPublishResponse,
    PlatformPluginRouteAuthorityReadinessResponseV2,
    PlatformPluginShadowRolloutReadinessResponse,
    PlatformPluginShadowRolloutResponse,
    PlatformPluginSnapshotResponse,
)
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_platform_plugins_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2

pytestmark = pytest.mark.unit


def test_platform_plugins_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.platform_plugins_route_definitions_v2()
    prefix = "/api/v1/platform-plugins"
    v2 = f"{prefix}/v2"

    assert tuple(
        (definition.path, definition.methods, definition.name, definition.response_model)
        for definition in definitions
    ) == (
        (
            f"{v2}/desired-bundle-sets/current",
            ("PUT",),
            "put_current_desired_bundle_set_v2",
            PlatformPluginDesiredBundleSetResponseV2,
        ),
        (
            f"{v2}/desired-bundle-sets/current",
            ("GET",),
            "get_current_desired_bundle_set_v2",
            PlatformPluginDesiredBundleSetResponseV2,
        ),
        (
            f"{v2}/desired-bundle-sets/history",
            ("GET",),
            "list_desired_bundle_set_history_v2",
            list[PlatformPluginDesiredBundleSetResponseV2],
        ),
        (
            f"{v2}/distribution",
            ("GET",),
            "get_distribution_v2",
            PlatformPluginDistributionResponseV2,
        ),
        (
            f"{v2}/data-plane-state",
            ("POST",),
            "record_data_plane_state_v2",
            PlatformPluginApplyStateResponseV2,
        ),
        (
            f"{v2}/readiness",
            ("GET",),
            "get_latest_publication_readiness_v2",
            PlatformPluginPublicationReadinessResponseV2,
        ),
        (
            f"{v2}/route-authority/readiness",
            ("GET",),
            "get_route_authority_readiness_v2",
            PlatformPluginRouteAuthorityReadinessResponseV2,
        ),
        (
            f"{v2}/publications/{{nonce}}/readiness",
            ("GET",),
            "get_publication_readiness_v2",
            PlatformPluginPublicationReadinessResponseV2,
        ),
        (
            f"{v2}/publications/republish-last-ready",
            ("POST",),
            "republish_last_ready_v2",
            PlatformPluginPublicationReadinessResponseV2,
        ),
        (
            f"{prefix}/shadow-rollout",
            ("GET",),
            "get_shadow_rollout_evidence",
            PlatformPluginShadowRolloutResponse,
        ),
        (
            f"{prefix}/shadow-rollout/readiness",
            ("GET",),
            "get_shadow_rollout_readiness",
            PlatformPluginShadowRolloutReadinessResponse,
        ),
        (
            f"{prefix}/cutover/readiness",
            ("GET",),
            "get_platform_plugin_cutover_readiness",
            PlatformPluginCutoverReadinessResponse,
        ),
        (
            f"{prefix}/cutover/approve",
            ("POST",),
            "approve_platform_plugin_cutover",
            PlatformPluginCutoverApprovalResponse,
        ),
        (
            f"{prefix}/cutover/revoke",
            ("POST",),
            "revoke_platform_plugin_cutover",
            PlatformPluginCutoverRevocationResponse,
        ),
        (
            f"{prefix}/http-routes",
            ("GET",),
            "list_platform_plugin_http_routes",
            list[PlatformPluginHttpRouteResponse],
        ),
        (
            f"{prefix}/http-routes/{{plugin_id}}",
            ("PUT",),
            "upsert_platform_plugin_http_route",
            PlatformPluginHttpRouteResponse,
        ),
        (
            f"{prefix}/http-routes/reconcile",
            ("POST",),
            "reconcile_platform_plugin_http_routes",
            PlatformPluginHttpRouteReconcileResponse,
        ),
        (
            f"{prefix}/publish",
            ("POST",),
            "publish_snapshot",
            PlatformPluginPublishResponse,
        ),
        (
            f"{prefix}/snapshot",
            ("GET",),
            "get_snapshot",
            PlatformPluginSnapshotResponse,
        ),
        (
            f"{prefix}/data-plane-state",
            ("POST",),
            "record_data_plane_state",
            PlatformPluginApplyStateResponse,
        ),
    )
    assert (
        tuple(definition.tags for definition in definitions[:9])
        == (("Platform Plugins", "Platform Plugins V2"),) * 9
    )
    assert tuple(definition.tags for definition in definitions[9:]) == (("Platform Plugins",),) * 11
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.PLATFORM_PLUGINS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {
        "platform-plugins"
    }


def test_platform_plugins_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="platform-plugins-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.platform_plugins_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("platform-plugins",)


def test_platform_plugins_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_platform_plugins_http_routes_definition_v2()

    assert definition.module_ref == subject.PLATFORM_PLUGINS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
