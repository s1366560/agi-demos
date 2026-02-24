"""Artifact domain model.

Artifacts represent files, images, videos, and other outputs produced by
sandbox/MCP tool executions that need to be stored and displayed in the UI.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.domain.shared_kernel import Entity


class ArtifactStatus(str, Enum):
    """Status of an artifact in its lifecycle."""

    PENDING = "pending"  # Upload initiated but not complete
    UPLOADING = "uploading"  # Currently uploading to storage
    READY = "ready"  # Successfully stored and accessible
    ERROR = "error"  # Upload or processing failed
    DELETED = "deleted"  # Soft-deleted, pending cleanup


class ArtifactCategory(str, Enum):
    """High-level category of an artifact for UI rendering decisions."""

    IMAGE = "image"  # JPEG, PNG, GIF, WebP, SVG
    VIDEO = "video"  # MP4, WebM, MOV
    AUDIO = "audio"  # MP3, WAV, OGG
    DOCUMENT = "document"  # PDF, DOCX, TXT
    CODE = "code"  # Source code files
    DATA = "data"  # JSON, CSV, XML
    ARCHIVE = "archive"  # ZIP, TAR, GZ
    OTHER = "other"  # Unknown or unsupported types


class ArtifactContentType(str, Enum):
    """Common MIME types for quick matching."""

    # Images
    IMAGE_PNG = "image/png"
    IMAGE_JPEG = "image/jpeg"
    IMAGE_GIF = "image/gif"
    IMAGE_WEBP = "image/webp"
    IMAGE_SVG = "image/svg+xml"

    # Videos
    VIDEO_MP4 = "video/mp4"
    VIDEO_WEBM = "video/webm"
    VIDEO_MOV = "video/quicktime"

    # Audio
    AUDIO_MP3 = "audio/mpeg"
    AUDIO_WAV = "audio/wav"
    AUDIO_OGG = "audio/ogg"

    # Documents
    APPLICATION_PDF = "application/pdf"
    TEXT_PLAIN = "text/plain"
    TEXT_HTML = "text/html"
    TEXT_MARKDOWN = "text/markdown"

    # Code
    TEXT_JAVASCRIPT = "text/javascript"
    TEXT_PYTHON = "text/x-python"
    TEXT_CSS = "text/css"
    APPLICATION_JSON = "application/json"
    TEXT_XML = "text/xml"

    # Data
    TEXT_CSV = "text/csv"

    # Archives
    APPLICATION_ZIP = "application/zip"
    APPLICATION_GZIP = "application/gzip"
    APPLICATION_TAR = "application/x-tar"

    # Binary
    APPLICATION_OCTET_STREAM = "application/octet-stream"


# MIME type to category mapping
MIME_TO_CATEGORY: dict[str, ArtifactCategory] = {
    # Images
    "image/png": ArtifactCategory.IMAGE,
    "image/jpeg": ArtifactCategory.IMAGE,
    "image/jpg": ArtifactCategory.IMAGE,
    "image/gif": ArtifactCategory.IMAGE,
    "image/webp": ArtifactCategory.IMAGE,
    "image/svg+xml": ArtifactCategory.IMAGE,
    "image/bmp": ArtifactCategory.IMAGE,
    "image/tiff": ArtifactCategory.IMAGE,
    # Videos
    "video/mp4": ArtifactCategory.VIDEO,
    "video/webm": ArtifactCategory.VIDEO,
    "video/quicktime": ArtifactCategory.VIDEO,
    "video/x-msvideo": ArtifactCategory.VIDEO,
    "video/x-matroska": ArtifactCategory.VIDEO,
    # Audio
    "audio/mpeg": ArtifactCategory.AUDIO,
    "audio/wav": ArtifactCategory.AUDIO,
    "audio/ogg": ArtifactCategory.AUDIO,
    "audio/webm": ArtifactCategory.AUDIO,
    "audio/mp4": ArtifactCategory.AUDIO,
    # Documents
    "application/pdf": ArtifactCategory.DOCUMENT,
    "application/msword": ArtifactCategory.DOCUMENT,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ArtifactCategory.DOCUMENT,
    "text/plain": ArtifactCategory.DOCUMENT,
    "text/html": ArtifactCategory.DOCUMENT,
    "text/markdown": ArtifactCategory.DOCUMENT,
    # Code
    "text/javascript": ArtifactCategory.CODE,
    "application/javascript": ArtifactCategory.CODE,
    "text/x-python": ArtifactCategory.CODE,
    "text/x-java": ArtifactCategory.CODE,
    "text/x-c": ArtifactCategory.CODE,
    "text/x-c++": ArtifactCategory.CODE,
    "text/css": ArtifactCategory.CODE,
    "text/x-typescript": ArtifactCategory.CODE,
    "text/x-rust": ArtifactCategory.CODE,
    "text/x-go": ArtifactCategory.CODE,
    # Data
    "application/json": ArtifactCategory.DATA,
    "text/xml": ArtifactCategory.DATA,
    "application/xml": ArtifactCategory.DATA,
    "text/csv": ArtifactCategory.DATA,
    "application/x-yaml": ArtifactCategory.DATA,
    "text/yaml": ArtifactCategory.DATA,
    # Archives
    "application/zip": ArtifactCategory.ARCHIVE,
    "application/gzip": ArtifactCategory.ARCHIVE,
    "application/x-gzip": ArtifactCategory.ARCHIVE,
    "application/x-tar": ArtifactCategory.ARCHIVE,
    "application/x-rar-compressed": ArtifactCategory.ARCHIVE,
    "application/x-7z-compressed": ArtifactCategory.ARCHIVE,
}

# File extension to MIME type mapping for detection
EXTENSION_TO_MIME: dict[str, str] = {
    # Images
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    # Videos
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    # Audio
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    # Documents
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    # Code
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".ts": "text/x-typescript",
    ".py": "text/x-python",
    ".java": "text/x-java",
    ".c": "text/x-c",
    ".cpp": "text/x-c++",
    ".h": "text/x-c",
    ".hpp": "text/x-c++",
    ".css": "text/css",
    ".rs": "text/x-rust",
    ".go": "text/x-go",
    ".rb": "text/x-ruby",
    ".php": "text/x-php",
    ".sh": "text/x-shellscript",
    ".bash": "text/x-shellscript",
    ".zsh": "text/x-shellscript",
    # Data
    ".json": "application/json",
    ".xml": "application/xml",
    ".csv": "text/csv",
    ".yaml": "application/x-yaml",
    ".yml": "application/x-yaml",
    # Archives
    ".zip": "application/zip",
    ".gz": "application/gzip",
    ".tar": "application/x-tar",
    ".rar": "application/x-rar-compressed",
    ".7z": "application/x-7z-compressed",
}


def detect_mime_type(filename: str) -> str:
    """Detect MIME type from filename extension."""
    import os

    _, ext = os.path.splitext(filename.lower())
    return EXTENSION_TO_MIME.get(ext, "application/octet-stream")


def get_category_from_mime(mime_type: str) -> ArtifactCategory:
    """Get artifact category from MIME type."""
    # Normalize mime type
    mime_lower = mime_type.lower().split(";")[0].strip()
    return MIME_TO_CATEGORY.get(mime_lower, ArtifactCategory.OTHER)


@dataclass(kw_only=True)
class Artifact(Entity):
    """Artifact entity representing a file output from tool execution.

    Artifacts are immutable once created (except for status transitions).
    They are stored in MinIO and associated with specific tool executions.

    Attributes:
        project_id: The project this artifact belongs to
        tenant_id: Tenant ID for multi-tenancy scoping
        sandbox_id: The sandbox that produced this artifact (optional)
        tool_execution_id: The specific tool execution that created it
        conversation_id: The conversation context (optional)

        filename: Original filename
        mime_type: MIME content type
        category: High-level category for UI rendering
        size_bytes: File size in bytes

        object_key: Storage object key (MinIO/S3 path)
        url: Public/presigned URL for access (may expire)
        preview_url: Optional thumbnail/preview URL

        status: Current artifact status
        error_message: Error description if status is ERROR

        source_tool: Name of the tool that created this artifact
        source_path: Original path in sandbox filesystem

        metadata: Additional metadata (e.g., dimensions for images)
        created_at: Creation timestamp
    """

    # Ownership & context
    project_id: str
    tenant_id: str
    sandbox_id: str | None = None
    tool_execution_id: str | None = None
    conversation_id: str | None = None

    # File information
    filename: str
    mime_type: str
    category: ArtifactCategory = field(default=ArtifactCategory.OTHER)
    size_bytes: int = 0

    # Storage references
    object_key: str = ""
    url: str | None = None
    preview_url: str | None = None

    # Status
    status: ArtifactStatus = ArtifactStatus.PENDING
    error_message: str | None = None

    # Source information
    source_tool: str | None = None
    source_path: str | None = None

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self):
        """Auto-detect category from mime_type if not set."""
        if self.category == ArtifactCategory.OTHER and self.mime_type:
            self.category = get_category_from_mime(self.mime_type)

    def mark_uploading(self) -> None:
        """Mark artifact as uploading."""
        self.status = ArtifactStatus.UPLOADING

    def mark_ready(self, url: str, preview_url: str | None = None) -> None:
        """Mark artifact as ready with access URL."""
        self.status = ArtifactStatus.READY
        self.url = url
        if preview_url:
            self.preview_url = preview_url

    def mark_error(self, message: str) -> None:
        """Mark artifact as having an error."""
        self.status = ArtifactStatus.ERROR
        self.error_message = message

    def mark_deleted(self) -> None:
        """Mark artifact as deleted (soft delete)."""
        self.status = ArtifactStatus.DELETED

    def is_displayable(self) -> bool:
        """Check if artifact can be displayed inline."""
        return self.category in (
            ArtifactCategory.IMAGE,
            ArtifactCategory.VIDEO,
            ArtifactCategory.AUDIO,
            ArtifactCategory.CODE,
            ArtifactCategory.DATA,
        )

    def is_previewable(self) -> bool:
        """Check if artifact supports thumbnail preview."""
        return self.category == ArtifactCategory.IMAGE

    def to_dict(self) -> dict[str, Any]:
        """Convert artifact to dictionary for API responses."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "sandbox_id": self.sandbox_id,
            "tool_execution_id": self.tool_execution_id,
            "conversation_id": self.conversation_id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "category": self.category.value,
            "size_bytes": self.size_bytes,
            "object_key": self.object_key,
            "url": self.url,
            "preview_url": self.preview_url,
            "status": self.status.value,
            "error_message": self.error_message,
            "source_tool": self.source_tool,
            "source_path": self.source_path,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }
