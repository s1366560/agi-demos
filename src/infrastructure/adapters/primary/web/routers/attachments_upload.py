"""Attachment API routes for file uploads.

Provides REST API endpoints for:
- Simple file upload (small files ≤10MB)
- Multipart upload initiation, part upload, completion
- Attachment download and deletion
"""

import logging
from typing import Any, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.attachment_service import AttachmentService
from src.domain.model.agent.attachment import (
    DEFAULT_PART_SIZE,
    Attachment,
    AttachmentPurpose,
    AttachmentStatus,
)
from src.domain.ports.services.storage_service_port import PartUploadResult
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.sql_attachment_repository import (
    SqlAttachmentRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/attachments", tags=["attachments"])

# Cached storage service (stateless, can be reused)
_storage_service = None


def _get_storage_service() -> None:
    """Get or create the storage service singleton (stateless)."""
    global _storage_service
    if _storage_service is None:
        from src.configuration.di_container import DIContainer

        container = DIContainer()
        _storage_service = container.storage_service()
    return cast(None, _storage_service)


async def get_attachment_service(
    session: AsyncSession = Depends(get_db),
) -> AttachmentService:
    """Get attachment service with per-request database session."""
    from src.configuration.config import get_settings

    settings = get_settings()
    repository = SqlAttachmentRepository(session)
    return AttachmentService(
        storage_service=_get_storage_service(),
        attachment_repository=repository,
        upload_max_size_llm_mb=settings.upload_max_size_llm_mb,
        upload_max_size_sandbox_mb=settings.upload_max_size_sandbox_mb,
    )


# === Request/Response Models ===


class InitiateUploadRequest(BaseModel):
    """Request model for initiating multipart upload."""

    conversation_id: str = Field(..., description="ID of the conversation")
    project_id: str = Field(..., description="ID of the project")
    filename: str = Field(..., description="Original filename")
    mime_type: str = Field(..., description="MIME type of the file")
    size_bytes: int = Field(..., gt=0, description="Total file size in bytes")
    purpose: str = Field(
        default="both",
        description="Purpose: 'llm_context', 'sandbox_input', or 'both'",
    )


class InitiateUploadResponse(BaseModel):
    """Response model for multipart upload initiation."""

    attachment_id: str = Field(..., description="ID of the created attachment")
    upload_id: str = Field(..., description="S3 multipart upload ID")
    total_parts: int = Field(..., description="Total number of parts to upload")
    part_size: int = Field(..., description="Recommended part size in bytes")


class UploadPartResponse(BaseModel):
    """Response model for part upload."""

    part_number: int = Field(..., description="Part number that was uploaded")
    etag: str = Field(..., description="ETag of the uploaded part")


class CompleteUploadRequest(BaseModel):
    """Request model for completing multipart upload."""

    attachment_id: str = Field(..., description="ID of the attachment")
    parts: list[dict[str, Any]] = Field(
        ...,
        description="List of uploaded parts with 'part_number' and 'etag'",
    )


class AttachmentResponse(BaseModel):
    """Response model for attachment details."""

    id: str
    conversation_id: str
    project_id: str
    filename: str
    mime_type: str
    size_bytes: int
    purpose: str
    status: str
    sandbox_path: str | None = None
    created_at: str
    error_message: str | None = None


class AttachmentListResponse(BaseModel):
    """Response model for attachment list."""

    attachments: list[AttachmentResponse]
    total: int


# === Helper Functions ===


def _attachment_to_response(attachment: Attachment) -> AttachmentResponse:
    """Convert attachment entity to response model."""
    return AttachmentResponse(
        id=attachment.id,
        conversation_id=attachment.conversation_id,
        project_id=attachment.project_id,
        filename=attachment.filename,
        mime_type=attachment.mime_type,
        size_bytes=attachment.size_bytes,
        purpose=attachment.purpose.value,
        status=attachment.status.value,
        sandbox_path=attachment.sandbox_path,
        created_at=attachment.created_at.isoformat(),
        error_message=attachment.error_message,
    )


def _parse_purpose(purpose: str) -> AttachmentPurpose:
    """Parse purpose string to enum."""
    try:
        return AttachmentPurpose(purpose)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid purpose: {purpose}. Must be one of: llm_context, sandbox_input, both",
        ) from None


# === API Endpoints ===


