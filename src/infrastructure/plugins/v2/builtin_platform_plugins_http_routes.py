"""V2-owned production contributions for the builtin platform plugins HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

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
from src.infrastructure.adapters.primary.web.routers.platform_plugins import (
    approve_platform_plugin_cutover,
    get_platform_plugin_cutover_readiness,
    get_shadow_rollout_evidence,
    get_shadow_rollout_readiness,
    get_snapshot,
    list_platform_plugin_http_routes,
    publish_snapshot,
    reconcile_platform_plugin_http_routes,
    record_data_plane_state,
    revoke_platform_plugin_cutover,
    upsert_platform_plugin_http_route,
)
from src.infrastructure.adapters.primary.web.routers.platform_plugins_v2 import (
    get_current_desired_bundle_set_v2,
    get_distribution_v2,
    get_latest_publication_readiness_v2,
    get_publication_readiness_v2,
    get_route_authority_readiness_v2,
    list_desired_bundle_set_history_v2,
    put_current_desired_bundle_set_v2,
    record_data_plane_state_v2,
    republish_last_ready_v2,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

PLATFORM_PLUGINS_HTTP_ROUTES_ENTRY_V2 = "builtin-platform-plugins-http-routes"
PLATFORM_PLUGINS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/platform-plugins-routes"
PLATFORM_PLUGINS_HTTP_ROUTES_ROW_V2 = "platform-plugins"
_PLATFORM_PLUGINS_PREFIX_V2 = "/api/v1/platform-plugins"
_PLATFORM_PLUGINS_TAGS_V2 = ("Platform Plugins",)
_PROTOCOL_V2_TAGS_V2 = ("Platform Plugins", "Platform Plugins V2")


def _platform_plugins_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object,
    tags: tuple[str, ...],
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=PLATFORM_PLUGINS_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=tags,
        response_model=response_model,
        replaces_builtin_row_id=PLATFORM_PLUGINS_HTTP_ROUTES_ROW_V2,
    )


def platform_plugins_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete nested V2 and frozen V1 ``platform-plugins`` row."""
    prefix = _PLATFORM_PLUGINS_PREFIX_V2
    v2 = f"{prefix}/v2"
    mapping: tuple[
        tuple[
            str,
            tuple[str, ...],
            Callable[..., Any],
            str,
            object,
            tuple[str, ...],
        ],
        ...,
    ] = (
        (
            f"{v2}/desired-bundle-sets/current",
            ("PUT",),
            put_current_desired_bundle_set_v2,
            "put_current_desired_bundle_set_v2",
            PlatformPluginDesiredBundleSetResponseV2,
            _PROTOCOL_V2_TAGS_V2,
        ),
        (
            f"{v2}/desired-bundle-sets/current",
            ("GET",),
            get_current_desired_bundle_set_v2,
            "get_current_desired_bundle_set_v2",
            PlatformPluginDesiredBundleSetResponseV2,
            _PROTOCOL_V2_TAGS_V2,
        ),
        (
            f"{v2}/desired-bundle-sets/history",
            ("GET",),
            list_desired_bundle_set_history_v2,
            "list_desired_bundle_set_history_v2",
            list[PlatformPluginDesiredBundleSetResponseV2],
            _PROTOCOL_V2_TAGS_V2,
        ),
        (
            f"{v2}/distribution",
            ("GET",),
            get_distribution_v2,
            "get_distribution_v2",
            PlatformPluginDistributionResponseV2,
            _PROTOCOL_V2_TAGS_V2,
        ),
        (
            f"{v2}/data-plane-state",
            ("POST",),
            record_data_plane_state_v2,
            "record_data_plane_state_v2",
            PlatformPluginApplyStateResponseV2,
            _PROTOCOL_V2_TAGS_V2,
        ),
        (
            f"{v2}/readiness",
            ("GET",),
            get_latest_publication_readiness_v2,
            "get_latest_publication_readiness_v2",
            PlatformPluginPublicationReadinessResponseV2,
            _PROTOCOL_V2_TAGS_V2,
        ),
        (
            f"{v2}/route-authority/readiness",
            ("GET",),
            get_route_authority_readiness_v2,
            "get_route_authority_readiness_v2",
            PlatformPluginRouteAuthorityReadinessResponseV2,
            _PROTOCOL_V2_TAGS_V2,
        ),
        (
            f"{v2}/publications/{{nonce}}/readiness",
            ("GET",),
            get_publication_readiness_v2,
            "get_publication_readiness_v2",
            PlatformPluginPublicationReadinessResponseV2,
            _PROTOCOL_V2_TAGS_V2,
        ),
        (
            f"{v2}/publications/republish-last-ready",
            ("POST",),
            republish_last_ready_v2,
            "republish_last_ready_v2",
            PlatformPluginPublicationReadinessResponseV2,
            _PROTOCOL_V2_TAGS_V2,
        ),
        (
            f"{prefix}/shadow-rollout",
            ("GET",),
            get_shadow_rollout_evidence,
            "get_shadow_rollout_evidence",
            PlatformPluginShadowRolloutResponse,
            _PLATFORM_PLUGINS_TAGS_V2,
        ),
        (
            f"{prefix}/shadow-rollout/readiness",
            ("GET",),
            get_shadow_rollout_readiness,
            "get_shadow_rollout_readiness",
            PlatformPluginShadowRolloutReadinessResponse,
            _PLATFORM_PLUGINS_TAGS_V2,
        ),
        (
            f"{prefix}/cutover/readiness",
            ("GET",),
            get_platform_plugin_cutover_readiness,
            "get_platform_plugin_cutover_readiness",
            PlatformPluginCutoverReadinessResponse,
            _PLATFORM_PLUGINS_TAGS_V2,
        ),
        (
            f"{prefix}/cutover/approve",
            ("POST",),
            approve_platform_plugin_cutover,
            "approve_platform_plugin_cutover",
            PlatformPluginCutoverApprovalResponse,
            _PLATFORM_PLUGINS_TAGS_V2,
        ),
        (
            f"{prefix}/cutover/revoke",
            ("POST",),
            revoke_platform_plugin_cutover,
            "revoke_platform_plugin_cutover",
            PlatformPluginCutoverRevocationResponse,
            _PLATFORM_PLUGINS_TAGS_V2,
        ),
        (
            f"{prefix}/http-routes",
            ("GET",),
            list_platform_plugin_http_routes,
            "list_platform_plugin_http_routes",
            list[PlatformPluginHttpRouteResponse],
            _PLATFORM_PLUGINS_TAGS_V2,
        ),
        (
            f"{prefix}/http-routes/{{plugin_id}}",
            ("PUT",),
            upsert_platform_plugin_http_route,
            "upsert_platform_plugin_http_route",
            PlatformPluginHttpRouteResponse,
            _PLATFORM_PLUGINS_TAGS_V2,
        ),
        (
            f"{prefix}/http-routes/reconcile",
            ("POST",),
            reconcile_platform_plugin_http_routes,
            "reconcile_platform_plugin_http_routes",
            PlatformPluginHttpRouteReconcileResponse,
            _PLATFORM_PLUGINS_TAGS_V2,
        ),
        (
            f"{prefix}/publish",
            ("POST",),
            publish_snapshot,
            "publish_snapshot",
            PlatformPluginPublishResponse,
            _PLATFORM_PLUGINS_TAGS_V2,
        ),
        (
            f"{prefix}/snapshot",
            ("GET",),
            get_snapshot,
            "get_snapshot",
            PlatformPluginSnapshotResponse,
            _PLATFORM_PLUGINS_TAGS_V2,
        ),
        (
            f"{prefix}/data-plane-state",
            ("POST",),
            record_data_plane_state,
            "record_data_plane_state",
            PlatformPluginApplyStateResponse,
            _PLATFORM_PLUGINS_TAGS_V2,
        ),
    )
    return tuple(
        _platform_plugins_route_v2(
            path=path,
            methods=methods,
            endpoint=endpoint,
            name=name,
            response_model=response_model,
            tags=tags,
        )
        for path, methods, endpoint, name, response_model, tags in mapping
    )


def builtin_platform_plugins_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register platform plugin control-plane routes as reversible V2 effects."""
    definitions = platform_plugins_route_definitions_v2()

    async def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        builder = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
        if not isinstance(builder, RouteTableBuilderV2):
            raise RuntimeV2Error(
                "invalid_route_table_builder",
                "route_table inject is not a protocol v2 route table builder",
            )

        async def setup() -> tuple[Callable[[], Awaitable[None]], ...]:
            disposers: list[Callable[[], Awaitable[None]]] = []
            try:
                for definition in definitions:
                    disposers.append(builder.contribute(definition))
            except Exception:
                for dispose in reversed(disposers):
                    await dispose()
                raise
            return tuple(disposers)

        await context.effect(setup, label=PLATFORM_PLUGINS_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=PLATFORM_PLUGINS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(PLATFORM_PLUGINS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "PLATFORM_PLUGINS_HTTP_ROUTES_ENTRY_V2",
    "PLATFORM_PLUGINS_HTTP_ROUTES_MODULE_V2",
    "PLATFORM_PLUGINS_HTTP_ROUTES_ROW_V2",
    "builtin_platform_plugins_http_routes_definition_v2",
    "platform_plugins_route_definitions_v2",
]
