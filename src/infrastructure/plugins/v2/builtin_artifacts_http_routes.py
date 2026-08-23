"""V2-owned production contributions for the builtin artifacts HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.routers.artifacts import (
    ArtifactContentBodyLimitRoute,
    ArtifactContentResponse,
    ArtifactListResponse,
    ArtifactResponse,
    RefreshUrlResponse,
    UpdateContentResponse,
    delete_artifact,
    download_artifact,
    get_artifact,
    get_artifact_content,
    get_artifact_content_bytes,
    list_artifacts,
    list_categories,
    refresh_artifact_url,
    update_artifact_content,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

ARTIFACTS_HTTP_ROUTES_ENTRY_V2 = "builtin-artifacts-http-routes"
ARTIFACTS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/artifacts-routes"
ARTIFACTS_HTTP_ROUTES_ROW_V2 = "artifacts"
_ARTIFACTS_PREFIX_V2 = "/api/v1/artifacts"


def _artifact_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=ARTIFACTS_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("artifacts",),
        response_model=response_model,
        route_class_override=ArtifactContentBodyLimitRoute,
        replaces_builtin_row_id=ARTIFACTS_HTTP_ROUTES_ROW_V2,
    )


def artifact_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``artifacts`` inventory row."""
    prefix = _ARTIFACTS_PREFIX_V2
    return (
        _artifact_route_v2(
            path=prefix,
            methods=("GET",),
            endpoint=list_artifacts,
            name="list_artifacts",
            response_model=ArtifactListResponse,
        ),
        _artifact_route_v2(
            path=f"{prefix}/{{artifact_id}}",
            methods=("GET",),
            endpoint=get_artifact,
            name="get_artifact",
            response_model=ArtifactResponse,
        ),
        _artifact_route_v2(
            path=f"{prefix}/{{artifact_id}}/download",
            methods=("GET",),
            endpoint=download_artifact,
            name="download_artifact",
            response_model=None,
        ),
        _artifact_route_v2(
            path=f"{prefix}/{{artifact_id}}/content",
            methods=("GET",),
            endpoint=get_artifact_content,
            name="get_artifact_content",
            response_model=ArtifactContentResponse,
        ),
        _artifact_route_v2(
            path=f"{prefix}/{{artifact_id}}/content/bytes",
            methods=("GET",),
            endpoint=get_artifact_content_bytes,
            name="get_artifact_content_bytes",
            response_model=None,
        ),
        _artifact_route_v2(
            path=f"{prefix}/{{artifact_id}}/refresh-url",
            methods=("POST",),
            endpoint=refresh_artifact_url,
            name="refresh_artifact_url",
            response_model=RefreshUrlResponse,
        ),
        _artifact_route_v2(
            path=f"{prefix}/{{artifact_id}}/content",
            methods=("PUT",),
            endpoint=update_artifact_content,
            name="update_artifact_content",
            response_model=UpdateContentResponse,
        ),
        _artifact_route_v2(
            path=f"{prefix}/{{artifact_id}}",
            methods=("DELETE",),
            endpoint=delete_artifact,
            name="delete_artifact",
            response_model=dict[str, Any],
        ),
        _artifact_route_v2(
            path=f"{prefix}/categories/list",
            methods=("GET",),
            endpoint=list_categories,
            name="list_categories",
            response_model=dict[str, Any],
        ),
    )


def builtin_artifacts_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register artifact routes as reversible effects of one V2 Fiber."""
    definitions = artifact_route_definitions_v2()

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

        await context.effect(setup, label=ARTIFACTS_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=ARTIFACTS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ARTIFACTS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "ARTIFACTS_HTTP_ROUTES_ENTRY_V2",
    "ARTIFACTS_HTTP_ROUTES_MODULE_V2",
    "ARTIFACTS_HTTP_ROUTES_ROW_V2",
    "artifact_route_definitions_v2",
    "builtin_artifacts_http_routes_definition_v2",
]
