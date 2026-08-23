"""V2-owned production contributions for the builtin instance-files HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import status

from src.infrastructure.adapters.primary.web.routers.instance_files import (
    create_file,
    delete_file,
    download_file,
    list_files,
    preview_file,
    upload_file,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

INSTANCE_FILES_HTTP_ROUTES_ENTRY_V2 = "builtin-instance-files-http-routes"
INSTANCE_FILES_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/instance-files-routes"
INSTANCE_FILES_HTTP_ROUTES_ROW_V2 = "instance-files"
_INSTANCE_FILES_PREFIX_V2 = "/api/v1/instances/{instance_id}/files"


def _instance_file_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=INSTANCE_FILES_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("Instance Files",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=INSTANCE_FILES_HTTP_ROUTES_ROW_V2,
    )


def instance_file_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``instance-files`` inventory row."""
    prefix = _INSTANCE_FILES_PREFIX_V2
    return (
        _instance_file_route_v2(
            path=prefix,
            methods=("GET",),
            endpoint=list_files,
            name="list_files",
            response_model=dict[str, Any],
        ),
        _instance_file_route_v2(
            path=f"{prefix}/{{file_path:path}}/content",
            methods=("GET",),
            endpoint=preview_file,
            name="preview_file",
            response_model=dict[str, Any],
        ),
        _instance_file_route_v2(
            path=f"{prefix}/{{file_path:path}}/download",
            methods=("GET",),
            endpoint=download_file,
            name="download_file",
            response_model=None,
        ),
        _instance_file_route_v2(
            path=prefix,
            methods=("POST",),
            endpoint=create_file,
            name="create_file",
            response_model=dict[str, Any],
            status_code=status.HTTP_201_CREATED,
        ),
        _instance_file_route_v2(
            path=f"{prefix}/upload",
            methods=("POST",),
            endpoint=upload_file,
            name="upload_file",
            response_model=dict[str, Any],
        ),
        _instance_file_route_v2(
            path=f"{prefix}/{{file_path:path}}",
            methods=("DELETE",),
            endpoint=delete_file,
            name="delete_file",
            response_model=None,
            status_code=status.HTTP_204_NO_CONTENT,
        ),
    )


def builtin_instance_files_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register instance-file routes as reversible effects of one V2 Fiber."""
    definitions = instance_file_route_definitions_v2()

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

        await context.effect(setup, label=INSTANCE_FILES_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=INSTANCE_FILES_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(INSTANCE_FILES_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "INSTANCE_FILES_HTTP_ROUTES_ENTRY_V2",
    "INSTANCE_FILES_HTTP_ROUTES_MODULE_V2",
    "INSTANCE_FILES_HTTP_ROUTES_ROW_V2",
    "builtin_instance_files_http_routes_definition_v2",
    "instance_file_route_definitions_v2",
]
