"""Strict full-snapshot transport through the request-pinned schema authority."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.domain.model.project_schema.commands import ReplaceProjectSchema
from src.domain.model.project_schema.transport import (
    MAX_TRANSPORT_BYTES,
    SchemaHistoryQuery,
    SchemaReceiptQuery,
    parse_replace,
    parse_transport,
)
from src.domain.model.project_schema.validation import ProjectSchemaError, closed
from src.infrastructure.adapters.primary.web.cloud_knowledge_sync_generation_v2 import (
    KNOWLEDGE_SYNC_GENERATION_HEADER,
    MAX_GENERATION_HEADER_BYTES,
    cloud_knowledge_sync_generation_payload_v2,
    observe_cloud_knowledge_sync_generation_v2,
    require_cloud_knowledge_sync_generation_v2,
)
from src.infrastructure.adapters.primary.web.schema_application_authority_v2 import (
    SchemaApplicationAuthorityV2,
    schema_application_authority_dependency_v2,
)
from src.infrastructure.i18n import gettext as _

router = APIRouter(prefix="/document")
Authority = Annotated[
    SchemaApplicationAuthorityV2, Depends(schema_application_authority_dependency_v2)
]


def _validate_generation_json(request: Request) -> None:
    values = request.headers.getlist(KNOWLEDGE_SYNC_GENERATION_HEADER)
    try:
        if len(values) > 1:
            raise ValueError("duplicate generation header")
        if values:
            if len(values[0]) > MAX_GENERATION_HEADER_BYTES:
                raise ValueError("generation header exceeds bound")
            _validated = parse_transport(values[0].encode("latin-1"))
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "knowledge_sync_generation_invalid",
                "message": _("Knowledge synchronization generation condition is invalid"),
            },
        ) from error


def _observe_generation(request: Request) -> PluginGenerationDescriptorV2:
    _validate_generation_json(request)
    return observe_cloud_knowledge_sync_generation_v2(request)


def _require_generation(request: Request) -> PluginGenerationDescriptorV2:
    _validate_generation_json(request)
    return require_cloud_knowledge_sync_generation_v2(request)


Observed = Annotated[PluginGenerationDescriptorV2, Depends(_observe_generation)]
Required = Annotated[PluginGenerationDescriptorV2, Depends(_require_generation)]


def _invalid(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "project_schema_transport_invalid",
            "message": _("Project schema request is invalid"),
        },
    )


async def _body(request: Request) -> dict[str, Any]:
    # Full-document CAS and replay identity are exclusively in the closed body.
    if any(
        name in request.headers
        for name in (
            "X-Expected-Revision",
            "Idempotency-Key",
            "X-Project-Schema-Expected-Revision",
            "X-Project-Schema-Change-Id",
        )
    ):
        raise _invalid(ValueError("alternate command headers are not supported"))
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_TRANSPORT_BYTES:
            raise _invalid(ValueError("request too large"))
        raw.extend(chunk)
    try:
        return parse_transport(bytes(raw))
    except ProjectSchemaError as error:
        raise _invalid(error) from error


async def _read_request(request: Request) -> None:
    value = await _body(request)
    try:
        closed(value, set())
    except ProjectSchemaError as error:
        raise _invalid(error) from error


async def _replace_request(request: Request) -> ReplaceProjectSchema:
    value = await _body(request)
    try:
        return parse_replace(value)
    except ProjectSchemaError as error:
        raise _invalid(error) from error


async def _receipt_request(request: Request) -> SchemaReceiptQuery:
    value = await _body(request)
    try:
        return SchemaReceiptQuery.from_value(value)
    except ProjectSchemaError as error:
        raise _invalid(error) from error


async def _history_request(request: Request) -> SchemaHistoryQuery:
    value = await _body(request)
    try:
        return SchemaHistoryQuery.from_value(value)
    except ProjectSchemaError as error:
        raise _invalid(error) from error


async def _call[ResultT](operation: Awaitable[ResultT]) -> ResultT:
    try:
        return await operation
    except ProjectSchemaError as error:
        statuses = {
            "project_schema_access_denied": 403,
            "project_schema_scope_not_found": 404,
            "project_schema_active_required": 409,
            "project_schema_not_active": 409,
            "project_schema_revision_conflict": 409,
            "project_schema_change_id_reused": 409,
            "project_schema_transition_invalid": 409,
            "project_schema_identity_conflict": 409,
            "project_schema_legacy_unrepresentable": 409,
            "project_schema_cursor_invalid": 422,
        }
        if error.code not in statuses:
            raise
        raise HTTPException(
            status_code=statuses[error.code],
            detail={
                "code": error.code,
                "message": _("Project schema command was rejected"),
            },
        ) from error


@router.post("/read", dependencies=[Depends(_read_request)])
async def read_document(_generation: Observed, authority: Authority) -> dict[str, Any]:
    document = await _call(authority.services.documents.read())
    return {
        "document": document.to_dict() if document is not None else None,
        "generation": cloud_knowledge_sync_generation_payload_v2(),
    }


@router.post("/replace")
async def replace_document(
    command: Annotated[ReplaceProjectSchema, Depends(_replace_request)],
    _generation: Required,
    authority: Authority,
) -> Response:
    try:
        _ = command.request_json(authority.services.scope)
    except ProjectSchemaError as error:
        raise _invalid(error) from error
    receipt = await _call(authority.services.documents.replace(command))
    return Response(content=receipt.receipt_json, media_type="application/json")


@router.post("/receipt")
async def lookup_receipt(
    query: Annotated[SchemaReceiptQuery, Depends(_receipt_request)],
    _generation: Required,
    authority: Authority,
) -> Response:
    receipt = await _call(authority.services.documents.receipt(query))
    if receipt is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "project_schema_receipt_not_found",
                "message": _("Project schema receipt not found"),
            },
        )
    return Response(content=receipt.receipt_json, media_type="application/json")


@router.post("/history")
async def read_history(
    query: Annotated[SchemaHistoryQuery, Depends(_history_request)],
    _generation: Required,
    authority: Authority,
) -> Response:
    raw = await _call(authority.services.documents.history(query))
    return Response(content=raw, media_type="application/json")
