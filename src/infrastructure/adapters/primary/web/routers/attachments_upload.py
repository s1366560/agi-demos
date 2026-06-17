"""Attachment API routes for file uploads.

Provides REST API endpoints for:
- Simple file upload (small files ≤10MB)
- Multipart upload initiation, part upload, completion
- Attachment download and deletion
"""

import logging
from typing import Any, Self, cast

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status as http_status,
)
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.attachment_service import AttachmentService
from src.domain.model.agent.attachment import (
    DEFAULT_PART_SIZE,
    Attachment,
    AttachmentPurpose,
    AttachmentStatus,
)
from src.domain.ports.services.storage_service_port import PartUploadResult, StorageServicePort
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User, UserProject
from src.infrastructure.adapters.secondary.persistence.sql_attachment_repository import (
    SqlAttachmentRepository,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/attachments", tags=["attachments"])

# Cached storage service (stateless, can be reused)
_storage_service: StorageServicePort | None = None


def _get_storage_service() -> StorageServicePort:
    """Get or create the storage service singleton (stateless)."""
    global _storage_service
    if _storage_service is None:
        from src.configuration.di_container import DIContainer

        container = DIContainer()
        _storage_service = cast(StorageServicePort, container.storage_service())
    return _storage_service


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


class CompleteUploadPart(BaseModel):
    """Uploaded multipart part descriptor."""

    part_number: int = Field(..., ge=1, description="Part number that was uploaded")
    etag: str = Field(..., min_length=1, description="ETag returned by object storage")


class CompleteUploadRequest(BaseModel):
    """Request model for completing multipart upload."""

    attachment_id: str = Field(..., description="ID of the attachment")
    parts: list[CompleteUploadPart] = Field(
        ...,
        min_length=1,
        description="List of uploaded parts with 'part_number' and 'etag'",
    )

    @model_validator(mode="after")
    def validate_unique_parts(self) -> Self:
        """Ensure the same part is not submitted twice."""
        part_numbers = [part.part_number for part in self.parts]
        if len(part_numbers) != len(set(part_numbers)):
            raise ValueError("Duplicate part numbers are not allowed")
        return self


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
            detail=_("Invalid attachment purpose"),
        ) from None


async def _verify_project_access(project_id: str, user: User, db: AsyncSession) -> None:
    """Verify the current user can access the attachment's project."""
    if user.is_superuser:
        return

    result = await db.execute(
        refresh_select_statement(
            select(UserProject).where(
                and_(
                    UserProject.user_id == user.id,
                    UserProject.project_id == project_id,
                )
            )
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail=_("Access denied to project"),
        )


async def _get_accessible_attachment_project_ids(
    project_ids: set[str],
    user: User,
    db: AsyncSession,
) -> set[str]:
    """Return project IDs the current user can access for attachment listing."""
    if user.is_superuser:
        return project_ids
    if not project_ids:
        return set()

    result = await db.execute(
        refresh_select_statement(
            select(UserProject.project_id).where(
                and_(
                    UserProject.user_id == user.id,
                    UserProject.project_id.in_(project_ids),
                )
            )
        )
    )
    return set(result.scalars().all())


async def _get_authorized_attachment(
    attachment_id: str,
    user: User,
    tenant_id: str,
    db: AsyncSession,
    attachment_service: AttachmentService,
) -> Attachment:
    """Load an attachment and verify tenant/project access before side effects."""
    attachment = await attachment_service.get(attachment_id)
    if not attachment:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=_("Attachment not found"),
        )

    if not user.is_superuser and attachment.tenant_id != tenant_id:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail=_("Access denied to attachment"),
        )

    await _verify_project_access(attachment.project_id, user, db)
    return attachment


def _validate_part_upload(attachment: Attachment, part_number: int, data: bytes) -> None:
    """Validate a part upload request against attachment metadata."""
    if attachment.total_parts is None or attachment.total_parts <= 0:
        raise HTTPException(status_code=400, detail=_("Invalid upload state"))
    if part_number > attachment.total_parts:
        raise HTTPException(status_code=400, detail=_("Part number exceeds total parts"))
    if not data:
        raise HTTPException(status_code=400, detail=_("Uploaded part cannot be empty"))


