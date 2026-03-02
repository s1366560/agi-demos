"""Backward compatibility - re-exports from conversation subpackage."""

from src.domain.model.agent.conversation.attachment import (
    ALLOWED_MIME_TYPES,
    DEFAULT_MAX_SIZE_LLM_MB,
    DEFAULT_MAX_SIZE_SANDBOX_MB,
    DEFAULT_PART_SIZE,
    FILE_SIZE_LIMITS,
    MIN_PART_SIZE,
    MULTIPART_THRESHOLD,
    Attachment,
    AttachmentMetadata,
    AttachmentPurpose,
    AttachmentStatus,
    build_file_size_limits,
)

__all__ = [
    "ALLOWED_MIME_TYPES",
    "DEFAULT_MAX_SIZE_LLM_MB",
    "DEFAULT_MAX_SIZE_SANDBOX_MB",
    "DEFAULT_PART_SIZE",
    "FILE_SIZE_LIMITS",
    "MIN_PART_SIZE",
    "MULTIPART_THRESHOLD",
    "Attachment",
    "AttachmentMetadata",
    "AttachmentPurpose",
    "AttachmentStatus",
    "build_file_size_limits",
]
