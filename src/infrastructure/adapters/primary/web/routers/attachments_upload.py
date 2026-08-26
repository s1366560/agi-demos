"""Attachment API routes for file uploads.

Provides REST API endpoints for:
- Simple file upload (small files ≤10MB)
- Multipart upload initiation, part upload, completion
- Attachment download and deletion
"""

import logging
from typing import Any, Self

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

from src.domain.model.agent.attachment import (
    DEFAULT_PART_SIZE,
    Attachment,
    AttachmentPurpose,
    AttachmentStatus,
)
from src.domain.ports.services.storage_service_port import PartUploadResult
from src.infrastructure.adapters.primary.web.attachment_application_authority_v2 import (
    AttachmentApplicationAuthorityV2,
    attachment_application_authority_dependency_v2,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.attachment_services import (
    AttachmentAccessDeniedV2,
    AttachmentNotFoundV2,
    AttachmentProjectAccessDeniedV2,
    AttachmentServiceErrorV2,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/attachments", tags=["attachments"])

_ATTACHMENT_HTTP_ERROR_SPECS: dict[type[AttachmentServiceErrorV2], tuple[int, str]] = {
    AttachmentProjectAccessDeniedV2: (
        http_status.HTTP_403_FORBIDDEN,
        "Access denied to project",
    ),
    AttachmentNotFoundV2: (http_status.HTTP_404_NOT_FOUND, "Attachment not found"),
    AttachmentAccessDeniedV2: (
        http_status.HTTP_403_FORBIDDEN,
        "Access denied to attachment",
    ),
}


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


def _attachment_http_error(error: AttachmentServiceErrorV2) -> HTTPException:
    status_code, detail = _ATTACHMENT_HTTP_ERROR_SPECS.get(
        type(error),
        (http_status.HTTP_400_BAD_REQUEST, "Attachment operation failed"),
    )
    return HTTPException(status_code=status_code, detail=_(detail))


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
    attachment_application: AttachmentApplicationAuthorityV2 = Depends(
        attachment_application_authority_dependency_v2
    ),
) -> InitiateUploadResponse:
    """
    Initialize a multipart upload for large files.

    Use this endpoint for files larger than 10MB. After initialization,
    upload each part using POST /upload/part, then complete with POST /upload/complete.
    """
    try:
        attachments = attachment_application.services.attachments
        purpose = _parse_purpose(request.purpose)
        project_tenant_id = await attachments.require_project_tenant(request.project_id)

        attachment = await attachments.service.initiate_multipart_upload(
            tenant_id=project_tenant_id,
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
    except AttachmentServiceErrorV2 as error:
        raise _attachment_http_error(error) from error
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to initiate multipart upload: error_type=%s",
            type(e).__name__,
        )
        raise HTTPException(status_code=500, detail=_("Failed to initiate upload")) from e


@router.post("/upload/part", response_model=UploadPartResponse)
async def upload_part(
    attachment_id: str = Form(..., description="ID of the attachment"),
    part_number: int = Form(..., ge=1, description="Part number (1-indexed)"),
    file: UploadFile = File(..., description="Part data"),
    attachment_application: AttachmentApplicationAuthorityV2 = Depends(
        attachment_application_authority_dependency_v2
    ),
) -> UploadPartResponse:
    """
    Upload a single part in a multipart upload.

    Part numbers start at 1 and must be uploaded in order.
    Each part (except the last) should be exactly part_size bytes.
    """
    try:
        attachments = attachment_application.services.attachments
        attachment = await attachments.get_authorized(attachment_id)
        data = await file.read()
        _validate_part_upload(attachment, part_number, data)

        result = await attachments.service.upload_part(
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
    except AttachmentServiceErrorV2 as error:
        raise _attachment_http_error(error) from error
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to upload part")
        raise HTTPException(status_code=500, detail=_("Failed to upload part")) from exc


@router.post("/upload/complete", response_model=AttachmentResponse)
async def complete_multipart_upload(
    request: CompleteUploadRequest,
    attachment_application: AttachmentApplicationAuthorityV2 = Depends(
        attachment_application_authority_dependency_v2
    ),
) -> AttachmentResponse:
    """
    Complete a multipart upload.

    Call this after all parts have been uploaded successfully.
    The 'parts' array must contain all uploaded parts with their part_number and etag.
    """
    try:
        attachments = attachment_application.services.attachments
        attachment = await attachments.get_authorized(request.attachment_id)
        _validate_complete_upload(attachment, request.parts)

        # Convert parts to PartUploadResult
        parts = [
            PartUploadResult(
                part_number=part.part_number,
                etag=part.etag,
            )
            for part in sorted(request.parts, key=lambda part: part.part_number)
        ]

        attachment = await attachments.service.complete_multipart_upload(
            attachment_id=request.attachment_id,
            parts=parts,
        )

        return _attachment_to_response(attachment)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=_("Invalid upload completion request")) from e
    except AttachmentServiceErrorV2 as error:
        raise _attachment_http_error(error) from error
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to complete multipart upload")
        raise HTTPException(status_code=500, detail=_("Failed to complete upload")) from exc


@router.post("/upload/abort")
async def abort_multipart_upload(
    attachment_id: str = Form(..., description="ID of the attachment"),
    attachment_application: AttachmentApplicationAuthorityV2 = Depends(
        attachment_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """
    Abort a multipart upload.

    Use this to cancel an in-progress multipart upload and clean up resources.
    """
    try:
        attachments = attachment_application.services.attachments
        authorized_attachment = await attachments.get_authorized(attachment_id)
        success = await attachments.service.abort_multipart_upload(authorized_attachment.id)

        if not success:
            raise HTTPException(status_code=404, detail=_("Attachment not found"))

        return {"success": True, "message": "Upload aborted"}

    except AttachmentServiceErrorV2 as error:
        raise _attachment_http_error(error) from error
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
    attachment_application: AttachmentApplicationAuthorityV2 = Depends(
        attachment_application_authority_dependency_v2
    ),
) -> AttachmentResponse:
    """
    Upload a small file directly (recommended for files ≤10MB).

    For larger files, use the multipart upload endpoints instead.
    """
    try:
        attachments = attachment_application.services.attachments
        purpose_enum = _parse_purpose(purpose)
        project_tenant_id = await attachments.require_project_tenant(project_id)
        data = await file.read()

        attachment = await attachments.service.upload_simple(
            tenant_id=project_tenant_id,
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
    except AttachmentServiceErrorV2 as error:
        raise _attachment_http_error(error) from error
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to upload file")
        raise HTTPException(status_code=500, detail=_("Failed to upload file")) from exc


@router.get("", response_model=AttachmentListResponse)
async def list_attachments(
    conversation_id: str = Query(..., description="Conversation ID to list attachments for"),
    status: str | None = Query(None, description="Filter by status"),
    attachment_application: AttachmentApplicationAuthorityV2 = Depends(
        attachment_application_authority_dependency_v2
    ),
) -> AttachmentListResponse:
    """
    List attachments for a conversation.
    """
    try:
        status_enum = AttachmentStatus(status) if status else None
    except ValueError:
        raise HTTPException(status_code=400, detail=_("Invalid attachment status")) from None

    visible_attachments = await attachment_application.services.attachments.list_visible(
        conversation_id=conversation_id,
        status=status_enum,
    )

    return AttachmentListResponse(
        attachments=[_attachment_to_response(a) for a in visible_attachments],
        total=len(visible_attachments),
    )


@router.get("/{attachment_id}", response_model=AttachmentResponse)
async def get_attachment(
    attachment_id: str,
    attachment_application: AttachmentApplicationAuthorityV2 = Depends(
        attachment_application_authority_dependency_v2
    ),
) -> AttachmentResponse:
    """
    Get attachment details by ID.
    """
    try:
        attachment = await attachment_application.services.attachments.get_authorized(attachment_id)
    except AttachmentServiceErrorV2 as error:
        raise _attachment_http_error(error) from error

    return _attachment_to_response(attachment)


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: str,
    attachment_application: AttachmentApplicationAuthorityV2 = Depends(
        attachment_application_authority_dependency_v2
    ),
) -> RedirectResponse:
    """
    Download an attachment via presigned URL redirect.
    """
    attachments = attachment_application.services.attachments
    try:
        authorized_attachment = await attachments.get_authorized(attachment_id)
    except AttachmentServiceErrorV2 as error:
        raise _attachment_http_error(error) from error
    url = await attachments.service.get_download_url(authorized_attachment.id)

    if not url:
        raise HTTPException(status_code=404, detail=_("Attachment not found or not ready"))

    return RedirectResponse(url=url, status_code=302)


@router.delete("/{attachment_id}")
async def delete_attachment(
    attachment_id: str,
    attachment_application: AttachmentApplicationAuthorityV2 = Depends(
        attachment_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """
    Delete an attachment.
    """
    attachments = attachment_application.services.attachments
    try:
        authorized_attachment = await attachments.get_authorized(attachment_id)
    except AttachmentServiceErrorV2 as error:
        raise _attachment_http_error(error) from error
    success = await attachments.service.delete(authorized_attachment.id)

    if not success:
        raise HTTPException(status_code=404, detail=_("Attachment not found"))

    return {"success": True, "message": "Attachment deleted"}
