"""Workspace blackboard API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.blackboard_file_service import BlackboardFileService
from src.application.services.blackboard_service import BlackboardService
from src.application.services.workspace_surface_contract import (
    AUTHORITY_CLASS_KEY,
    BLACKBOARD_OWNERSHIP_METADATA,
    SURFACE_BOUNDARY_KEY,
)
from src.configuration.di_container import DIContainer
from src.domain.events.types import AgentEventType
from src.domain.model.workspace.blackboard_file import BlackboardFile
from src.domain.model.workspace.blackboard_post import BlackboardPost, BlackboardPostStatus
from src.domain.model.workspace.blackboard_reply import BlackboardReply
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.workspace_events import publish_workspace_event
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard",
    tags=["blackboard"],
)

def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    app_container = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container._redis_client,
    )


def _service_from_request(request: Request, db: AsyncSession) -> BlackboardService:
    return get_container_with_db(request, db).blackboard_service()


def _blackboard_event_metadata(tenant_id: str, project_id: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        **BLACKBOARD_OWNERSHIP_METADATA,
    }


def _blackboard_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        SURFACE_BOUNDARY_KEY: BLACKBOARD_OWNERSHIP_METADATA[SURFACE_BOUNDARY_KEY],
        AUTHORITY_CLASS_KEY: BLACKBOARD_OWNERSHIP_METADATA[AUTHORITY_CLASS_KEY],
    }


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ValueError):
        message = str(exc)
        if "not found" in message:
            return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


class BlackboardPostCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    status: BlackboardPostStatus = BlackboardPostStatus.OPEN
    is_pinned: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class BlackboardPostUpdateRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    content: str | None = Field(None, min_length=1)
    status: BlackboardPostStatus | None = None
    is_pinned: bool | None = None
    metadata: dict[str, Any] | None = None


class BlackboardReplyCreateRequest(BaseModel):
    content: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BlackboardReplyUpdateRequest(BaseModel):
    content: str = Field(..., min_length=1)
    metadata: dict[str, Any] | None = None


class BlackboardPostResponse(BaseModel):
    id: str
    workspace_id: str
    author_id: str
    title: str
    content: str
    status: str
    is_pinned: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime | None


class BlackboardReplyResponse(BaseModel):
    id: str
    post_id: str
    workspace_id: str
    author_id: str
    content: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime | None


class BlackboardPostListResponse(BaseModel):
    items: list[BlackboardPostResponse]


class BlackboardReplyListResponse(BaseModel):
    items: list[BlackboardReplyResponse]


def _to_post_response(post: BlackboardPost) -> BlackboardPostResponse:
    return BlackboardPostResponse(
        id=post.id,
        workspace_id=post.workspace_id,
        author_id=post.author_id,
        title=post.title,
        content=post.content,
        status=post.status.value,
        is_pinned=post.is_pinned,
        metadata=post.metadata,
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


def _to_reply_response(reply: BlackboardReply) -> BlackboardReplyResponse:
    return BlackboardReplyResponse(
        id=reply.id,
        post_id=reply.post_id,
        workspace_id=reply.workspace_id,
        author_id=reply.author_id,
        content=reply.content,
        metadata=reply.metadata,
        created_at=reply.created_at,
        updated_at=reply.updated_at,
    )


@router.post("/posts", response_model=BlackboardPostResponse, status_code=status.HTTP_201_CREATED)
async def create_post(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    payload: BlackboardPostCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BlackboardPostResponse:
    service = _service_from_request(request, db)
    try:
        post = await service.create_post(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            title=payload.title,
            content=payload.content,
            status=payload.status,
            is_pinned=payload.is_pinned,
            metadata=payload.metadata,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.BLACKBOARD_POST_CREATED,
            payload=_blackboard_event_payload(
                {
                    "workspace_id": workspace_id,
                    "post_id": post.id,
                    "author_id": post.author_id,
                    "title": post.title,
                    "status": post.status.value,
                    "is_pinned": post.is_pinned,
                }
            ),
            metadata=_blackboard_event_metadata(tenant_id, project_id),
        )
        return _to_post_response(post)
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


@router.get("/posts", response_model=BlackboardPostListResponse)
async def list_posts(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BlackboardPostListResponse:
    service = _service_from_request(request, db)
    try:
        posts = await service.list_posts(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
        return BlackboardPostListResponse(items=[_to_post_response(post) for post in posts])
    except Exception as exc:
        raise _map_error(exc) from exc


@router.get("/posts/{post_id}", response_model=BlackboardPostResponse)
async def get_post(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    post_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BlackboardPostResponse:
    service = _service_from_request(request, db)
    try:
        post = await service.get_post(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            post_id=post_id,
            actor_user_id=current_user.id,
        )
        return _to_post_response(post)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.patch("/posts/{post_id}", response_model=BlackboardPostResponse)
async def update_post(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    post_id: str,
    payload: BlackboardPostUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BlackboardPostResponse:
    service = _service_from_request(request, db)
    try:
        post = await service.update_post(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            post_id=post_id,
            actor_user_id=current_user.id,
            title=payload.title,
            content=payload.content,
            status=payload.status,
            is_pinned=payload.is_pinned,
            metadata=payload.metadata,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.BLACKBOARD_POST_UPDATED,
            payload=_blackboard_event_payload(
                {
                    "post": _to_post_response(post).model_dump(mode="json"),
                }
            ),
            metadata=_blackboard_event_metadata(tenant_id, project_id),
        )
        return _to_post_response(post)
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


@router.delete("/posts/{post_id}")
async def delete_post(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    post_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    service = _service_from_request(request, db)
    try:
        deleted = await service.delete_post(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            post_id=post_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.BLACKBOARD_POST_DELETED,
            payload=_blackboard_event_payload({"post_id": post_id}),
            metadata=_blackboard_event_metadata(tenant_id, project_id),
        )
        return {"success": deleted}
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


# --- Blackboard Files ---


class BlackboardFileResponse(BaseModel):
    id: str
    workspace_id: str
    parent_path: str
    name: str
    is_directory: bool
    file_size: int
    content_type: str
    uploader_type: str
    uploader_id: str
    uploader_name: str
    created_at: datetime


class BlackboardFileListResponse(BaseModel):
    items: list[BlackboardFileResponse]


class MkdirRequest(BaseModel):
    parent_path: str = Field("/", description="Parent directory path")
    name: str = Field(..., min_length=1, max_length=255)


def _file_service_from_request(request: Request, db: AsyncSession) -> BlackboardFileService:
    container = get_container_with_db(request, db)
    return container.blackboard_file_service()


def _to_file_response(f: BlackboardFile) -> BlackboardFileResponse:
    return BlackboardFileResponse(
        id=f.id,
        workspace_id=f.workspace_id,
        parent_path=f.parent_path,
        name=f.name,
        is_directory=f.is_directory,
        file_size=f.file_size,
        content_type=f.content_type,
        uploader_type=f.uploader_type,
        uploader_id=f.uploader_id,
        uploader_name=f.uploader_name,
        created_at=f.created_at,
    )


@router.get("/files", response_model=BlackboardFileListResponse)
async def list_files(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    request: Request,
    parent_path: str = Query("/"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BlackboardFileListResponse:
    service = _file_service_from_request(request, db)
    try:
        files = await service.list_files(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            parent_path=parent_path,
        )
        return BlackboardFileListResponse(items=[_to_file_response(f) for f in files])
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post(
    "/files/mkdir",
    response_model=BlackboardFileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_directory(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    payload: MkdirRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BlackboardFileResponse:
    service = _file_service_from_request(request, db)
    try:
        directory = await service.create_directory(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            parent_path=payload.parent_path,
            name=payload.name,
        )
        await db.commit()
        return _to_file_response(directory)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post(
    "/files/upload",
    response_model=BlackboardFileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    request: Request,
    file: UploadFile = File(...),
    parent_path: str = Form("/"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BlackboardFileResponse:
    service = _file_service_from_request(request, db)
    content = await file.read()
    try:
        bb_file = await service.upload_file(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            actor_user_name=current_user.full_name or current_user.email,
            parent_path=parent_path,
            filename=file.filename or "unnamed",
            content=content,
        )
        await db.commit()
        return _to_file_response(bb_file)
    except Exception as exc:
        raise _map_error(exc) from exc


@router.get("/files/{file_id}/download")
async def download_file(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    file_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    service = _file_service_from_request(request, db)
    try:
        content, content_type = await service.read_file(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            file_id=file_id,
        )
        return Response(
            content=content,
            media_type=content_type,
            headers={"Content-Disposition": "attachment"},
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.delete("/files/{file_id}", status_code=status.HTTP_200_OK)
async def delete_file(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    file_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    service = _file_service_from_request(request, db)
    try:
        deleted = await service.delete_file(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            file_id=file_id,
        )
        await db.commit()
        return {"deleted": deleted}
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/posts/{post_id}/pin", response_model=BlackboardPostResponse)
async def pin_post(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    post_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BlackboardPostResponse:
    service = _service_from_request(request, db)
    try:
        post = await service.pin_post(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            post_id=post_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.BLACKBOARD_POST_UPDATED,
            payload=_blackboard_event_payload(
                {
                    "post": _to_post_response(post).model_dump(mode="json"),
                    "action": "pin",
                }
            ),
            metadata=_blackboard_event_metadata(tenant_id, project_id),
        )
        return _to_post_response(post)
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


@router.post("/posts/{post_id}/unpin", response_model=BlackboardPostResponse)
async def unpin_post(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    post_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BlackboardPostResponse:
    service = _service_from_request(request, db)
    try:
        post = await service.unpin_post(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            post_id=post_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.BLACKBOARD_POST_UPDATED,
            payload=_blackboard_event_payload(
                {
                    "post": _to_post_response(post).model_dump(mode="json"),
                    "action": "unpin",
                }
            ),
            metadata=_blackboard_event_metadata(tenant_id, project_id),
        )
        return _to_post_response(post)
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


@router.post(
    "/posts/{post_id}/replies",
    response_model=BlackboardReplyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_reply(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    post_id: str,
    payload: BlackboardReplyCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BlackboardReplyResponse:
    service = _service_from_request(request, db)
    try:
        reply = await service.create_reply(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            post_id=post_id,
            actor_user_id=current_user.id,
            content=payload.content,
            metadata=payload.metadata,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.BLACKBOARD_REPLY_CREATED,
            payload=_blackboard_event_payload(
                {
                    "reply": _to_reply_response(reply).model_dump(mode="json"),
                    "post_id": post_id,
                }
            ),
            metadata=_blackboard_event_metadata(tenant_id, project_id),
        )
        return _to_reply_response(reply)
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


@router.get("/posts/{post_id}/replies", response_model=BlackboardReplyListResponse)
async def list_replies(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    post_id: str,
    request: Request,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BlackboardReplyListResponse:
    service = _service_from_request(request, db)
    try:
        replies = await service.list_replies(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            post_id=post_id,
            actor_user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
        return BlackboardReplyListResponse(items=[_to_reply_response(reply) for reply in replies])
    except Exception as exc:
        raise _map_error(exc) from exc


@router.patch("/posts/{post_id}/replies/{reply_id}", response_model=BlackboardReplyResponse)
async def update_reply(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    post_id: str,
    reply_id: str,
    payload: BlackboardReplyUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BlackboardReplyResponse:
    service = _service_from_request(request, db)
    try:
        reply = await service.update_reply(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            post_id=post_id,
            reply_id=reply_id,
            actor_user_id=current_user.id,
            content=payload.content,
            metadata=payload.metadata,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.BLACKBOARD_POST_UPDATED,
            payload=_blackboard_event_payload(
                {
                    "reply": _to_reply_response(reply).model_dump(mode="json"),
                    "post_id": post_id,
                    "action": "reply_updated",
                }
            ),
            metadata=_blackboard_event_metadata(tenant_id, project_id),
        )
        return _to_reply_response(reply)
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc


@router.delete("/posts/{post_id}/replies/{reply_id}")
async def delete_reply(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    post_id: str,
    reply_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    service = _service_from_request(request, db)
    try:
        deleted = await service.delete_reply(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            post_id=post_id,
            reply_id=reply_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.BLACKBOARD_REPLY_DELETED,
            payload=_blackboard_event_payload(
                {
                    "reply_id": reply_id,
                    "post_id": post_id,
                }
            ),
            metadata=_blackboard_event_metadata(tenant_id, project_id),
        )
        return {"success": deleted}
    except Exception as exc:
        await db.rollback()
        raise _map_error(exc) from exc
