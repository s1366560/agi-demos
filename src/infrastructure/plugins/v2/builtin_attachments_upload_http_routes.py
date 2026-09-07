"""V2-owned production contributions for the builtin attachment-upload HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.routers.attachments_upload import (
    AttachmentListResponse,
    AttachmentResponse,
    InitiateUploadResponse,
    UploadPartResponse,
    abort_multipart_upload,
    complete_multipart_upload,
    delete_attachment,
    download_attachment,
    get_attachment,
    initiate_multipart_upload,
    list_attachments,
    upload_part,
    upload_simple,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

ATTACHMENTS_UPLOAD_HTTP_ROUTES_ENTRY_V2 = "builtin-attachments-upload-http-routes"
ATTACHMENTS_UPLOAD_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/attachments-upload-routes"
ATTACHMENTS_UPLOAD_HTTP_ROUTES_ROW_V2 = "attachments-upload"
_ATTACHMENTS_PREFIX_V2 = "/api/v1/attachments"


def _attachments_upload_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=ATTACHMENTS_UPLOAD_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("attachments",),
        response_model=response_model,
        replaces_builtin_row_id=ATTACHMENTS_UPLOAD_HTTP_ROUTES_ROW_V2,
    )


def attachments_upload_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``attachments-upload`` inventory row."""
    return (
        _attachments_upload_route_v2(
            path=f"{_ATTACHMENTS_PREFIX_V2}/upload/initiate",
            methods=("POST",),
            endpoint=initiate_multipart_upload,
            name="initiate_multipart_upload",
            response_model=InitiateUploadResponse,
        ),
        _attachments_upload_route_v2(
            path=f"{_ATTACHMENTS_PREFIX_V2}/upload/part",
            methods=("POST",),
            endpoint=upload_part,
            name="upload_part",
            response_model=UploadPartResponse,
        ),
        _attachments_upload_route_v2(
            path=f"{_ATTACHMENTS_PREFIX_V2}/upload/complete",
            methods=("POST",),
            endpoint=complete_multipart_upload,
            name="complete_multipart_upload",
            response_model=AttachmentResponse,
        ),
        _attachments_upload_route_v2(
            path=f"{_ATTACHMENTS_PREFIX_V2}/upload/abort",
            methods=("POST",),
            endpoint=abort_multipart_upload,
            name="abort_multipart_upload",
            response_model=dict[str, Any],
        ),
        _attachments_upload_route_v2(
            path=f"{_ATTACHMENTS_PREFIX_V2}/upload/simple",
            methods=("POST",),
            endpoint=upload_simple,
            name="upload_simple",
            response_model=AttachmentResponse,
        ),
        _attachments_upload_route_v2(
            path=_ATTACHMENTS_PREFIX_V2,
            methods=("GET",),
            endpoint=list_attachments,
            name="list_attachments",
            response_model=AttachmentListResponse,
        ),
        _attachments_upload_route_v2(
            path=f"{_ATTACHMENTS_PREFIX_V2}/{{attachment_id}}",
            methods=("GET",),
            endpoint=get_attachment,
            name="get_attachment",
            response_model=AttachmentResponse,
        ),
        _attachments_upload_route_v2(
            path=f"{_ATTACHMENTS_PREFIX_V2}/{{attachment_id}}/download",
            methods=("GET",),
            endpoint=download_attachment,
            name="download_attachment",
            response_model=None,
        ),
        _attachments_upload_route_v2(
            path=f"{_ATTACHMENTS_PREFIX_V2}/{{attachment_id}}",
            methods=("DELETE",),
            endpoint=delete_attachment,
            name="delete_attachment",
            response_model=dict[str, Any],
        ),
    )


def builtin_attachments_upload_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register attachment upload routes as reversible effects of one V2 Fiber."""
    definitions = attachments_upload_route_definitions_v2()

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

        await context.effect(setup, label=ATTACHMENTS_UPLOAD_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=ATTACHMENTS_UPLOAD_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ATTACHMENTS_UPLOAD_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "ATTACHMENTS_UPLOAD_HTTP_ROUTES_ENTRY_V2",
    "ATTACHMENTS_UPLOAD_HTTP_ROUTES_MODULE_V2",
    "ATTACHMENTS_UPLOAD_HTTP_ROUTES_ROW_V2",
    "attachments_upload_route_definitions_v2",
    "builtin_attachments_upload_http_routes_definition_v2",
]
