"""Attachment Service - Application service for file attachments.

Manages file uploads (including multipart), storage, and preparation
for LLM multimodal understanding and sandbox import.
"""

import base64
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from src.domain.model.agent.attachment import (
    ALLOWED_MIME_TYPES,
    DEFAULT_PART_SIZE,
    MULTIPART_THRESHOLD,
    Attachment,
    AttachmentMetadata,
    AttachmentPurpose,
    AttachmentStatus,
    build_file_size_limits,
)
from src.domain.ports.repositories.attachment_repository import AttachmentRepositoryPort
from src.domain.ports.services.storage_service_port import (
    PartUploadResult,
    StorageServicePort,
)

logger = logging.getLogger(__name__)


class AttachmentService:
    """
    Application service for managing file attachments.

    Handles file upload (simple and multipart), storage operations,
    and preparation of attachments for LLM and sandbox use.
    """

    def __init__(
        self,
        storage_service: StorageServicePort,
        attachment_repository: AttachmentRepositoryPort,
        bucket_prefix: str = "attachments",
        default_expiration_hours: int = 24,
        upload_max_size_llm_mb: int = 100,
        upload_max_size_sandbox_mb: int = 100,
    ) -> None:
        """
        Initialize the attachment service.

        Args:
            storage_service: Storage service for file operations
            attachment_repository: Repository for attachment persistence
            bucket_prefix: Prefix for storage object keys
            default_expiration_hours: Default expiration time for attachments
            upload_max_size_llm_mb: Max upload size for LLM context in MB
            upload_max_size_sandbox_mb: Max upload size for sandbox input in MB
        """
        self._storage = storage_service
        self._repo = attachment_repository
        self._bucket_prefix = bucket_prefix
        self._default_expiration_hours = default_expiration_hours
        self._file_size_limits = build_file_size_limits(
            llm_max_mb=upload_max_size_llm_mb,
            sandbox_max_mb=upload_max_size_sandbox_mb,
        )

    def _generate_object_key(
        self,
        tenant_id: str,
        project_id: str,
        conversation_id: str,
        filename: str,
    ) -> str:
        """Generate a unique S3 object key for the attachment."""
        # Extract extension
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        unique_id = uuid.uuid4().hex[:12]
        timestamp = datetime.now(UTC).strftime("%Y%m%d")

        if ext:
            key = f"{self._bucket_prefix}/{tenant_id}/{project_id}/{conversation_id}/{timestamp}_{unique_id}.{ext}"
        else:
            key = f"{self._bucket_prefix}/{tenant_id}/{project_id}/{conversation_id}/{timestamp}_{unique_id}"

        return key

    def validate_file(
        self,
        filename: str,
        mime_type: str,
        size_bytes: int,
        purpose: AttachmentPurpose,
    ) -> tuple[bool, str | None]:
        """
        Validate file against size and type restrictions.

        Args:
            filename: Name of the file
            mime_type: MIME type of the file
            size_bytes: Size of the file in bytes
            purpose: Intended purpose of the attachment

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check size limit
        max_size = self._file_size_limits.get(
            purpose, self._file_size_limits[AttachmentPurpose.BOTH]
        )
        if size_bytes > max_size:
            max_mb = max_size // (1024 * 1024)
            return False, f"File size exceeds limit ({max_mb}MB for {purpose.value})"

        # Check MIME type
        allowed_types = ALLOWED_MIME_TYPES.get(purpose, ALLOWED_MIME_TYPES[AttachmentPurpose.BOTH])

        if "*/*" not in allowed_types:
            type_allowed = False
            for allowed in allowed_types:
                if allowed.endswith("/*"):
                    # Wildcard match (e.g., "image/*")
                    prefix = allowed[:-2]
                    if mime_type.startswith(prefix):
                        type_allowed = True
                        break
                elif mime_type == allowed:
                    type_allowed = True
                    break

            if not type_allowed:
                return False, f"File type '{mime_type}' not allowed for {purpose.value}"

        return True, None

    async def get(self, attachment_id: str) -> Attachment | None:
        """Get an attachment by ID."""
        return await self._repo.get(attachment_id)

    async def get_by_ids(self, attachment_ids: list[str]) -> list[Attachment]:
        """Get multiple attachments by their IDs."""
        return await self._repo.get_by_ids(attachment_ids)

    async def get_by_conversation(
        self,
        conversation_id: str,
        status: AttachmentStatus | None = None,
    ) -> list[Attachment]:
        """Get all attachments for a conversation."""
        return await self._repo.get_by_conversation(conversation_id, status)

    # ==================== Simple Upload ====================

    async def upload_simple(
        self,
        tenant_id: str,
        project_id: str,
        conversation_id: str,
        filename: str,
        mime_type: str,
        data: bytes,
        purpose: AttachmentPurpose,
        metadata: AttachmentMetadata | None = None,
    ) -> Attachment:
        """
        Upload a small file directly (≤10MB recommended).

        Args:
            tenant_id: Tenant ID
            project_id: Project ID
            conversation_id: Conversation ID
            filename: Original filename
            mime_type: MIME type of the file
            data: File content as bytes
            purpose: Intended purpose of the attachment
            metadata: Optional file metadata

        Returns:
            Created attachment entity

        Raises:
            ValueError: If validation fails
        """
        size_bytes = len(data)

        # Validate
        valid, error = self.validate_file(filename, mime_type, size_bytes, purpose)
        if not valid:
            raise ValueError(error)

        # Generate object key
        object_key = self._generate_object_key(tenant_id, project_id, conversation_id, filename)

        # Upload to storage
        await self._storage.upload_file(
            file_content=data,
            object_key=object_key,
            content_type=mime_type,
            metadata={"filename": filename, "purpose": purpose.value},
        )

        # Create attachment record
        attachment = Attachment(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            project_id=project_id,
            tenant_id=tenant_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            object_key=object_key,
            purpose=purpose,
            status=AttachmentStatus.UPLOADED,
            metadata=metadata or AttachmentMetadata(),
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=self._default_expiration_hours),
        )

        await self._repo.save(attachment)
        logger.info(f"Uploaded attachment: {attachment.id} ({filename}, {size_bytes} bytes)")

        return attachment

    # ==================== Multipart Upload ====================

    async def initiate_multipart_upload(
        self,
        tenant_id: str,
        project_id: str,
        conversation_id: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        purpose: AttachmentPurpose,
        metadata: AttachmentMetadata | None = None,
    ) -> Attachment:
        """
        Initialize a multipart upload for large files.

        Args:
            tenant_id: Tenant ID
            project_id: Project ID
            conversation_id: Conversation ID
            filename: Original filename
            mime_type: MIME type of the file
            size_bytes: Total size of the file
            purpose: Intended purpose of the attachment
            metadata: Optional file metadata

        Returns:
            Attachment with upload_id set for subsequent part uploads

        Raises:
            ValueError: If validation fails
        """
        # Validate
        valid, error = self.validate_file(filename, mime_type, size_bytes, purpose)
        if not valid:
            raise ValueError(error)

        # Calculate number of parts
        total_parts = (size_bytes + DEFAULT_PART_SIZE - 1) // DEFAULT_PART_SIZE

        # Generate object key
        object_key = self._generate_object_key(tenant_id, project_id, conversation_id, filename)

        # Create multipart upload in S3
        result = await self._storage.create_multipart_upload(
            object_key=object_key,
            content_type=mime_type,
            metadata={"filename": filename, "purpose": purpose.value},
        )

        # Create attachment record
        attachment = Attachment(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            project_id=project_id,
            tenant_id=tenant_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            object_key=object_key,
            purpose=purpose,
            status=AttachmentStatus.PENDING,
            upload_id=result.upload_id,
            total_parts=total_parts,
            uploaded_parts=0,
            metadata=metadata or AttachmentMetadata(),
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=self._default_expiration_hours),
        )

        await self._repo.save(attachment)
        logger.info(
            f"Initiated multipart upload: {attachment.id} ({filename}, "
            f"{size_bytes} bytes, {total_parts} parts)"
        )

        return attachment

    async def upload_part(
        self,
        attachment_id: str,
        part_number: int,
        data: bytes,
    ) -> PartUploadResult:
        """
        Upload a single part in a multipart upload.

        Args:
            attachment_id: ID of the attachment
            part_number: Part number (1-indexed)
            data: Part content as bytes

        Returns:
            PartUploadResult with part_number and etag

        Raises:
            ValueError: If attachment not found or not in pending state
        """
        attachment = await self._repo.get(attachment_id)
        if not attachment:
            raise ValueError(f"Attachment not found: {attachment_id}")

        if attachment.status != AttachmentStatus.PENDING:
            raise ValueError(f"Attachment is not in pending state: {attachment.status.value}")

        if not attachment.upload_id:
            raise ValueError("Attachment does not have an active multipart upload")

        # Upload part to S3
        result = await self._storage.upload_part(
            object_key=attachment.object_key,
            upload_id=attachment.upload_id,
            part_number=part_number,
            data=data,
        )

        # Update progress
        await self._repo.update_upload_progress(attachment_id, attachment.uploaded_parts + 1)

        logger.debug(f"Uploaded part {part_number}/{attachment.total_parts} for {attachment_id}")

        return result

    async def complete_multipart_upload(
        self,
        attachment_id: str,
        parts: list[PartUploadResult],
    ) -> Attachment:
        """
        Complete a multipart upload.

        Args:
            attachment_id: ID of the attachment
            parts: List of PartUploadResult from uploaded parts

        Returns:
            Updated attachment entity

        Raises:
            ValueError: If attachment not found or invalid state
        """
        attachment = await self._repo.get(attachment_id)
        if not attachment:
            raise ValueError(f"Attachment not found: {attachment_id}")

        if attachment.status != AttachmentStatus.PENDING:
            raise ValueError(f"Attachment is not in pending state: {attachment.status.value}")

        if not attachment.upload_id:
            raise ValueError("Attachment does not have an active multipart upload")

        # Complete multipart upload in S3
        await self._storage.complete_multipart_upload(
            object_key=attachment.object_key,
            upload_id=attachment.upload_id,
            parts=parts,
        )

        # Update attachment status
        attachment.mark_uploaded()
        await self._repo.save(attachment)

        logger.info(f"Completed multipart upload: {attachment_id}")

        return attachment

    async def abort_multipart_upload(self, attachment_id: str) -> bool:
        """
        Abort a multipart upload.

        Args:
            attachment_id: ID of the attachment

        Returns:
            True if aborted successfully
        """
        attachment = await self._repo.get(attachment_id)
        if not attachment:
            return False

        if attachment.upload_id:
            await self._storage.abort_multipart_upload(
                object_key=attachment.object_key,
                upload_id=attachment.upload_id,
            )

        attachment.mark_failed("Upload aborted")
        await self._repo.save(attachment)

        logger.info(f"Aborted multipart upload: {attachment_id}")
        return True

    # ==================== LLM Integration ====================

    async def prepare_for_llm(
        self,
        attachment: Attachment,
    ) -> dict[str, Any]:
        """
        Prepare attachment for LLM multimodal message.

        Converts the attachment to the appropriate format for LLM API:
        - Images: base64 data URL
        - Documents: extracted text or file info
        - Others: file info description

        Args:
            attachment: The attachment to prepare

        Returns:
            Dict suitable for LLM message content

        Raises:
            ValueError: If attachment not ready or not intended for LLM
        """
        if not attachment.needs_llm_processing():
            raise ValueError("Attachment is not intended for LLM processing")

        if not attachment.can_be_used():
            raise ValueError(f"Attachment is not ready: {attachment.status.value}")

        # Get file content
        content = await self._storage.get_file(attachment.object_key)
        if not content:
            raise ValueError("File not found in storage")

        # Images: return as base64 data URL
        if attachment.is_image():
            b64 = base64.b64encode(content).decode("utf-8")
            return {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{attachment.mime_type};base64,{b64}",
                    "detail": "auto",
                },
            }

        # Text files: return as text block
        if attachment.mime_type.startswith("text/") or attachment.mime_type in [
            "application/json",
            "application/xml",
            "application/javascript",
        ]:
            try:
                text = content.decode("utf-8")
                return {
                    "type": "text",
                    "text": f"=== File: {attachment.filename} ===\n{text}\n=== End of file ===",
                }
            except UnicodeDecodeError:
                pass

        # PDF: can be processed by vision models
        if attachment.mime_type == "application/pdf":
            # TODO: Consider converting PDF pages to images for vision models
            # For now, return file info
            # Note: sandbox_path is set by the caller, default to /workspace/{filename}
            sandbox_path = attachment.sandbox_path or f"/workspace/{attachment.filename}"
            return {
                "type": "text",
                "text": (
                    f"[Document: {attachment.filename}]\n"
                    f"Type: {attachment.mime_type}\n"
                    f"Size: {attachment.size_bytes} bytes\n"
                    f"Sandbox Path: {sandbox_path}"
                ),
            }

        # Other files: return file info
        return {
            "type": "text",
            "text": (
                f"[Attachment: {attachment.filename}]\n"
                f"Type: {attachment.mime_type}\n"
                f"Size: {attachment.size_bytes} bytes"
            ),
        }

    async def prepare_for_llm_batch(
        self,
        attachments: list[Attachment],
    ) -> list[dict[str, Any]]:
        """
        Prepare multiple attachments for LLM.

        Args:
            attachments: List of attachments to prepare

        Returns:
            List of content parts for LLM message
        """
        parts = []
        for attachment in attachments:
            if attachment.needs_llm_processing() and attachment.can_be_used():
                try:
                    part = await self.prepare_for_llm(attachment)
                    parts.append(part)
                except Exception as e:
                    logger.warning(f"Failed to prepare attachment {attachment.id} for LLM: {e}")
        return parts

    # ==================== Sandbox Integration ====================

    async def prepare_for_sandbox(
        self,
        attachment: Attachment,
    ) -> dict[str, Any]:
        """
        Prepare attachment for sandbox import.

        Returns data needed to import the file into sandbox workspace.

        Args:
            attachment: The attachment to prepare

        Returns:
            Dict with filename, content_base64, mime_type, and md5 hash

        Raises:
            ValueError: If attachment not ready or not intended for sandbox
        """
        if not attachment.needs_sandbox_import():
            raise ValueError("Attachment is not intended for sandbox import")

        if not attachment.can_be_used():
            raise ValueError(f"Attachment is not ready: {attachment.status.value}")

        # Get file content
        content = await self._storage.get_file(attachment.object_key)
        if not content:
            raise ValueError("File not found in storage")

        # Calculate MD5 for integrity verification
        import hashlib

        content_md5 = hashlib.md5(content).hexdigest()

        # Log source file info
        logger.info(
            f"[AttachmentService] prepare_for_sandbox: "
            f"filename={attachment.filename}, size={len(content)}, "
            f"md5={content_md5}, header={content[:16].hex() if len(content) >= 16 else content.hex()}"
        )

        return {
            "filename": attachment.filename,
            "content_base64": base64.b64encode(content).decode("utf-8"),
            "mime_type": attachment.mime_type,
            "size_bytes": len(content),  # Use actual content size, not db record
            "source_md5": content_md5,  # For end-to-end integrity verification
        }

    async def prepare_for_sandbox_batch(
        self,
        attachments: list[Attachment],
    ) -> list[dict[str, Any]]:
        """
        Prepare multiple attachments for sandbox import.

        Args:
            attachments: List of attachments to prepare

        Returns:
            List of import data dicts
        """
        results = []
        for attachment in attachments:
            if attachment.needs_sandbox_import() and attachment.can_be_used():
                try:
                    data = await self.prepare_for_sandbox(attachment)
                    data["attachment_id"] = attachment.id
                    results.append(data)
                except Exception as e:
                    logger.warning(f"Failed to prepare attachment {attachment.id} for sandbox: {e}")
        return results

    async def mark_sandbox_imported(
        self,
        attachment_id: str,
        sandbox_path: str,
    ) -> bool:
        """
        Mark an attachment as imported to sandbox.

        Args:
            attachment_id: ID of the attachment
            sandbox_path: Path in sandbox where file was imported

        Returns:
            True if updated successfully
        """
        return await self._repo.update_sandbox_path(attachment_id, sandbox_path)

    # ==================== Cleanup ====================

    async def delete(self, attachment_id: str) -> bool:
        """
        Delete an attachment and its storage content.

        Args:
            attachment_id: ID of the attachment to delete

        Returns:
            True if deleted successfully
        """
        attachment = await self._repo.get(attachment_id)
        if not attachment:
            return False

        # Delete from storage
        try:
            await self._storage.delete_file(attachment.object_key)
        except Exception as e:
            logger.warning(f"Failed to delete attachment file: {e}")

        # Delete record
        await self._repo.delete(attachment_id)
        logger.info(f"Deleted attachment: {attachment_id}")

        return True

    async def cleanup_expired(self) -> int:
        """
        Clean up expired attachments.

        Returns:
            Number of attachments cleaned up
        """
        # Get expired attachments
        expired = await self._repo.get_by_conversation(
            conversation_id="",  # Will need to modify to get all expired
            status=AttachmentStatus.EXPIRED,
        )

        count = 0
        for attachment in expired:
            if await self.delete(attachment.id):
                count += 1

        # Also delete by expiration date
        count += await self._repo.delete_expired()

        if count > 0:
            logger.info(f"Cleaned up {count} expired attachments")

        return count

    # ==================== URL Generation ====================

    async def get_download_url(
        self,
        attachment_id: str,
        expiration_seconds: int = 3600,
    ) -> str | None:
        """
        Get a presigned URL for downloading an attachment.

        Args:
            attachment_id: ID of the attachment
            expiration_seconds: URL validity period

        Returns:
            Presigned URL or None if attachment not found
        """
        attachment = await self._repo.get(attachment_id)
        if not attachment or not attachment.can_be_used():
            return None

        return await self._storage.generate_presigned_url(
            object_key=attachment.object_key,
            expiration_seconds=expiration_seconds,
            content_disposition=f'attachment; filename="{attachment.filename}"',
        )

    # ==================== Utility ====================

    def should_use_multipart(self, size_bytes: int) -> bool:
        """Check if multipart upload should be used for the given size."""
        return size_bytes > MULTIPART_THRESHOLD

    def get_part_size(self) -> int:
        """Get the recommended part size for multipart upload."""
        return DEFAULT_PART_SIZE
