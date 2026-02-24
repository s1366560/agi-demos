"""
Tests for V2 SqlAttachmentRepository using BaseRepository.

TDD Approach: RED -> GREEN -> REFACTOR

These tests verify that the migrated repository maintains 100% compatibility
with the original implementation while leveraging the BaseRepository.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.attachment import (
    Attachment,
    AttachmentMetadata,
    AttachmentPurpose,
    AttachmentStatus,
)
from src.infrastructure.adapters.secondary.persistence.sql_attachment_repository import (
    SqlAttachmentRepository,
)


@pytest.fixture
async def v2_attachment_repo(v2_db_session: AsyncSession) -> SqlAttachmentRepository:
    """Create a V2 attachment repository for testing."""
    return SqlAttachmentRepository(v2_db_session)


class TestSqlAttachmentRepositoryCreate:
    """Tests for creating new attachments."""

    @pytest.mark.asyncio
    async def test_save_new_attachment(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test saving a new attachment."""
        attachment = Attachment(
            id="att-test-1",
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            filename="test.txt",
            mime_type="text/plain",
            size_bytes=100,
            object_key="key/test.txt",
            purpose=AttachmentPurpose.LLM_CONTEXT,
            status=AttachmentStatus.PENDING,
            upload_id=None,
            total_parts=1,
            uploaded_parts=0,
            sandbox_path=None,
            metadata=AttachmentMetadata.from_dict(None),
            created_at=datetime.now(UTC),
            expires_at=None,
            error_message=None,
        )

        await v2_attachment_repo.save(attachment)

        # Verify attachment was saved
        retrieved = await v2_attachment_repo.get("att-test-1")
        assert retrieved is not None
        assert retrieved.id == "att-test-1"
        assert retrieved.conversation_id == "conv-1"
        assert retrieved.project_id == "proj-1"
        assert retrieved.tenant_id == "tenant-1"
        assert retrieved.filename == "test.txt"
        assert retrieved.mime_type == "text/plain"
        assert retrieved.size_bytes == 100
        assert retrieved.object_key == "key/test.txt"
        assert retrieved.purpose == AttachmentPurpose.LLM_CONTEXT
        assert retrieved.status == AttachmentStatus.PENDING

    @pytest.mark.asyncio
    async def test_save_with_expiration(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test saving an attachment with expiration."""
        expires_at = datetime.now(UTC) + timedelta(hours=24)
        attachment = Attachment(
            id="att-expire-1",
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            filename="expire.txt",
            mime_type="text/plain",
            size_bytes=50,
            object_key="key/expire.txt",
            purpose=AttachmentPurpose.LLM_CONTEXT,
            status=AttachmentStatus.PENDING,
            upload_id=None,
            total_parts=1,
            uploaded_parts=0,
            sandbox_path=None,
            metadata=AttachmentMetadata.from_dict(None),
            created_at=datetime.now(UTC),
            expires_at=expires_at,
            error_message=None,
        )

        await v2_attachment_repo.save(attachment)

        retrieved = await v2_attachment_repo.get("att-expire-1")
        assert retrieved is not None
        assert retrieved.expires_at is not None


class TestSqlAttachmentRepositoryUpdate:
    """Tests for updating existing attachments."""

    @pytest.mark.asyncio
    async def test_update_existing_attachment(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test updating an existing attachment."""
        # Create initial attachment
        attachment = Attachment(
            id="att-update-1",
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            filename="original.txt",
            mime_type="text/plain",
            size_bytes=100,
            object_key="key/original.txt",
            purpose=AttachmentPurpose.LLM_CONTEXT,
            status=AttachmentStatus.PENDING,
            upload_id=None,
            total_parts=1,
            uploaded_parts=0,
            sandbox_path=None,
            metadata=AttachmentMetadata.from_dict(None),
            created_at=datetime.now(UTC),
            expires_at=None,
            error_message=None,
        )
        await v2_attachment_repo.save(attachment)

        # Update the attachment
        updated_attachment = Attachment(
            id="att-update-1",
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            filename="updated.txt",
            mime_type="text/plain",
            size_bytes=200,
            object_key="key/updated.txt",
            purpose=AttachmentPurpose.LLM_CONTEXT,
            status=AttachmentStatus.READY,
            upload_id=None,
            total_parts=1,
            uploaded_parts=1,
            sandbox_path="/sandbox/updated.txt",
            metadata=AttachmentMetadata.from_dict(None),
            created_at=attachment.created_at,
            expires_at=None,
            error_message=None,
        )
        await v2_attachment_repo.save(updated_attachment)

        # Verify updates
        retrieved = await v2_attachment_repo.get("att-update-1")
        assert retrieved.filename == "updated.txt"
        assert retrieved.size_bytes == 200
        assert retrieved.status == AttachmentStatus.READY
        assert retrieved.uploaded_parts == 1
        assert retrieved.sandbox_path == "/sandbox/updated.txt"


class TestSqlAttachmentRepositoryFind:
    """Tests for finding attachments."""

    @pytest.mark.asyncio
    async def test_get_existing(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test finding an existing attachment by ID."""
        attachment = Attachment(
            id="att-get-1",
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            filename="get.txt",
            mime_type="text/plain",
            size_bytes=100,
            object_key="key/get.txt",
            purpose=AttachmentPurpose.LLM_CONTEXT,
            status=AttachmentStatus.PENDING,
            upload_id=None,
            total_parts=1,
            uploaded_parts=0,
            sandbox_path=None,
            metadata=AttachmentMetadata.from_dict(None),
            created_at=datetime.now(UTC),
            expires_at=None,
            error_message=None,
        )
        await v2_attachment_repo.save(attachment)

        retrieved = await v2_attachment_repo.get("att-get-1")
        assert retrieved is not None
        assert retrieved.id == "att-get-1"
        assert retrieved.filename == "get.txt"

    @pytest.mark.asyncio
    async def test_get_not_found(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test finding a non-existent attachment returns None."""
        retrieved = await v2_attachment_repo.get("non-existent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_by_conversation(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test listing attachments for a conversation."""
        # Create attachments for different conversations
        for i in range(3):
            attachment = Attachment(
                id=f"att-conv-1-{i}",
                conversation_id="conv-1",
                project_id="proj-1",
                tenant_id="tenant-1",
                filename=f"file{i}.txt",
                mime_type="text/plain",
                size_bytes=100,
                object_key=f"key/file{i}.txt",
                purpose=AttachmentPurpose.LLM_CONTEXT,
                status=AttachmentStatus.PENDING,
                upload_id=None,
                total_parts=1,
                uploaded_parts=0,
                sandbox_path=None,
                metadata=AttachmentMetadata.from_dict(None),
                created_at=datetime.now(UTC),
                expires_at=None,
                error_message=None,
            )
            await v2_attachment_repo.save(attachment)

        # Add attachment for different conversation
        other_attachment = Attachment(
            id="att-other-conv",
            conversation_id="conv-2",
            project_id="proj-1",
            tenant_id="tenant-1",
            filename="other.txt",
            mime_type="text/plain",
            size_bytes=100,
            object_key="key/other.txt",
            purpose=AttachmentPurpose.LLM_CONTEXT,
            status=AttachmentStatus.PENDING,
            upload_id=None,
            total_parts=1,
            uploaded_parts=0,
            sandbox_path=None,
            metadata=AttachmentMetadata.from_dict(None),
            created_at=datetime.now(UTC),
            expires_at=None,
            error_message=None,
        )
        await v2_attachment_repo.save(other_attachment)

        # List attachments for conv-1
        attachments = await v2_attachment_repo.get_by_conversation("conv-1")
        assert len(attachments) == 3
        assert all(a.conversation_id == "conv-1" for a in attachments)

    @pytest.mark.asyncio
    async def test_get_by_conversation_with_status_filter(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test listing attachments for a conversation with status filter."""
        # Create attachments with different statuses
        for status in [AttachmentStatus.PENDING, AttachmentStatus.READY, AttachmentStatus.FAILED]:
            attachment = Attachment(
                id=f"att-status-{status.value}",
                conversation_id="conv-status",
                project_id="proj-1",
                tenant_id="tenant-1",
                filename=f"{status.value}.txt",
                mime_type="text/plain",
                size_bytes=100,
                object_key=f"key/{status.value}.txt",
                purpose=AttachmentPurpose.LLM_CONTEXT,
                status=status,
                upload_id=None,
                total_parts=1,
                uploaded_parts=0,
                sandbox_path=None,
                metadata=AttachmentMetadata.from_dict(None),
                created_at=datetime.now(UTC),
                expires_at=None,
                error_message=None,
            )
            await v2_attachment_repo.save(attachment)

        # List only pending attachments
        pending = await v2_attachment_repo.get_by_conversation("conv-status", status=AttachmentStatus.PENDING)
        assert len(pending) == 1
        assert pending[0].status == AttachmentStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_by_ids(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test getting multiple attachments by their IDs."""
        # Create attachments
        attachment_ids = [f"att-bulk-{i}" for i in range(3)]
        for att_id in attachment_ids:
            attachment = Attachment(
                id=att_id,
                conversation_id="conv-1",
                project_id="proj-1",
                tenant_id="tenant-1",
                filename=f"{att_id}.txt",
                mime_type="text/plain",
                size_bytes=100,
                object_key=f"key/{att_id}.txt",
                purpose=AttachmentPurpose.LLM_CONTEXT,
                status=AttachmentStatus.PENDING,
                upload_id=None,
                total_parts=1,
                uploaded_parts=0,
                sandbox_path=None,
                metadata=AttachmentMetadata.from_dict(None),
                created_at=datetime.now(UTC),
                expires_at=None,
                error_message=None,
            )
            await v2_attachment_repo.save(attachment)

        # Get by IDs
        attachments = await v2_attachment_repo.get_by_ids(attachment_ids)
        assert len(attachments) == 3
        assert {a.id for a in attachments} == set(attachment_ids)

    @pytest.mark.asyncio
    async def test_get_by_ids_empty_list(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test getting attachments with empty ID list returns empty list."""
        attachments = await v2_attachment_repo.get_by_ids([])
        assert attachments == []


class TestSqlAttachmentRepositoryDelete:
    """Tests for deleting attachments."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test deleting an existing attachment."""
        attachment = Attachment(
            id="att-delete-1",
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            filename="delete.txt",
            mime_type="text/plain",
            size_bytes=100,
            object_key="key/delete.txt",
            purpose=AttachmentPurpose.LLM_CONTEXT,
            status=AttachmentStatus.PENDING,
            upload_id=None,
            total_parts=1,
            uploaded_parts=0,
            sandbox_path=None,
            metadata=AttachmentMetadata.from_dict(None),
            created_at=datetime.now(UTC),
            expires_at=None,
            error_message=None,
        )
        await v2_attachment_repo.save(attachment)

        # Delete
        result = await v2_attachment_repo.delete("att-delete-1")
        assert result is True

        # Verify deleted
        retrieved = await v2_attachment_repo.get("att-delete-1")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test deleting a non-existent attachment returns False."""
        result = await v2_attachment_repo.delete("non-existent")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_expired(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test deleting all expired attachments."""
        now = datetime.now(UTC)
        past = now - timedelta(hours=1)
        future = now + timedelta(hours=1)

        # Create expired attachment
        expired = Attachment(
            id="att-expired",
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            filename="expired.txt",
            mime_type="text/plain",
            size_bytes=100,
            object_key="key/expired.txt",
            purpose=AttachmentPurpose.LLM_CONTEXT,
            status=AttachmentStatus.PENDING,
            upload_id=None,
            total_parts=1,
            uploaded_parts=0,
            sandbox_path=None,
            metadata=AttachmentMetadata.from_dict(None),
            created_at=past,
            expires_at=past,
            error_message=None,
        )
        await v2_attachment_repo.save(expired)

        # Create non-expired attachment
        not_expired = Attachment(
            id="att-not-expired",
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            filename="not_expired.txt",
            mime_type="text/plain",
            size_bytes=100,
            object_key="key/not_expired.txt",
            purpose=AttachmentPurpose.LLM_CONTEXT,
            status=AttachmentStatus.PENDING,
            upload_id=None,
            total_parts=1,
            uploaded_parts=0,
            sandbox_path=None,
            metadata=AttachmentMetadata.from_dict(None),
            created_at=now,
            expires_at=future,
            error_message=None,
        )
        await v2_attachment_repo.save(not_expired)

        # Delete expired
        count = await v2_attachment_repo.delete_expired()
        assert count == 1

        # Verify only expired was deleted
        assert await v2_attachment_repo.get("att-expired") is None
        assert await v2_attachment_repo.get("att-not-expired") is not None


class TestSqlAttachmentRepositoryUpdateMethods:
    """Tests for specific update methods."""

    @pytest.mark.asyncio
    async def test_update_status(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test updating the status of an attachment."""
        attachment = Attachment(
            id="att-update-status-1",
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            filename="status.txt",
            mime_type="text/plain",
            size_bytes=100,
            object_key="key/status.txt",
            purpose=AttachmentPurpose.LLM_CONTEXT,
            status=AttachmentStatus.PENDING,
            upload_id=None,
            total_parts=1,
            uploaded_parts=0,
            sandbox_path=None,
            metadata=AttachmentMetadata.from_dict(None),
            created_at=datetime.now(UTC),
            expires_at=None,
            error_message=None,
        )
        await v2_attachment_repo.save(attachment)

        # Update status
        result = await v2_attachment_repo.update_status(
            "att-update-status-1",
            AttachmentStatus.READY,
            error_message=None,
        )
        assert result is True

        # Verify update
        retrieved = await v2_attachment_repo.get("att-update-status-1")
        assert retrieved.status == AttachmentStatus.READY

    @pytest.mark.asyncio
    async def test_update_status_with_error(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test updating status with error message."""
        attachment = Attachment(
            id="att-update-error-1",
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            filename="error.txt",
            mime_type="text/plain",
            size_bytes=100,
            object_key="key/error.txt",
            purpose=AttachmentPurpose.LLM_CONTEXT,
            status=AttachmentStatus.PROCESSING,
            upload_id=None,
            total_parts=1,
            uploaded_parts=0,
            sandbox_path=None,
            metadata=AttachmentMetadata.from_dict(None),
            created_at=datetime.now(UTC),
            expires_at=None,
            error_message=None,
        )
        await v2_attachment_repo.save(attachment)

        # Update status with error
        result = await v2_attachment_repo.update_status(
            "att-update-error-1",
            AttachmentStatus.FAILED,
            error_message="Upload failed",
        )
        assert result is True

        # Verify update
        retrieved = await v2_attachment_repo.get("att-update-error-1")
        assert retrieved.status == AttachmentStatus.FAILED
        assert retrieved.error_message == "Upload failed"

    @pytest.mark.asyncio
    async def test_update_upload_progress(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test updating the multipart upload progress."""
        attachment = Attachment(
            id="att-progress-1",
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            filename="progress.txt",
            mime_type="text/plain",
            size_bytes=100,
            object_key="key/progress.txt",
            purpose=AttachmentPurpose.LLM_CONTEXT,
            status=AttachmentStatus.PROCESSING,
            upload_id="upload-123",
            total_parts=5,
            uploaded_parts=0,
            sandbox_path=None,
            metadata=AttachmentMetadata.from_dict(None),
            created_at=datetime.now(UTC),
            expires_at=None,
            error_message=None,
        )
        await v2_attachment_repo.save(attachment)

        # Update progress
        result = await v2_attachment_repo.update_upload_progress("att-progress-1", 3)
        assert result is True

        # Verify update
        retrieved = await v2_attachment_repo.get("att-progress-1")
        assert retrieved.uploaded_parts == 3

    @pytest.mark.asyncio
    async def test_update_sandbox_path(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test updating the sandbox path after import."""
        attachment = Attachment(
            id="att-sandbox-1",
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            filename="sandbox.txt",
            mime_type="text/plain",
            size_bytes=100,
            object_key="key/sandbox.txt",
            purpose=AttachmentPurpose.SANDBOX_INPUT,
            status=AttachmentStatus.PROCESSING,
            upload_id=None,
            total_parts=1,
            uploaded_parts=0,
            sandbox_path=None,
            metadata=AttachmentMetadata.from_dict(None),
            created_at=datetime.now(UTC),
            expires_at=None,
            error_message=None,
        )
        await v2_attachment_repo.save(attachment)

        # Update sandbox path
        result = await v2_attachment_repo.update_sandbox_path("att-sandbox-1", "/sandbox/files/sandbox.txt")
        assert result is True

        # Verify update
        retrieved = await v2_attachment_repo.get("att-sandbox-1")
        assert retrieved.sandbox_path == "/sandbox/files/sandbox.txt"
        assert retrieved.status == AttachmentStatus.READY


class TestSqlAttachmentRepositoryToDomain:
    """Tests for _to_domain conversion."""

    def test_to_domain_with_none(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test that _to_domain returns None for None input."""
        result = v2_attachment_repo._to_domain(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_to_domain_converts_all_fields(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test that _to_domain correctly converts all DB fields."""
        # Create metadata with extra field for custom data
        metadata = AttachmentMetadata(extra={"custom": "value"})
        attachment = Attachment(
            id="att-domain-1",
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            filename="domain.txt",
            mime_type="text/plain",
            size_bytes=100,
            object_key="key/domain.txt",
            purpose=AttachmentPurpose.BOTH,
            status=AttachmentStatus.READY,
            upload_id="upload-1",
            total_parts=5,
            uploaded_parts=5,
            sandbox_path="/sandbox/domain.txt",
            metadata=metadata,
            created_at=datetime.now(UTC),
            expires_at=None,
            error_message=None,
        )
        await v2_attachment_repo.save(attachment)

        retrieved = await v2_attachment_repo.get("att-domain-1")
        assert retrieved.id == "att-domain-1"
        assert retrieved.purpose == AttachmentPurpose.BOTH
        assert retrieved.status == AttachmentStatus.READY
        assert retrieved.upload_id == "upload-1"
        assert retrieved.total_parts == 5
        assert retrieved.uploaded_parts == 5
        assert retrieved.sandbox_path == "/sandbox/domain.txt"
        # Metadata is stored in the extra field
        assert retrieved.metadata.extra == {"custom": "value"}


class TestSqlAttachmentRepositoryToDb:
    """Tests for _to_db conversion."""

    def test_to_db_creates_db_model(self, v2_attachment_repo: SqlAttachmentRepository):
        """Test that _to_db creates a valid DB model."""
        attachment = Attachment(
            id="att-todb-1",
            conversation_id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            filename="todb.txt",
            mime_type="text/plain",
            size_bytes=100,
            object_key="key/todb.txt",
            purpose=AttachmentPurpose.LLM_CONTEXT,
            status=AttachmentStatus.PENDING,
            upload_id=None,
            total_parts=1,
            uploaded_parts=0,
            sandbox_path=None,
            metadata=AttachmentMetadata.from_dict(None),
            created_at=datetime.now(UTC),
            expires_at=None,
            error_message=None,
        )

        db_dict = v2_attachment_repo._to_model_dict(attachment)
        assert db_dict["id"] == "att-todb-1"
        assert db_dict["conversation_id"] == "conv-1"
        assert db_dict["filename"] == "todb.txt"
        assert db_dict["purpose"] == AttachmentPurpose.LLM_CONTEXT.value
        assert db_dict["status"] == AttachmentStatus.PENDING.value