@router.post("/upload/initiate", response_model=InitiateUploadResponse)
async def initiate_multipart_upload(
    request: InitiateUploadRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> InitiateUploadResponse:
    """
    Initialize a multipart upload for large files.

    Use this endpoint for files larger than 10MB. After initialization,
    upload each part using POST /upload/part, then complete with POST /upload/complete.
    """
    try:
        purpose = _parse_purpose(request.purpose)

        attachment = await attachment_service.initiate_multipart_upload(
            tenant_id=tenant_id,
            project_id=request.project_id,
            conversation_id=request.conversation_id,
            filename=request.filename,
            mime_type=request.mime_type,
            size_bytes=request.size_bytes,
            purpose=purpose,
        )

        return InitiateUploadResponse(
            attachment_id=attachment.id,
            upload_id=attachment.upload_id or "",
            total_parts=attachment.total_parts or 0,
            part_size=DEFAULT_PART_SIZE,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to initiate multipart upload: {e}")
        raise HTTPException(status_code=500, detail="Failed to initiate upload") from e


@router.post("/upload/part", response_model=UploadPartResponse)
async def upload_part(
    attachment_id: str = Form(..., description="ID of the attachment"),
    part_number: int = Form(..., ge=1, description="Part number (1-indexed)"),
    file: UploadFile = File(..., description="Part data"),
    current_user: User = Depends(get_current_user),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> UploadPartResponse:
    """
    Upload a single part in a multipart upload.

    Part numbers start at 1 and must be uploaded in order.
    Each part (except the last) should be exactly part_size bytes.
    """
    try:
        data = await file.read()

        result = await attachment_service.upload_part(
            attachment_id=attachment_id,
            part_number=part_number,
            data=data,
        )

        return UploadPartResponse(
            part_number=result.part_number,
            etag=result.etag,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to upload part: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload part") from e


@router.post("/upload/complete", response_model=AttachmentResponse)
async def complete_multipart_upload(
    request: CompleteUploadRequest,
    current_user: User = Depends(get_current_user),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> _attachment_to_response:
    """
    Complete a multipart upload.

    Call this after all parts have been uploaded successfully.
    The 'parts' array must contain all uploaded parts with their part_number and etag.
    """
    try:
        # Convert parts to PartUploadResult
        parts = [
            PartUploadResult(
                part_number=p["part_number"],
                etag=p["etag"],
            )
            for p in request.parts
        ]

        attachment = await attachment_service.complete_multipart_upload(
            attachment_id=request.attachment_id,
            parts=parts,
        )

        return _attachment_to_response(attachment)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to complete multipart upload: {e}")
        raise HTTPException(status_code=500, detail="Failed to complete upload") from e


@router.post("/upload/abort")
async def abort_multipart_upload(
    attachment_id: str = Form(..., description="ID of the attachment"),
    current_user: User = Depends(get_current_user),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> dict[str, Any]:
    """
    Abort a multipart upload.

    Use this to cancel an in-progress multipart upload and clean up resources.
    """
    try:
        success = await attachment_service.abort_multipart_upload(attachment_id)

        if not success:
            raise HTTPException(status_code=404, detail="Attachment not found")

        return {"success": True, "message": "Upload aborted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to abort multipart upload: {e}")
        raise HTTPException(status_code=500, detail="Failed to abort upload") from e


@router.post("/upload/simple", response_model=AttachmentResponse)
async def upload_simple(
    conversation_id: str = Form(..., description="ID of the conversation"),
    project_id: str = Form(..., description="ID of the project"),
    purpose: str = Form(default="both", description="Purpose of the attachment"),
    file: UploadFile = File(..., description="File to upload"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> _attachment_to_response:
    """
    Upload a small file directly (recommended for files ≤10MB).

    For larger files, use the multipart upload endpoints instead.
    """
    try:
        purpose_enum = _parse_purpose(purpose)
        data = await file.read()

        attachment = await attachment_service.upload_simple(
            tenant_id=tenant_id,
            project_id=project_id,
            conversation_id=conversation_id,
            filename=file.filename or "unnamed",
            mime_type=file.content_type or "application/octet-stream",
            data=data,
            purpose=purpose_enum,
        )

        return _attachment_to_response(attachment)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        import traceback

        logger.error(f"Failed to upload file: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to upload file") from e


@router.get("", response_model=AttachmentListResponse)
async def list_attachments(
    conversation_id: str = Query(..., description="Conversation ID to list attachments for"),
    status: str | None = Query(None, description="Filter by status"),
    current_user: User = Depends(get_current_user),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> AttachmentListResponse:
    """
    List attachments for a conversation.
    """
    try:
        status_enum = AttachmentStatus(status) if status else None
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}") from None

    attachments = await attachment_service.get_by_conversation(
        conversation_id=conversation_id,
        status=status_enum,
    )

    return AttachmentListResponse(
        attachments=[_attachment_to_response(a) for a in attachments],
        total=len(attachments),
    )


@router.get("/{attachment_id}", response_model=AttachmentResponse)
async def get_attachment(
    attachment_id: str,
    current_user: User = Depends(get_current_user),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> _attachment_to_response:
    """
    Get attachment details by ID.
    """
    attachment = await attachment_service.get(attachment_id)

    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    return _attachment_to_response(attachment)


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: str,
    current_user: User = Depends(get_current_user),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> RedirectResponse:
    """
    Download an attachment via presigned URL redirect.
    """
    url = await attachment_service.get_download_url(attachment_id)

    if not url:
        raise HTTPException(status_code=404, detail="Attachment not found or not ready")

    return RedirectResponse(url=url, status_code=302)


@router.delete("/{attachment_id}")
async def delete_attachment(
    attachment_id: str,
    current_user: User = Depends(get_current_user),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> dict[str, Any]:
    """
    Delete an attachment.
    """
    success = await attachment_service.delete(attachment_id)

    if not success:
        raise HTTPException(status_code=404, detail="Attachment not found")

    return {"success": True, "message": "Attachment deleted"}
