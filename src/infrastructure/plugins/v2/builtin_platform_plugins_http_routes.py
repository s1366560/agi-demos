"""V2-owned production contributions for the builtin platform plugins HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.application.schemas.platform_plugins import (
    PlatformPluginApplyStateResponseV2,
    PlatformPluginDataPlaneCredentialIssuedResponseV2,
    PlatformPluginDataPlaneCredentialResponseV2,
    PlatformPluginDesiredBundleSetResponseV2,
    PlatformPluginDistributionResponseV2,
    PlatformPluginPublicationReadinessResponseV2,
    PlatformPluginRouteAuthorityReadinessResponseV2,
)
from src.infrastructure.adapters.primary.web.routers.platform_plugins import (
    retired_plugin_protocol_v1_root_route,
    retired_plugin_protocol_v1_route,
)
from src.infrastructure.adapters.primary.web.routers.platform_plugins_v2 import (
    get_current_desired_bundle_set_v2,
    get_distribution_v2,
    get_latest_publication_readiness_v2,
    get_publication_readiness_v2,
    get_route_authority_readiness_v2,
    get_web_public_view_v2,
    issue_data_plane_credential_v2,
    list_data_plane_credentials_v2,
    list_desired_bundle_set_history_v2,
    put_current_desired_bundle_set_v2,
    record_data_plane_state_v2,
    republish_last_ready_v2,
    revoke_data_plane_credential_v2,
    rotate_data_plane_credential_v2,
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
_PROTOCOL_V2_TAGS_V2 = ("Platform Plugins", "Platform Plugins V2")


def _platform_plugins_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object,
    tags: tuple[str, ...],
    status_code: int | None = None,
    include_in_schema: bool = True,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=PLATFORM_PLUGINS_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=tags,
        status_code=status_code,
        response_model=response_model,
        include_in_schema=include_in_schema,
        replaces_builtin_row_id=PLATFORM_PLUGINS_HTTP_ROUTES_ROW_V2,
    )


def platform_plugins_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return exact V2 routes followed by explicit V1 retirement traps."""
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
            f"{v2}/data-plane-credentials",
            ("POST",),
            issue_data_plane_credential_v2,
            "issue_data_plane_credential_v2",
            PlatformPluginDataPlaneCredentialIssuedResponseV2,
            _PROTOCOL_V2_TAGS_V2,
        ),
        (
            f"{v2}/data-plane-credentials",
            ("GET",),
            list_data_plane_credentials_v2,
            "list_data_plane_credentials_v2",
            list[PlatformPluginDataPlaneCredentialResponseV2],
            _PROTOCOL_V2_TAGS_V2,
        ),
        (
            f"{v2}/data-plane-credentials/{{credential_id}}/rotate",
            ("POST",),
            rotate_data_plane_credential_v2,
            "rotate_data_plane_credential_v2",
            PlatformPluginDataPlaneCredentialIssuedResponseV2,
            _PROTOCOL_V2_TAGS_V2,
        ),
        (
            f"{v2}/data-plane-credentials/{{credential_id}}",
            ("DELETE",),
            revoke_data_plane_credential_v2,
            "revoke_data_plane_credential_v2",
            PlatformPluginDataPlaneCredentialResponseV2,
            _PROTOCOL_V2_TAGS_V2,
        ),
        (
            f"{v2}/web-view",
            ("GET",),
            get_web_public_view_v2,
            "get_web_public_view_v2",
            dict[str, Any],
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
    )
    v2_routes = tuple(
        _platform_plugins_route_v2(
            path=path,
            methods=methods,
            endpoint=endpoint,
            name=name,
            response_model=response_model,
            tags=tags,
            status_code=(
                201
                if endpoint in {issue_data_plane_credential_v2, rotate_data_plane_credential_v2}
                else None
            ),
        )
        for path, methods, endpoint, name, response_model, tags in mapping
    )
    retired_v1_root = _platform_plugins_route_v2(
        path=prefix,
        methods=("GET", "POST", "PUT", "PATCH", "DELETE"),
        endpoint=retired_plugin_protocol_v1_root_route,
        name="retired_plugin_protocol_v1_root_route",
        response_model=None,
        tags=("Platform Plugins",),
        include_in_schema=False,
    )
    retired_v1_descendants = _platform_plugins_route_v2(
        path=f"{prefix}/{{legacy_path:path}}",
        methods=("GET", "POST", "PUT", "PATCH", "DELETE"),
        endpoint=retired_plugin_protocol_v1_route,
        name="retired_plugin_protocol_v1_route",
        response_model=None,
        tags=("Platform Plugins",),
        include_in_schema=False,
    )
    return (*v2_routes, retired_v1_root, retired_v1_descendants)


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
