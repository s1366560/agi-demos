"""Instance File Management API endpoints."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel

from src.infrastructure.adapters.primary.web.instance_file_application_authority_v2 import (
    InstanceFileApplicationAuthorityV2,
    instance_file_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.http_headers import (
    content_disposition_attachment,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/instances", tags=["Instance Files"])


def _file_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_("File not found"),
    )


def _invalid_file_request_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_("Invalid file request"),
    )


def _file_conflict_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=_("File already exists"),
    )


async def _ensure_instance_file_access(
    authority: InstanceFileApplicationAuthorityV2,
    instance_id: str,
) -> None:
    instance = await authority.services.instance.get_instance(instance_id)
    if instance is None or getattr(instance, "tenant_id", None) != authority.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Instance not found"),
        )


class CreateFileRequest(BaseModel):
    """Request body for creating a file or folder."""

    path: str
    type: str


@router.get("/{instance_id}/files")
async def list_files(
    instance_id: str,
    authority: InstanceFileApplicationAuthorityV2 = Depends(
        instance_file_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    await _ensure_instance_file_access(authority, instance_id)
    svc = authority.services.files
    tree = await svc.list_tree(instance_id)
    return {"tree": [asdict(n) for n in tree]}


@router.get("/{instance_id}/files/{file_path:path}/content")
async def preview_file(
    instance_id: str,
    file_path: str,
    authority: InstanceFileApplicationAuthorityV2 = Depends(
        instance_file_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    await _ensure_instance_file_access(authority, instance_id)
    svc = authority.services.files
    try:
        content = await svc.read_content(instance_id, file_path)
    except FileNotFoundError as exc:
        raise _file_not_found_error() from exc
    except ValueError as exc:
        raise _invalid_file_request_error() from exc
    return {"content": content}


@router.get("/{instance_id}/files/{file_path:path}/download")
async def download_file(
    instance_id: str,
    file_path: str,
    authority: InstanceFileApplicationAuthorityV2 = Depends(
        instance_file_application_authority_dependency_v2
    ),
) -> Response:
    """Download a file as binary."""
    await _ensure_instance_file_access(authority, instance_id)
    svc = authority.services.files
    try:
        data, filename, mime = await svc.read_bytes(instance_id, file_path)
    except FileNotFoundError as exc:
        raise _file_not_found_error() from exc
    return Response(
        content=data,
        media_type=mime,
        headers={
            "Content-Disposition": content_disposition_attachment(filename),
        },
    )


@router.post("/{instance_id}/files", status_code=status.HTTP_201_CREATED)
async def create_file(
    instance_id: str,
    body: CreateFileRequest,
    authority: InstanceFileApplicationAuthorityV2 = Depends(
        instance_file_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    await _ensure_instance_file_access(authority, instance_id)
    svc = authority.services.files
    try:
        node = await svc.create(instance_id, body.path, body.type)
    except FileExistsError as exc:
        raise _file_conflict_error() from exc
    except ValueError as exc:
        raise _invalid_file_request_error() from exc
    return asdict(node)


@router.post("/{instance_id}/files/upload")
async def upload_file(
    instance_id: str,
    file: UploadFile,
    directory: str = Form(""),
    authority: InstanceFileApplicationAuthorityV2 = Depends(
        instance_file_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    await _ensure_instance_file_access(authority, instance_id)
    svc = authority.services.files
    content = await file.read()
    filename = file.filename or "unnamed"
    try:
        node = await svc.upload(instance_id, directory, filename, content)
    except ValueError as exc:
        raise _invalid_file_request_error() from exc
    return asdict(node)


@router.delete(
    "/{instance_id}/files/{file_path:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_file(
    instance_id: str,
    file_path: str,
    authority: InstanceFileApplicationAuthorityV2 = Depends(
        instance_file_application_authority_dependency_v2
    ),
) -> None:
    """Delete a file or folder."""
    await _ensure_instance_file_access(authority, instance_id)
    svc = authority.services.files
    try:
        await svc.delete(instance_id, file_path)
    except FileNotFoundError as exc:
        raise _file_not_found_error() from exc
