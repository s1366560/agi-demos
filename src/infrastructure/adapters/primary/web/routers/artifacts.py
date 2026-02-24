"""Artifact API routes for managing tool output artifacts.

Provides REST API endpoints for:
- Listing artifacts by project/tool execution
- Getting individual artifact details
- Downloading artifact content
- Refreshing presigned URLs
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from src.application.services.artifact_service import ArtifactService
from src.domain.model.artifact.artifact import ArtifactCategory, ArtifactStatus
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.models import User

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

    return _artifact_service


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

    metadata: dict = Field(default_factory=dict)
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
    """Request model for updating artifact content from canvas."""

    content: str = Field(..., description="Updated text content")


class UpdateContentResponse(BaseModel):
    """Response model for content update."""

    artifact_id: str
    size_bytes: int
    url: str | None = None


# === API Endpoints ===


@router.get("", response_model=ArtifactListResponse)
async def list_artifacts(
    project_id: str = Query(..., description="Project ID to list artifacts for"),
    category: str | None = Query(None, description="Filter by category"),
    tool_execution_id: str | None = Query(None, description="Filter by tool execution"),
    limit: int = Query(100, ge=1, le=500, description="Maximum number of artifacts to return"),
    current_user: User = Depends(get_current_user),
):
    """
    List artifacts for a project.

    Supports filtering by category (image, video, audio, etc.) and tool execution ID.
    Returns artifacts sorted by creation time, newest first.
    """
    service = get_artifact_service()

    # Validate category if provided
    category_filter = None
    if category:
        try:
            category_filter = ArtifactCategory(category)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category: {category}. Valid categories: {[c.value for c in ArtifactCategory]}",
            )

    # Get artifacts
    if tool_execution_id:
        artifacts = await service.get_artifacts_by_tool_execution(tool_execution_id)
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
):
    """
    Get a single artifact by ID.
    """
    service = get_artifact_service()
    artifact = await service.get_artifact(artifact_id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

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
):
    """
    Download an artifact.

    Redirects to the presigned URL for the artifact content.
    If the URL has expired, a new one is generated automatically.
    """
    service = get_artifact_service()
    artifact = await service.get_artifact(artifact_id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact.status != ArtifactStatus.READY:
        raise HTTPException(
            status_code=400,
            detail=f"Artifact not ready for download (status: {artifact.status.value})",
        )

    # Refresh URL to ensure it's valid
    url = await service.refresh_artifact_url(artifact_id)
    if not url:
        raise HTTPException(status_code=500, detail="Failed to generate download URL")

    # Redirect to presigned URL
    return RedirectResponse(url=url, status_code=307)


@router.post("/{artifact_id}/refresh-url", response_model=RefreshUrlResponse)
async def refresh_artifact_url(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Refresh the presigned URL for an artifact.

    Use this when the current URL has expired or is about to expire.
    """
    service = get_artifact_service()
    artifact = await service.get_artifact(artifact_id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact.status != ArtifactStatus.READY:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot refresh URL for artifact with status: {artifact.status.value}",
        )

    url = await service.refresh_artifact_url(artifact_id)
    if not url:
        raise HTTPException(status_code=500, detail="Failed to refresh URL")

    return RefreshUrlResponse(artifact_id=artifact_id, url=url)


@router.put("/{artifact_id}/content", response_model=UpdateContentResponse)
async def update_artifact_content(
    artifact_id: str,
    request: UpdateContentRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Update the text content of an artifact (canvas save-back).

    Overwrites the file in object storage with the provided text content.
    Only works for READY artifacts with text-decodable content.
    """
    service = get_artifact_service()
    artifact = await service.get_artifact(artifact_id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact.status != ArtifactStatus.READY:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update artifact with status: {artifact.status.value}",
        )

    updated = await service.update_artifact_content(artifact_id, request.content)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update artifact content")

    return UpdateContentResponse(
        artifact_id=artifact_id,
        size_bytes=updated.size_bytes,
        url=updated.url,
    )


@router.delete("/{artifact_id}")
async def delete_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Delete an artifact.

    This removes the artifact from storage and marks it as deleted.
    """
    service = get_artifact_service()
    artifact = await service.get_artifact(artifact_id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    success = await service.delete_artifact(artifact_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete artifact")

    return {"status": "deleted", "artifact_id": artifact_id}


@router.get("/categories/list")
async def list_categories(
    current_user: User = Depends(get_current_user),
):
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