def _validate_complete_upload(attachment: Attachment, parts: list[CompleteUploadPart]) -> None:
    """Validate completion request before passing it to object storage."""
    if attachment.total_parts is None or attachment.total_parts <= 0:
        raise HTTPException(status_code=400, detail=_("Invalid upload state"))

    expected_part_numbers = list(range(1, attachment.total_parts + 1))
    submitted_part_numbers = sorted(part.part_number for part in parts)
    if submitted_part_numbers != expected_part_numbers:
        raise HTTPException(
            status_code=400,
            detail=_("Uploaded parts do not match expected part count"),
        )


# === API Endpoints ===


@router.post("/upload/initiate", response_model=InitiateUploadResponse)
async def initiate_multipart_upload(
    request: InitiateUploadRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> InitiateUploadResponse:
    """
    Initialize a multipart upload for large files.

    Use this endpoint for files larger than 10MB. After initialization,
    upload each part using POST /upload/part, then complete with POST /upload/complete.
    """
    try:
        purpose = _parse_purpose(request.purpose)
        await _verify_project_access(request.project_id, current_user, db)

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
        raise HTTPException(status_code=400, detail=_("Invalid upload request")) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to initiate multipart upload: {e}")
        raise HTTPException(status_code=500, detail=_("Failed to initiate upload")) from e


@router.post("/upload/part", response_model=UploadPartResponse)
async def upload_part(
    attachment_id: str = Form(..., description="ID of the attachment"),
    part_number: int = Form(..., ge=1, description="Part number (1-indexed)"),
    file: UploadFile = File(..., description="Part data"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> UploadPartResponse:
    """
    Upload a single part in a multipart upload.

    Part numbers start at 1 and must be uploaded in order.
    Each part (except the last) should be exactly part_size bytes.
    """
    try:
        attachment = await _get_authorized_attachment(
            attachment_id=attachment_id,
            user=current_user,
            tenant_id=tenant_id,
            db=db,
            attachment_service=attachment_service,
        )
        data = await file.read()
        _validate_part_upload(attachment, part_number, data)

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
        raise HTTPException(status_code=400, detail=_("Invalid upload part")) from e
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to upload part")
        raise HTTPException(status_code=500, detail=_("Failed to upload part")) from exc


@router.post("/upload/complete", response_model=AttachmentResponse)
async def complete_multipart_upload(
    request: CompleteUploadRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> AttachmentResponse:
    """
    Complete a multipart upload.

    Call this after all parts have been uploaded successfully.
    The 'parts' array must contain all uploaded parts with their part_number and etag.
    """
    try:
        attachment = await _get_authorized_attachment(
            attachment_id=request.attachment_id,
            user=current_user,
            tenant_id=tenant_id,
            db=db,
            attachment_service=attachment_service,
        )
        _validate_complete_upload(attachment, request.parts)

        # Convert parts to PartUploadResult
        parts = [
            PartUploadResult(
                part_number=part.part_number,
                etag=part.etag,
            )
            for part in sorted(request.parts, key=lambda part: part.part_number)
        ]

        attachment = await attachment_service.complete_multipart_upload(
            attachment_id=request.attachment_id,
            parts=parts,
        )

        return _attachment_to_response(attachment)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=_("Invalid upload completion request")) from e
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to complete multipart upload")
        raise HTTPException(status_code=500, detail=_("Failed to complete upload")) from exc


@router.post("/upload/abort")
async def abort_multipart_upload(
    attachment_id: str = Form(..., description="ID of the attachment"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> dict[str, Any]:
    """
    Abort a multipart upload.

    Use this to cancel an in-progress multipart upload and clean up resources.
    """
    try:
        authorized_attachment = await _get_authorized_attachment(
            attachment_id=attachment_id,
            user=current_user,
            tenant_id=tenant_id,
            db=db,
            attachment_service=attachment_service,
        )
        success = await attachment_service.abort_multipart_upload(authorized_attachment.id)

        if not success:
            raise HTTPException(status_code=404, detail=_("Attachment not found"))

        return {"success": True, "message": "Upload aborted"}

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to abort multipart upload")
        raise HTTPException(status_code=500, detail=_("Failed to abort upload")) from exc


@router.post("/upload/simple", response_model=AttachmentResponse)
async def upload_simple(
    conversation_id: str = Form(..., description="ID of the conversation"),
    project_id: str = Form(..., description="ID of the project"),
    purpose: str = Form(default="both", description="Purpose of the attachment"),
    file: UploadFile = File(..., description="File to upload"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> AttachmentResponse:
    """
    Upload a small file directly (recommended for files ≤10MB).

    For larger files, use the multipart upload endpoints instead.
    """
    try:
        purpose_enum = _parse_purpose(purpose)
        await _verify_project_access(project_id, current_user, db)
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
        raise HTTPException(status_code=400, detail=_("Invalid upload request")) from e
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to upload file")
        raise HTTPException(status_code=500, detail=_("Failed to upload file")) from exc


@router.get("", response_model=AttachmentListResponse)
async def list_attachments(
    conversation_id: str = Query(..., description="Conversation ID to list attachments for"),
    status: str | None = Query(None, description="Filter by status"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> AttachmentListResponse:
    """
    List attachments for a conversation.
    """
    try:
        status_enum = AttachmentStatus(status) if status else None
    except ValueError:
        raise HTTPException(status_code=400, detail=_("Invalid attachment status")) from None

    attachments = await attachment_service.get_by_conversation(
        conversation_id=conversation_id,
        status=status_enum,
    )
    tenant_visible_attachments = (
        attachments
        if current_user.is_superuser
        else [attachment for attachment in attachments if attachment.tenant_id == tenant_id]
    )
    accessible_project_ids = await _get_accessible_attachment_project_ids(
        {attachment.project_id for attachment in tenant_visible_attachments},
        current_user,
        db,
    )
    visible_attachments = [
        attachment
        for attachment in tenant_visible_attachments
        if attachment.project_id in accessible_project_ids
    ]

    return AttachmentListResponse(
        attachments=[_attachment_to_response(a) for a in visible_attachments],
        total=len(visible_attachments),
    )


@router.get("/{attachment_id}", response_model=AttachmentResponse)
async def get_attachment(
    attachment_id: str,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> AttachmentResponse:
    """
    Get attachment details by ID.
    """
    attachment = await _get_authorized_attachment(
        attachment_id=attachment_id,
        user=current_user,
        tenant_id=tenant_id,
        db=db,
        attachment_service=attachment_service,
    )

    return _attachment_to_response(attachment)


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: str,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> RedirectResponse:
    """
    Download an attachment via presigned URL redirect.
    """
    authorized_attachment = await _get_authorized_attachment(
        attachment_id=attachment_id,
        user=current_user,
        tenant_id=tenant_id,
        db=db,
        attachment_service=attachment_service,
    )
    url = await attachment_service.get_download_url(authorized_attachment.id)

    if not url:
        raise HTTPException(status_code=404, detail=_("Attachment not found or not ready"))

    return RedirectResponse(url=url, status_code=302)


@router.delete("/{attachment_id}")
async def delete_attachment(
    attachment_id: str,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    attachment_service: AttachmentService = Depends(get_attachment_service),
) -> dict[str, Any]:
    """
    Delete an attachment.
    """
    authorized_attachment = await _get_authorized_attachment(
        attachment_id=attachment_id,
        user=current_user,
        tenant_id=tenant_id,
        db=db,
        attachment_service=attachment_service,
    )
    success = await attachment_service.delete(authorized_attachment.id)

    if not success:
        raise HTTPException(status_code=404, detail=_("Attachment not found"))

    return {"success": True, "message": "Attachment deleted"}
