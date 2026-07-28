"""Artifact API routes for managing tool output artifacts.

Provides REST API endpoints for:
- Listing artifacts by project/tool execution
- Getting individual artifact details
- Downloading artifact content
- Refreshing presigned URLs
"""

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.artifact_content_contract import (
    ArtifactContentContractError,
    ArtifactContentHashMismatchError,
    ArtifactContentIdempotencyConflictError,
    ArtifactContentIntegrityError,
    ArtifactContentNotEditableError,
    ArtifactContentRevisionConflictError,
    ArtifactContentSaveCommand,
)
from src.application.services.artifact_service import ArtifactService
from src.domain.model.artifact.artifact import ArtifactCategory, ArtifactStatus
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User, UserProject
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/artifacts", tags=["artifacts"])

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
    content: str


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
) -> Response:
    """
    Download authenticated bytes without exposing object-store credentials.
    """
    service = get_artifact_service()
    artifact = await service.get_artifact(artifact_id)

    if not artifact:
        raise HTTPException(status_code=404, detail=_("Artifact not found"))

    await verify_project_access(artifact.project_id, current_user, db)

    if artifact.status != ArtifactStatus.READY:
        raise HTTPException(
            status_code=400,
            detail=_("Artifact is not ready for download"),
        )

    content = await service.get_artifact_bytes(artifact_id)
    if content is None:
        raise HTTPException(status_code=404, detail=_("Artifact content not found"))

    return Response(
        content=content,
        media_type=artifact.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": "attachment",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{artifact_id}/content", response_model=ArtifactContentResponse)
async def get_artifact_content(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ArtifactContentResponse:
    """Return editable text with canonical revision and content hash."""
    service = get_artifact_service()
    artifact = await service.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail=_("Artifact not found"))
    await verify_project_access(artifact.project_id, current_user, db)
    if artifact.status != ArtifactStatus.READY:
        raise HTTPException(
            status_code=400,
            detail=_("Artifact content is not ready"),
        )
    try:
        content = await service.get_artifact_content(artifact_id)
    except ArtifactContentNotEditableError as exc:
        raise HTTPException(
            status_code=415,
            detail=_("Artifact content is not editable text"),
        ) from exc
    except ArtifactContentIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=_("Artifact content integrity check failed"),
        ) from exc
    if content is None:
        raise HTTPException(status_code=404, detail=_("Artifact content not found"))
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
) -> Response:
    """Return authenticated raw bytes for previews."""
    service = get_artifact_service()
    artifact = await service.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail=_("Artifact not found"))
    await verify_project_access(artifact.project_id, current_user, db)
    if artifact.status != ArtifactStatus.READY:
        raise HTTPException(
            status_code=400,
            detail=_("Artifact content is not ready"),
        )
    content = await service.get_artifact_bytes(artifact_id)
    if content is None:
        raise HTTPException(status_code=404, detail=_("Artifact content not found"))
    return Response(
        content=content,
        media_type=artifact.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
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
) -> UpdateContentResponse | JSONResponse:
    """
    Update the text content of an artifact (canvas save-back).

    Saves editable text to a versioned object and conditionally advances the
    metadata pointer.
    """
    service = get_artifact_service()
    artifact = await service.get_artifact(artifact_id)

    if not artifact:
        raise HTTPException(status_code=404, detail=_("Artifact not found"))

    await verify_project_access(artifact.project_id, current_user, db)

    if artifact.status != ArtifactStatus.READY:
        raise HTTPException(
            status_code=400,
            detail=_("Artifact cannot be updated in its current status"),
        )

    try:
        receipt = await service.save_artifact_content(
            artifact_id,
            ArtifactContentSaveCommand(
                contract_version=request.contract_version,
                expected_revision=request.expected_revision,
                content_hash=request.content_hash,
                idempotency_key=request.idempotency_key,
                content=request.content,
            ),
        )
    except ArtifactContentRevisionConflictError as exc:
        return _artifact_content_conflict_response(
            detail=_("Artifact content revision conflict"),
            error=exc,
        )
    except ArtifactContentIdempotencyConflictError as exc:
        return _artifact_content_conflict_response(
            detail=_("Artifact content idempotency conflict"),
            error=exc,
        )
    except ArtifactContentNotEditableError as exc:
        raise HTTPException(
            status_code=415,
            detail=_("Artifact content is not editable text"),
        ) from exc
    except ArtifactContentHashMismatchError as exc:
        raise HTTPException(
            status_code=422,
            detail=_("Artifact content hash does not match content"),
        ) from exc
    except ArtifactContentContractError as exc:
        raise HTTPException(
            status_code=422,
            detail=_("Artifact content command is invalid"),
        ) from exc
    if receipt is None:
        raise HTTPException(status_code=404, detail=_("Artifact content not found"))

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
