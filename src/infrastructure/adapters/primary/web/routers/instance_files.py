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

from src.application.services.instance_file_service import (
    InstanceFileService,
)
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user_tenant,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/instances", tags=["Instance Files"])


def _get_file_service() -> InstanceFileService:
    return InstanceFileService()


class CreateFileRequest(BaseModel):
    """Request body for creating a file or folder."""

    path: str
    type: str


@router.get("/{instance_id}/files")
async def list_files(
    instance_id: str,
    _tenant_id: str = Depends(get_current_user_tenant),
) -> dict[str, Any]:
    svc = _get_file_service()
    tree = await svc.list_tree(instance_id)
    return {"tree": [asdict(n) for n in tree]}


@router.get("/{instance_id}/files/{file_path:path}/content")
async def preview_file(
    instance_id: str,
    file_path: str,
    _tenant_id: str = Depends(get_current_user_tenant),
) -> dict[str, Any]:
    svc = _get_file_service()
    try:
        content = await svc.read_content(instance_id, file_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return {"content": content}


@router.get("/{instance_id}/files/{file_path:path}/download")
async def download_file(
    instance_id: str,
    file_path: str,
    _tenant_id: str = Depends(get_current_user_tenant),
) -> Response:
    """Download a file as binary."""
    svc = _get_file_service()
    try:
        data, filename, mime = await svc.read_bytes(instance_id, file_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return Response(
        content=data,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/{instance_id}/files", status_code=status.HTTP_201_CREATED)
async def create_file(
    instance_id: str,
    body: CreateFileRequest,
    _tenant_id: str = Depends(get_current_user_tenant),
) -> dict[str, Any]:
    svc = _get_file_service()
    try:
        node = await svc.create(instance_id, body.path, body.type)
    except FileExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return asdict(node)


@router.post("/{instance_id}/files/upload")
async def upload_file(
    instance_id: str,
    file: UploadFile,
    directory: str = Form(""),
    _tenant_id: str = Depends(get_current_user_tenant),
) -> dict[str, Any]:
    svc = _get_file_service()
    content = await file.read()
    filename = file.filename or "unnamed"
    try:
        node = await svc.upload(instance_id, directory, filename, content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return asdict(node)


@router.delete(
    "/{instance_id}/files/{file_path:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_file(
    instance_id: str,
    file_path: str,
    _tenant_id: str = Depends(get_current_user_tenant),
) -> None:
    """Delete a file or folder."""
    svc = _get_file_service()
    try:
        await svc.delete(instance_id, file_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
