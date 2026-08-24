"""Production V2 ownership tests for the builtin platform plugins HTTP row."""

from __future__ import annotations

import pytest

from src.application.schemas.platform_plugins import (
    PlatformPluginApplyStateResponseV2,
    PlatformPluginDesiredBundleSetResponseV2,
    PlatformPluginDistributionResponseV2,
    PlatformPluginPublicationReadinessResponseV2,
    PlatformPluginRouteAuthorityReadinessResponseV2,
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
            prefix,
            ("GET", "POST", "PUT", "PATCH", "DELETE"),
            "retired_plugin_protocol_v1_root_route",
            None,
        ),
        (
            f"{prefix}/{{legacy_path:path}}",
            ("GET", "POST", "PUT", "PATCH", "DELETE"),
            "retired_plugin_protocol_v1_route",
            None,
        ),
    )
    assert (
        tuple(definition.tags for definition in definitions[:9])
        == (("Platform Plugins", "Platform Plugins V2"),) * 9
    )
    assert tuple(definition.tags for definition in definitions[9:]) == (
        ("Platform Plugins",),
        ("Platform Plugins",),
    )
    assert all(definition.include_in_schema is False for definition in definitions[-2:])
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
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.platform_plugins_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("platform-plugins",)


def test_platform_plugins_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_platform_plugins_http_routes_definition_v2()

    assert definition.module_ref == subject.PLATFORM_PLUGINS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
