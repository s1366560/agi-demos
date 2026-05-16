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
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.instance_file_service import (
    InstanceFileService,
)
from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user_tenant,
    get_db,
)
from src.infrastructure.adapters.primary.web.routers.http_headers import (
    content_disposition_attachment,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/instances", tags=["Instance Files"])


def _get_file_service() -> InstanceFileService:
    return InstanceFileService()


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """Get DI container with database session for the current request."""
    app_container: DIContainer = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container.redis_client,
    )


async def _ensure_instance_file_access(
    request: Request,
    db: AsyncSession,
    instance_id: str,
    tenant_id: str,
) -> None:
    container = get_container_with_db(request, db)
    service = container.instance_service()
    instance = await service.get_instance(instance_id)
    if instance is None or getattr(instance, "tenant_id", None) != tenant_id:
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
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _ensure_instance_file_access(request, db, instance_id, tenant_id)
    svc = _get_file_service()
    tree = await svc.list_tree(instance_id)
    return {"tree": [asdict(n) for n in tree]}


@router.get("/{instance_id}/files/{file_path:path}/content")
async def preview_file(
    instance_id: str,
    file_path: str,
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _ensure_instance_file_access(request, db, instance_id, tenant_id)
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
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download a file as binary."""
    await _ensure_instance_file_access(request, db, instance_id, tenant_id)
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
            "Content-Disposition": content_disposition_attachment(filename),
        },
    )


@router.post("/{instance_id}/files", status_code=status.HTTP_201_CREATED)
async def create_file(
    instance_id: str,
    body: CreateFileRequest,
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _ensure_instance_file_access(request, db, instance_id, tenant_id)
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
    request: Request,
    file: UploadFile,
    directory: str = Form(""),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _ensure_instance_file_access(request, db, instance_id, tenant_id)
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
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a file or folder."""
    await _ensure_instance_file_access(request, db, instance_id, tenant_id)
    svc = _get_file_service()
    try:
        await svc.delete(instance_id, file_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
