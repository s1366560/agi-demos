"""Artifact API routes for managing tool output artifacts.

Provides REST API endpoints for:
- Listing artifacts by project/tool execution
- Getting individual artifact details
- Downloading artifact content
- Refreshing presigned URLs
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Literal, override

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask
from starlette.types import Message

from src.application.services.artifact_content_authority_service import (
    MAX_ARTIFACT_DOWNLOAD_BYTES,
    MAX_ARTIFACT_PREVIEW_BYTES,
    MAX_EDITABLE_ARTIFACT_BYTES,
    ArtifactContentAuthorityService,
    ArtifactContentNotReadyError,
    ArtifactContentSaveOutcome,
    ArtifactContentTooLargeError,
)
from src.application.services.artifact_content_contract import (
    ArtifactContentContractError,
    ArtifactContentHashMismatchError,
    ArtifactContentIdempotencyConflictError,
    ArtifactContentIntegrityError,
    ArtifactContentNotEditableError,
    ArtifactContentRevisionConflictError,
    ArtifactContentSaveCommand,
    preview_response_mime_type,
)
from src.application.services.artifact_service import ArtifactService
from src.domain.model.artifact.artifact import ArtifactCategory, ArtifactStatus
from src.domain.ports.repositories.artifact_content_authority_repository import (
    ArtifactContentScope,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.artifact_content_commit_reconciler import (
    ArtifactContentCommitReconciler,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory, get_db
from src.infrastructure.adapters.secondary.persistence.models import User, UserProject
from src.infrastructure.adapters.secondary.persistence.sql_artifact_content_authority import (
    SqlArtifactContentAuthorityRepository,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

MAX_EDITABLE_ARTIFACT_REQUEST_BYTES = (MAX_EDITABLE_ARTIFACT_BYTES * 6) + 16_384
_ARTIFACT_CONTENT_UPDATE_PATH = "/api/v1/artifacts/{artifact_id}/content"


async def _settle_artifact_side_effect(
    operation: Awaitable[None],
) -> tuple[BaseException | None, asyncio.CancelledError | None]:
    """Observe a side effect to a definitive outcome without losing cancellation."""
    task = asyncio.ensure_future(operation)
    caller_cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if task.cancelled():
                return exc, caller_cancellation or exc
            caller_cancellation = caller_cancellation or exc
        except BaseException as exc:
            return exc, caller_cancellation
    if task.cancelled():
        cancelled = asyncio.CancelledError()
        return cancelled, caller_cancellation or cancelled
    return task.exception(), caller_cancellation


async def _commit_artifact_content_outcome(
    *,
    db: AsyncSession,
    reconciler: ArtifactContentCommitReconciler,
    outcome: ArtifactContentSaveOutcome,
) -> None:
    """Commit once, reconcile only a definitive failure, and preserve cancellation."""
    commit_error, cancellation = await _settle_artifact_side_effect(db.commit())
    if commit_error is not None:
        rollback_error, rollback_cancellation = await _settle_artifact_side_effect(db.rollback())
        cancellation = cancellation or rollback_cancellation
        if rollback_error is not None:
            logger.warning(
                "Failed request transaction rollback before Artifact reconciliation",
                exc_info=(
                    type(rollback_error),
                    rollback_error,
                    rollback_error.__traceback__,
                ),
            )
        reconcile_error, reconcile_cancellation = await _settle_artifact_side_effect(
            reconciler.reconcile(outcome)
        )
        cancellation = cancellation or reconcile_cancellation
        if reconcile_error is not None:
            logger.error(
                "Failed Artifact reconciliation after request transaction failure",
                exc_info=(
                    type(reconcile_error),
                    reconcile_error,
                    reconcile_error.__traceback__,
                ),
            )
    if cancellation is not None:
        raise cancellation
    if commit_error is not None:
        raise commit_error


class ArtifactContentBodyLimitRoute(APIRoute):
    """Enforce the Artifact save transport limit before JSON parsing."""

    @override
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_route_handler = super().get_route_handler()
        if self.path_format != _ARTIFACT_CONTENT_UPDATE_PATH or "PUT" not in self.methods:
            return original_route_handler

        async def limited_route_handler(request: Request) -> Response:
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    declared_bytes = int(content_length)
                except ValueError:
                    declared_bytes = -1
                if declared_bytes > MAX_EDITABLE_ARTIFACT_REQUEST_BYTES:
                    return _artifact_content_request_too_large_response()

            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_EDITABLE_ARTIFACT_REQUEST_BYTES:
                    return _artifact_content_request_too_large_response()
                body.extend(chunk)

            replayed = False

            async def replay_receive() -> Message:
                nonlocal replayed
                if replayed:
                    return {"type": "http.disconnect"}
                replayed = True
                return {
                    "type": "http.request",
                    "body": bytes(body),
                    "more_body": False,
                }

            limited_request = Request(request.scope, receive=replay_receive)
            return await original_route_handler(limited_request)

        return limited_route_handler


router = APIRouter(
    prefix="/api/v1/artifacts",
    tags=["artifacts"],
    route_class=ArtifactContentBodyLimitRoute,
)

# Singleton artifact service
_artifact_service: ArtifactService | None = None


def get_artifact_service() -> ArtifactService:
    """Get or create the artifact service singleton."""
    global _artifact_service

    if _artifact_service is None:
        from src.configuration.di_container import DIContainer

        container = DIContainer()
        _artifact_service = container.artifact_service()

    service = _artifact_service
    if service is None:
        raise RuntimeError("Artifact service initialization failed")
    return service


def get_artifact_content_authority_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ArtifactContentAuthorityService:
    """Build the cloud content authority from the request-scoped DB container."""
    container = request.app.state.container.with_db(db)
    storage_service = container.storage_service()
    reconciler = ArtifactContentCommitReconciler(
        session_factory=async_session_factory,
        storage_service=storage_service,
    )
    return ArtifactContentAuthorityService(
        repository=SqlArtifactContentAuthorityRepository(db),
        storage_service=storage_service,
        orphan_recorder=reconciler.record_pending,
    )


def get_artifact_content_commit_reconciler(
    request: Request,
) -> ArtifactContentCommitReconciler:
    """Build a reconciler that never reuses a failed request transaction."""
    container = request.app.state.container
    return ArtifactContentCommitReconciler(
        session_factory=async_session_factory,
        storage_service=container.storage_service(),
    )


async def verify_project_access(project_id: str, user: User, db: AsyncSession) -> None:
    """Verify that the authenticated user is a project member."""
    if user.is_superuser:
        return

    result = await db.execute(
        refresh_select_statement(
            select(UserProject).where(
                and_(UserProject.user_id == user.id, UserProject.project_id == project_id)
            )
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail=_("Access denied to project"))


# === Request/Response Models ===


class ArtifactResponse(BaseModel):
    """Artifact response model."""

    id: str
    project_id: str
    tenant_id: str
    sandbox_id: str | None = None
    tool_execution_id: str | None = None
    conversation_id: str | None = None

    filename: str
    mime_type: str
    category: str
    size_bytes: int

    url: str | None = None
    preview_url: str | None = None

    status: str
    error_message: str | None = None

    source_tool: str | None = None
    source_path: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ArtifactListResponse(BaseModel):
    """Response model for artifact list."""

    artifacts: list[ArtifactResponse]
    total: int


class RefreshUrlResponse(BaseModel):
    """Response model for URL refresh."""

    artifact_id: str
    url: str


class UpdateContentRequest(BaseModel):
    """ArtifactContentContractV2 conditional save command."""

    contract_version: Literal[2]
    expected_revision: int = Field(ge=0)
    content_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    content: str = Field(max_length=MAX_EDITABLE_ARTIFACT_BYTES)


class UpdateContentResponse(BaseModel):
    """ArtifactContentContractV2 save receipt."""

    artifact_id: str
    revision: int
    content_hash: str
    duplicate: bool


class ArtifactContentResponse(BaseModel):
    """Canonical editable Artifact content authority."""

    contract_version: Literal[2]
    artifact_id: str
    revision: int
    content_hash: str
    mime_type: str
    content: str


# === API Endpoints ===


@router.get("", response_model=ArtifactListResponse)
async def list_artifacts(
    project_id: str = Query(..., description="Project ID to list artifacts for"),
    category: str | None = Query(None, description="Filter by category"),
    tool_execution_id: str | None = Query(None, description="Filter by tool execution"),
    limit: int = Query(100, ge=1, le=500, description="Maximum number of artifacts to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ArtifactListResponse:
    """
    List artifacts for a project.

    Supports filtering by category (image, video, audio, etc.) and tool execution ID.
    Returns artifacts sorted by creation time, newest first.
    """
    service = get_artifact_service()
    await verify_project_access(project_id, current_user, db)

    # Validate category if provided
    category_filter = None
    if category:
        try:
            category_filter = ArtifactCategory(category)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=_("Invalid artifact category"),
            ) from None

    # Get artifacts
    if tool_execution_id:
        artifacts = [
            artifact
            for artifact in await service.get_artifacts_by_tool_execution(tool_execution_id)
            if artifact.project_id == project_id and artifact.status == ArtifactStatus.READY
        ]
        if category_filter:
            artifacts = [a for a in artifacts if a.category == category_filter]
        artifacts = artifacts[:limit]
    else:
        artifacts = await service.get_artifacts_by_project(
            project_id=project_id,
            limit=limit,
            category=category_filter,
        )

    # Convert to response format
    artifact_responses = [
        ArtifactResponse(
            id=a.id,
            project_id=a.project_id,
            tenant_id=a.tenant_id,
            sandbox_id=a.sandbox_id,
            tool_execution_id=a.tool_execution_id,
            conversation_id=a.conversation_id,
            filename=a.filename,
            mime_type=a.mime_type,
            category=a.category.value,
            size_bytes=a.size_bytes,
            url=a.url,
            preview_url=a.preview_url,
            status=a.status.value,
            error_message=a.error_message,
            source_tool=a.source_tool,
            source_path=a.source_path,
            metadata=a.metadata,
            created_at=a.created_at.isoformat(),
        )
        for a in artifacts
    ]

    return ArtifactListResponse(
        artifacts=artifact_responses,
        total=len(artifact_responses),
    )


@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ArtifactResponse:
    """
    Get a single artifact by ID.
    """
    service = get_artifact_service()
    artifact = await service.get_artifact(artifact_id)

    if not artifact:
        raise HTTPException(status_code=404, detail=_("Artifact not found"))

    await verify_project_access(artifact.project_id, current_user, db)

    return ArtifactResponse(
        id=artifact.id,
        project_id=artifact.project_id,
        tenant_id=artifact.tenant_id,
        sandbox_id=artifact.sandbox_id,
        tool_execution_id=artifact.tool_execution_id,
        conversation_id=artifact.conversation_id,
        filename=artifact.filename,
        mime_type=artifact.mime_type,
        category=artifact.category.value,
        size_bytes=artifact.size_bytes,
        url=artifact.url,
        preview_url=artifact.preview_url,
        status=artifact.status.value,
        error_message=artifact.error_message,
        source_tool=artifact.source_tool,
        source_path=artifact.source_path,
        metadata=artifact.metadata,
        created_at=artifact.created_at.isoformat(),
    )


@router.get("/{artifact_id}/download")
async def download_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ArtifactContentAuthorityService = Depends(get_artifact_content_authority_service),
) -> Response:
    """
    Download authenticated bytes without exposing object-store credentials.
    """
    scope = await _resolve_artifact_content_scope(service, artifact_id, current_user, db)
    try:
        download = await service.stage_download(
            scope,
            max_bytes=MAX_ARTIFACT_DOWNLOAD_BYTES,
        )
    except ArtifactContentNotReadyError as exc:
        raise HTTPException(
            status_code=400,
            detail=_("Artifact is not ready for download"),
        ) from exc
    except ArtifactContentTooLargeError as exc:
        raise HTTPException(
            status_code=413,
            detail=_("Artifact exceeds the authenticated download size limit"),
        ) from exc
    except ArtifactContentIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=_("Artifact content integrity check failed"),
        ) from exc
    if download is None:
        raise HTTPException(status_code=404, detail=_("Artifact content not found"))
    try:
        await db.commit()
    except Exception:
        await download.discard()
        raise

    return StreamingResponse(
        content=download.iter_chunks(),
        media_type=download.mime_type,
        background=BackgroundTask(download.discard),
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": "attachment",
            "Content-Length": str(download.size_bytes),
            "X-Content-Type-Options": "nosniff",
            "X-Artifact-Revision": str(download.revision),
            "X-Artifact-Content-Hash": download.content_hash,
        },
    )


@router.get("/{artifact_id}/content", response_model=ArtifactContentResponse)
async def get_artifact_content(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ArtifactContentAuthorityService = Depends(get_artifact_content_authority_service),
) -> ArtifactContentResponse:
    """Return editable text with canonical revision and content hash."""
    scope = await _resolve_artifact_content_scope(service, artifact_id, current_user, db)
    try:
        content = await service.get_content(scope)
    except ArtifactContentNotReadyError as exc:
        raise HTTPException(
            status_code=400,
            detail=_("Artifact content is not ready"),
        ) from exc
    except ArtifactContentNotEditableError as exc:
        raise HTTPException(
            status_code=415,
            detail=_("Artifact content is not editable text"),
        ) from exc
    except ArtifactContentTooLargeError as exc:
        raise HTTPException(
            status_code=413,
            detail=_("Artifact exceeds the editable content size limit"),
        ) from exc
    except ArtifactContentIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=_("Artifact content integrity check failed"),
        ) from exc
    if content is None:
        raise HTTPException(status_code=404, detail=_("Artifact content not found"))
    await db.commit()
    return ArtifactContentResponse(
        contract_version=2,
        artifact_id=content.artifact_id,
        revision=content.revision,
        content_hash=content.content_hash,
        mime_type=content.mime_type,
        content=content.content,
    )


@router.get("/{artifact_id}/content/bytes")
async def get_artifact_content_bytes(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ArtifactContentAuthorityService = Depends(get_artifact_content_authority_service),
) -> Response:
    """Return authenticated raw bytes for previews."""
    scope = await _resolve_artifact_content_scope(service, artifact_id, current_user, db)
    try:
        content = await service.get_bytes(
            scope,
            max_bytes=MAX_ARTIFACT_PREVIEW_BYTES,
        )
    except ArtifactContentNotReadyError as exc:
        raise HTTPException(
            status_code=400,
            detail=_("Artifact content is not ready"),
        ) from exc
    except ArtifactContentTooLargeError as exc:
        return JSONResponse(
            status_code=413,
            content={
                "detail": _("Artifact exceeds the authenticated preview size limit"),
                "reason_code": "artifact_preview_size_limit",
                "fallback": "download",
                "download_url": f"/api/v1/artifacts/{artifact_id}/download",
                "max_bytes": exc.max_bytes,
            },
        )
    except ArtifactContentIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=_("Artifact content integrity check failed"),
        ) from exc
    if content is None:
        raise HTTPException(status_code=404, detail=_("Artifact content not found"))
    await db.commit()
    return Response(
        content=content.content,
        media_type=preview_response_mime_type(content.mime_type),
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Artifact-Revision": str(content.revision),
            "X-Artifact-Content-Hash": content.content_hash,
        },
    )


@router.post("/{artifact_id}/refresh-url", response_model=RefreshUrlResponse)
async def refresh_artifact_url(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RefreshUrlResponse:
    """
    Refresh the presigned URL for an artifact.

    Use this when the current URL has expired or is about to expire.
    """
    service = get_artifact_service()
    artifact = await service.get_artifact(artifact_id)

    if not artifact:
        raise HTTPException(status_code=404, detail=_("Artifact not found"))

    await verify_project_access(artifact.project_id, current_user, db)

    if artifact.status != ArtifactStatus.READY:
        raise HTTPException(
            status_code=400,
            detail=_("Artifact URL cannot be refreshed in its current status"),
        )

    url = await service.refresh_artifact_url(artifact_id)
    if not url:
        raise HTTPException(status_code=500, detail=_("Failed to refresh URL"))

    return RefreshUrlResponse(artifact_id=artifact_id, url=url)


@router.put("/{artifact_id}/content", response_model=UpdateContentResponse)
async def update_artifact_content(
    artifact_id: str,
    request: UpdateContentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ArtifactContentAuthorityService = Depends(get_artifact_content_authority_service),
    reconciler: ArtifactContentCommitReconciler = Depends(get_artifact_content_commit_reconciler),
) -> UpdateContentResponse | JSONResponse:
    """
    Update the text content of an artifact (canvas save-back).

    Saves editable text to a versioned object and conditionally advances the
    metadata pointer.
    """
    scope = await _resolve_artifact_content_scope(service, artifact_id, current_user, db)
    try:
        outcome = await service.save_content(
            scope,
            ArtifactContentSaveCommand(
                contract_version=request.contract_version,
                expected_revision=request.expected_revision,
                content_hash=request.content_hash,
                idempotency_key=request.idempotency_key,
                content=request.content,
            ),
        )
    except ArtifactContentRevisionConflictError as exc:
        await db.rollback()
        return _artifact_content_conflict_response(
            detail=_("Artifact content revision conflict"),
            error=exc,
        )
    except ArtifactContentIdempotencyConflictError as exc:
        await db.rollback()
        return _artifact_content_conflict_response(
            detail=_("Artifact content idempotency conflict"),
            error=exc,
        )
    except ArtifactContentNotEditableError as exc:
        raise HTTPException(
            status_code=415,
            detail=_("Artifact content is not editable text"),
        ) from exc
    except ArtifactContentNotReadyError as exc:
        raise HTTPException(
            status_code=400,
            detail=_("Artifact cannot be updated in its current status"),
        ) from exc
    except ArtifactContentHashMismatchError as exc:
        raise HTTPException(
            status_code=422,
            detail=_("Artifact content hash does not match content"),
        ) from exc
    except ArtifactContentTooLargeError as exc:
        raise HTTPException(
            status_code=413,
            detail=_("Artifact exceeds the editable content size limit"),
        ) from exc
    except ArtifactContentIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=_("Artifact content integrity check failed"),
        ) from exc
    except ArtifactContentContractError as exc:
        raise HTTPException(
            status_code=422,
            detail=_("Artifact content command is invalid"),
        ) from exc
    if outcome is None:
        raise HTTPException(status_code=404, detail=_("Artifact content not found"))
    await _commit_artifact_content_outcome(
        db=db,
        reconciler=reconciler,
        outcome=outcome,
    )
    receipt = outcome.receipt

    return UpdateContentResponse(
        artifact_id=artifact_id,
        revision=receipt.revision,
        content_hash=receipt.content_hash,
        duplicate=receipt.duplicate,
    )


@router.delete("/{artifact_id}")
async def delete_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Delete an artifact.

    This removes the artifact from storage and marks it as deleted.
    """
    service = get_artifact_service()
    artifact = await service.get_artifact(artifact_id)

    if not artifact:
        raise HTTPException(status_code=404, detail=_("Artifact not found"))

    await verify_project_access(artifact.project_id, current_user, db)

    success = await service.delete_artifact(artifact_id)
    if not success:
        raise HTTPException(status_code=500, detail=_("Failed to delete artifact"))

    return {"status": "deleted", "artifact_id": artifact_id}


