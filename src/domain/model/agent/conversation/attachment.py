"""Attachment entity for conversation file uploads."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class AttachmentPurpose(str, Enum):
    """Purpose of the attachment - how it will be used."""

    LLM_CONTEXT = "llm_context"  # Send to LLM for multimodal understanding
    SANDBOX_INPUT = "sandbox_input"  # Upload to sandbox for tool execution
    BOTH = "both"  # Both LLM understanding and sandbox access


class AttachmentStatus(str, Enum):
    """Status of the attachment upload/processing."""

    PENDING = "pending"  # Multipart upload in progress
    UPLOADED = "uploaded"  # Upload completed to storage
    PROCESSING = "processing"  # Being processed (e.g., importing to sandbox)
    READY = "ready"  # Ready for use
    FAILED = "failed"  # Upload or processing failed
    EXPIRED = "expired"  # Expired and cleaned up


@dataclass(frozen=True)
class AttachmentMetadata:
    """
    Metadata for an attachment (immutable value object).

    Contains optional file-specific information like dimensions for images,
    duration for media, or page count for documents.
    """

    width: int | None = None  # Image width in pixels
    height: int | None = None  # Image height in pixels
    duration: float | None = None  # Audio/video duration in seconds
    pages: int | None = None  # Document page count
    encoding: str | None = None  # Text file encoding
    extra: dict[str, Any] | None = None  # Additional metadata

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        result = {}
        if self.width is not None:
            result["width"] = self.width
        if self.height is not None:
            result["height"] = self.height
        if self.duration is not None:
            result["duration"] = self.duration
        if self.pages is not None:
            result["pages"] = self.pages
        if self.encoding is not None:
            result["encoding"] = self.encoding
        if self.extra is not None:
            result["extra"] = self.extra
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AttachmentMetadata":
        """Create from dictionary."""
        if not data:
            return cls()
        return cls(
            width=data.get("width"),
            height=data.get("height"),
            duration=data.get("duration"),
            pages=data.get("pages"),
            encoding=data.get("encoding"),
            extra=data.get("extra"),
        )


@dataclass(kw_only=True)
class Attachment:
    """
    Attachment entity for conversation file uploads.

    Represents a file uploaded by the user that can be:
    - Sent to LLM for multimodal understanding (images, documents)
    - Imported to sandbox for tool execution (any file type)
    - Both of the above

    Supports multipart upload for large files (>10MB).
    """

    id: str
    conversation_id: str
    project_id: str
    tenant_id: str

    # File information
    filename: str
    mime_type: str
    size_bytes: int
    object_key: str  # S3 storage path

    # Purpose and status
    purpose: AttachmentPurpose
    status: AttachmentStatus = AttachmentStatus.PENDING

    # Multipart upload tracking
    upload_id: str | None = None  # S3 multipart upload ID
    total_parts: int | None = None  # Total number of parts
    uploaded_parts: int = 0  # Number of parts uploaded so far

    # Sandbox integration
    sandbox_path: str | None = None  # Path after import to sandbox

    # Metadata
    metadata: AttachmentMetadata = field(default_factory=AttachmentMetadata)

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    # Error tracking
    error_message: str | None = None

    def __post_init__(self):
        """Validate attachment after initialization."""
        if not self.filename:
            raise ValueError("Filename cannot be empty")
        if self.size_bytes < 0:
            raise ValueError("Size cannot be negative")

    def is_image(self) -> bool:
        """Check if this attachment is an image."""
        return self.mime_type.startswith("image/")

    def is_document(self) -> bool:
        """Check if this attachment is a document (PDF, Word, text)."""
        document_types = [
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/plain",
            "text/markdown",
            "text/csv",
        ]
        return self.mime_type in document_types or self.mime_type.startswith("text/")

    def is_audio(self) -> bool:
        """Check if this attachment is audio."""
        return self.mime_type.startswith("audio/")

    def is_video(self) -> bool:
        """Check if this attachment is video."""
        return self.mime_type.startswith("video/")

    def needs_llm_processing(self) -> bool:
        """Check if this attachment should be sent to LLM."""
        return self.purpose in [AttachmentPurpose.LLM_CONTEXT, AttachmentPurpose.BOTH]

    def needs_sandbox_import(self) -> bool:
        """Check if this attachment should be imported to sandbox."""
        return self.purpose in [AttachmentPurpose.SANDBOX_INPUT, AttachmentPurpose.BOTH]

    def is_multipart_upload(self) -> bool:
        """Check if this is a multipart upload."""
        return self.upload_id is not None

    def is_upload_complete(self) -> bool:
        """Check if upload is complete."""
        return self.status in [
            AttachmentStatus.UPLOADED,
            AttachmentStatus.PROCESSING,
            AttachmentStatus.READY,
        ]

    def can_be_used(self) -> bool:
        """Check if this attachment is ready to be used."""
        return self.status in [AttachmentStatus.UPLOADED, AttachmentStatus.READY]

    def mark_uploaded(self) -> None:
        """Mark the attachment as uploaded."""
        self.status = AttachmentStatus.UPLOADED
        self.upload_id = None  # Clear multipart upload ID

    def mark_processing(self) -> None:
        """Mark the attachment as being processed."""
        self.status = AttachmentStatus.PROCESSING

    def mark_ready(self, sandbox_path: str | None = None) -> None:
        """Mark the attachment as ready for use."""
        self.status = AttachmentStatus.READY
        if sandbox_path:
            self.sandbox_path = sandbox_path

    def mark_failed(self, error_message: str) -> None:
        """Mark the attachment as failed."""
        self.status = AttachmentStatus.FAILED
        self.error_message = error_message

    def mark_expired(self) -> None:
        """Mark the attachment as expired."""
        self.status = AttachmentStatus.EXPIRED

    def update_upload_progress(self, parts_uploaded: int) -> None:
        """Update the multipart upload progress."""
        self.uploaded_parts = parts_uploaded

    def get_upload_progress(self) -> float:
        """Get upload progress as percentage (0.0 to 1.0)."""
        if not self.total_parts or self.total_parts == 0:
            return 1.0 if self.is_upload_complete() else 0.0
        return self.uploaded_parts / self.total_parts

    def get_file_extension(self) -> str:
        """Get the file extension from filename."""
        if "." in self.filename:
            return self.filename.rsplit(".", 1)[-1].lower()
        return ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "object_key": self.object_key,
            "purpose": self.purpose.value,
            "status": self.status.value,
            "upload_id": self.upload_id,
            "total_parts": self.total_parts,
            "uploaded_parts": self.uploaded_parts,
            "sandbox_path": self.sandbox_path,
            "metadata": self.metadata.to_dict(),
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "error_message": self.error_message,
        }


# Default file size limits by purpose (in bytes)
DEFAULT_MAX_SIZE_LLM_MB = 100
DEFAULT_MAX_SIZE_SANDBOX_MB = 100

FILE_SIZE_LIMITS = {
    AttachmentPurpose.LLM_CONTEXT: DEFAULT_MAX_SIZE_LLM_MB * 1024 * 1024,
    AttachmentPurpose.SANDBOX_INPUT: DEFAULT_MAX_SIZE_SANDBOX_MB * 1024 * 1024,
    AttachmentPurpose.BOTH: DEFAULT_MAX_SIZE_LLM_MB * 1024 * 1024,  # Use LLM limit (stricter)
}


def build_file_size_limits(
    llm_max_mb: int = DEFAULT_MAX_SIZE_LLM_MB,
    sandbox_max_mb: int = DEFAULT_MAX_SIZE_SANDBOX_MB,
) -> dict:
    """Build file size limits dict from configurable MB values."""
    return {
        AttachmentPurpose.LLM_CONTEXT: llm_max_mb * 1024 * 1024,
        AttachmentPurpose.SANDBOX_INPUT: sandbox_max_mb * 1024 * 1024,
        AttachmentPurpose.BOTH: min(llm_max_mb, sandbox_max_mb) * 1024 * 1024,
    }

# Allowed MIME types by purpose
ALLOWED_MIME_TYPES = {
    AttachmentPurpose.LLM_CONTEXT: [
        "image/*",  # All images
        "video/*",  # All videos
        "audio/*",  # All audio
        "application/pdf",
        "text/*",  # All text files
        # Microsoft Office formats
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
        "application/vnd.ms-excel",  # .xls
        "application/msword",  # .doc
        "application/vnd.ms-powerpoint",  # .ppt
        # OpenDocument formats
        "application/vnd.oasis.opendocument.spreadsheet",  # .ods
        "application/vnd.oasis.opendocument.text",  # .odt
        "application/vnd.oasis.opendocument.presentation",  # .odp
        # CSV and common data formats
        "text/csv",
        "application/csv",
    ],
    AttachmentPurpose.SANDBOX_INPUT: ["*/*"],  # All types allowed
    AttachmentPurpose.BOTH: [
        "image/*",
        "video/*",  # All videos
        "audio/*",  # All audio
        "application/pdf",
        "text/*",
        # Microsoft Office formats
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
        "application/vnd.ms-excel",  # .xls
        "application/msword",  # .doc
        "application/vnd.ms-powerpoint",  # .ppt
        # OpenDocument formats
        "application/vnd.oasis.opendocument.spreadsheet",  # .ods
        "application/vnd.oasis.opendocument.text",  # .odt
        "application/vnd.oasis.opendocument.presentation",  # .odp
        # CSV and common data formats
        "text/csv",
        "application/csv",
    ],
}

# Minimum part size for multipart upload (S3 requirement)
MIN_PART_SIZE = 5 * 1024 * 1024  # 5MB

# Default part size for multipart upload
DEFAULT_PART_SIZE = 5 * 1024 * 1024  # 5MB

# Threshold for using multipart upload
MULTIPART_THRESHOLD = 10 * 1024 * 1024  # 10MB