@router.get("/categories/list")
async def list_categories(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    List all available artifact categories.

    Useful for building filter UIs.
    """
    return {
        "categories": [
            {
                "value": c.value,
                "label": c.value.title(),
                "description": _get_category_description(c),
            }
            for c in ArtifactCategory
        ]
    }


def _get_category_description(category: ArtifactCategory) -> str:
    """Get human-readable description for a category."""
    descriptions = {
        ArtifactCategory.IMAGE: "Images (PNG, JPEG, GIF, SVG, etc.)",
        ArtifactCategory.VIDEO: "Videos (MP4, WebM, MOV, etc.)",
        ArtifactCategory.AUDIO: "Audio files (MP3, WAV, OGG, etc.)",
        ArtifactCategory.DOCUMENT: "Documents (PDF, TXT, HTML, Markdown)",
        ArtifactCategory.CODE: "Source code files (Python, JavaScript, etc.)",
        ArtifactCategory.DATA: "Data files (JSON, CSV, XML, YAML)",
        ArtifactCategory.ARCHIVE: "Archives (ZIP, TAR, GZ)",
        ArtifactCategory.OTHER: "Other file types",
    }
    return descriptions.get(category, "Unknown category")


def _artifact_content_conflict_response(
    *,
    detail: str,
    error: ArtifactContentRevisionConflictError | ArtifactContentIdempotencyConflictError,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "detail": detail,
            "reason_code": error.reason_code,
            "server_revision": error.server_revision,
            "server_content_hash": error.server_content_hash,
        },
    )


def _artifact_content_request_too_large_response() -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={
            "detail": _("Artifact content request exceeds the size limit"),
            "reason_code": "artifact_content_request_size_limit",
            "max_bytes": MAX_EDITABLE_ARTIFACT_REQUEST_BYTES,
        },
    )


async def _resolve_artifact_content_scope(
    service: ArtifactContentAuthorityService,
    artifact_id: str,
    current_user: User,
    db: AsyncSession,
) -> ArtifactContentScope:
    scope = await service.resolve_scope(artifact_id)
    if scope is None:
        raise HTTPException(status_code=404, detail=_("Artifact not found"))
    await verify_project_access(scope.project_id, current_user, db)
    return scope
