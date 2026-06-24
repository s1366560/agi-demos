"""Unit tests for attachment upload route authorization."""

import logging
from collections.abc import Sequence
from io import BytesIO
from typing import Any

import pytest
from fastapi import HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.attachment import Attachment, AttachmentPurpose, AttachmentStatus
from src.domain.ports.services.storage_service_port import PartUploadResult
from src.infrastructure.adapters.primary.web.routers.attachments_upload import (
    CompleteUploadPart,
    CompleteUploadRequest,
    InitiateUploadRequest,
    _get_authorized_attachment,
    _verify_project_access,
    complete_multipart_upload,
    initiate_multipart_upload,
    list_attachments,
    upload_part,
    upload_simple,
)
from src.infrastructure.adapters.secondary.persistence.models import Project, User


def _make_attachment(
    attachment_id: str,
    project_id: str,
    tenant_id: str,
    conversation_id: str = "conversation-1",
    status: AttachmentStatus = AttachmentStatus.UPLOADED,
    total_parts: int | None = None,
) -> Attachment:
    return Attachment(
        id=attachment_id,
        conversation_id=conversation_id,
        project_id=project_id,
        tenant_id=tenant_id,
        filename=f"{attachment_id}.txt",
        mime_type="text/plain",
        size_bytes=12,
        object_key=f"attachments/{attachment_id}.txt",
        purpose=AttachmentPurpose.BOTH,
        status=status,
        upload_id="upload-1" if status == AttachmentStatus.PENDING else None,
        total_parts=total_parts,
    )


class FakeAttachmentService:
    def __init__(self, attachments: Sequence[Attachment]) -> None:
        self._attachments = {attachment.id: attachment for attachment in attachments}
        self.initiate_calls: list[dict[str, Any]] = []
        self.simple_upload_calls: list[dict[str, Any]] = []
        self.upload_part_calls: list[tuple[str, int, bytes]] = []
        self.complete_calls: list[tuple[str, list[PartUploadResult]]] = []

    async def get(self, attachment_id: str) -> Attachment | None:
        return self._attachments.get(attachment_id)

    async def get_by_conversation(
        self,
        conversation_id: str,
        status: AttachmentStatus | None = None,
    ) -> list[Attachment]:
        attachments = [
            attachment
            for attachment in self._attachments.values()
            if attachment.conversation_id == conversation_id
        ]
        if status:
            attachments = [
                attachment for attachment in attachments if attachment.status == status
            ]
        return attachments

    async def initiate_multipart_upload(self, **kwargs: Any) -> Attachment:
        self.initiate_calls.append(kwargs)
        attachment = _make_attachment(
            "attachment-initiated",
            project_id=str(kwargs["project_id"]),
            tenant_id=str(kwargs["tenant_id"]),
            conversation_id=str(kwargs["conversation_id"]),
            status=AttachmentStatus.PENDING,
            total_parts=1,
        )
        self._attachments[attachment.id] = attachment
        return attachment

    async def upload_simple(self, **kwargs: Any) -> Attachment:
        self.simple_upload_calls.append(kwargs)
        attachment = _make_attachment(
            "attachment-simple",
            project_id=str(kwargs["project_id"]),
            tenant_id=str(kwargs["tenant_id"]),
            conversation_id=str(kwargs["conversation_id"]),
        )
        self._attachments[attachment.id] = attachment
        return attachment

    async def upload_part(
        self,
        attachment_id: str,
        part_number: int,
        data: bytes,
    ) -> PartUploadResult:
        self.upload_part_calls.append((attachment_id, part_number, data))
        return PartUploadResult(part_number=part_number, etag=f"etag-{part_number}")

    async def complete_multipart_upload(
        self,
        attachment_id: str,
        parts: list[PartUploadResult],
    ) -> Attachment:
        self.complete_calls.append((attachment_id, parts))
        attachment = self._attachments[attachment_id]
        attachment.mark_uploaded()
        return attachment


class FailingAttachmentService(FakeAttachmentService):
    def __init__(self) -> None:
        super().__init__([])

    async def initiate_multipart_upload(self, **_kwargs: object) -> Attachment:
        raise ValueError("internal multipart validation secret")

    async def upload_simple(self, **_kwargs: object) -> Attachment:
        raise ValueError("internal simple upload secret")


class UnexpectedFailingAttachmentService(FakeAttachmentService):
    def __init__(self) -> None:
        super().__init__([])

    async def initiate_multipart_upload(self, **_kwargs: object) -> Attachment:
        raise RuntimeError("internal multipart runtime secret")


@pytest.mark.unit
class TestAttachmentRouteAuthorization:
    @pytest.mark.asyncio
    async def test_project_access_allows_project_member(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        tenant_id = await _verify_project_access(test_project_db.id, test_user, test_db)

        assert tenant_id == test_project_db.tenant_id

    @pytest.mark.asyncio
    async def test_project_access_rejects_non_member(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        another_user: User,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await _verify_project_access(test_project_db.id, another_user, test_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_authorized_attachment_rejects_cross_tenant_access(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        attachment = _make_attachment(
            "attachment-other-tenant",
            project_id=test_project_db.id,
            tenant_id="other-tenant",
        )
        service = FakeAttachmentService([attachment])

        with pytest.raises(HTTPException) as exc_info:
            await _get_authorized_attachment(
                attachment.id,
                test_user,
                test_db,
                service,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_authorized_attachment_rejects_project_non_member(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        another_user: User,
    ) -> None:
        attachment = _make_attachment(
            "attachment-other-project-user",
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
        )
        service = FakeAttachmentService([attachment])

        with pytest.raises(HTTPException) as exc_info:
            await _get_authorized_attachment(
                attachment.id,
                another_user,
                test_db,
                service,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_list_attachments_filters_to_authorized_project_and_tenant(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        authorized = _make_attachment(
            "attachment-visible",
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
        )
        cross_tenant = _make_attachment(
            "attachment-hidden-tenant",
            project_id=test_project_db.id,
            tenant_id="other-tenant",
        )
        cross_project = _make_attachment(
            "attachment-hidden-project",
            project_id="project-without-membership",
            tenant_id=test_project_db.tenant_id,
        )
        service = FakeAttachmentService([authorized, cross_tenant, cross_project])

        response = await list_attachments(
            conversation_id="conversation-1",
            status=None,
            current_user=test_user,
            db=test_db,
            attachment_service=service,
        )

        assert response.total == 1
        assert [attachment.id for attachment in response.attachments] == [authorized.id]

    @pytest.mark.asyncio
    async def test_list_attachments_uses_bulk_project_access_lookup(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test list filtering does not call the per-attachment access verifier."""
        first = _make_attachment(
            "attachment-visible-1",
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
        )
        second = _make_attachment(
            "attachment-visible-2",
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
        )
        cross_project = _make_attachment(
            "attachment-hidden-project-bulk",
            project_id="project-without-membership",
            tenant_id=test_project_db.tenant_id,
        )

        async def fail_per_attachment_verify(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("list_attachments should use a bulk project access lookup")

        monkeypatch.setattr(
            "src.infrastructure.adapters.primary.web.routers.attachments_upload._verify_project_access",
            fail_per_attachment_verify,
        )
        service = FakeAttachmentService([first, second, cross_project])

        response = await list_attachments(
            conversation_id="conversation-1",
            status=None,
            current_user=test_user,
            db=test_db,
            attachment_service=service,
        )

        assert response.total == 2
        assert [attachment.id for attachment in response.attachments] == [first.id, second.id]

    @pytest.mark.asyncio
    async def test_initiate_upload_uses_authorized_project_tenant(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        service = FakeAttachmentService([])

        response = await initiate_multipart_upload(
            request=InitiateUploadRequest(
                conversation_id="conversation-1",
                project_id=test_project_db.id,
                filename="example.txt",
                mime_type="text/plain",
                size_bytes=12,
            ),
            current_user=test_user,
            db=test_db,
            attachment_service=service,
        )

        assert response.attachment_id == "attachment-initiated"
        assert service.initiate_calls[0]["tenant_id"] == test_project_db.tenant_id
        assert service.initiate_calls[0]["project_id"] == test_project_db.id

    @pytest.mark.asyncio
    async def test_simple_upload_uses_authorized_project_tenant(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        service = FakeAttachmentService([])

        response = await upload_simple(
            conversation_id="conversation-1",
            project_id=test_project_db.id,
            purpose="both",
            file=UploadFile(BytesIO(b"file-data"), filename="example.txt"),
            current_user=test_user,
            db=test_db,
            attachment_service=service,
        )

        assert response.id == "attachment-simple"
        assert service.simple_upload_calls[0]["tenant_id"] == test_project_db.tenant_id
        assert service.simple_upload_calls[0]["project_id"] == test_project_db.id

    @pytest.mark.asyncio
    async def test_upload_part_rejects_part_number_beyond_expected_total(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        attachment = _make_attachment(
            "attachment-pending",
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
            status=AttachmentStatus.PENDING,
            total_parts=2,
        )
        service = FakeAttachmentService([attachment])

        with pytest.raises(HTTPException) as exc_info:
            await upload_part(
                attachment_id=attachment.id,
                part_number=3,
                file=UploadFile(BytesIO(b"part-data"), filename="part.bin"),
                current_user=test_user,
                db=test_db,
                attachment_service=service,
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "Part number exceeds total parts"
        assert service.upload_part_calls == []

    @pytest.mark.asyncio
    async def test_upload_part_rejects_empty_payload(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        attachment = _make_attachment(
            "attachment-empty-part",
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
            status=AttachmentStatus.PENDING,
            total_parts=1,
        )
        service = FakeAttachmentService([attachment])

        with pytest.raises(HTTPException) as exc_info:
            await upload_part(
                attachment_id=attachment.id,
                part_number=1,
                file=UploadFile(BytesIO(b""), filename="part.bin"),
                current_user=test_user,
                db=test_db,
                attachment_service=service,
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "Uploaded part cannot be empty"
        assert service.upload_part_calls == []

    def test_complete_upload_request_rejects_duplicate_parts(self) -> None:
        with pytest.raises(ValidationError):
            CompleteUploadRequest(
                attachment_id="attachment-1",
                parts=[
                    CompleteUploadPart(part_number=1, etag="etag-1"),
                    CompleteUploadPart(part_number=1, etag="etag-1-again"),
                ],
            )

    @pytest.mark.asyncio
    async def test_complete_upload_rejects_missing_parts(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        attachment = _make_attachment(
            "attachment-missing-part",
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
            status=AttachmentStatus.PENDING,
            total_parts=2,
        )
        service = FakeAttachmentService([attachment])

        with pytest.raises(HTTPException) as exc_info:
            await complete_multipart_upload(
                request=CompleteUploadRequest(
                    attachment_id=attachment.id,
                    parts=[CompleteUploadPart(part_number=1, etag="etag-1")],
                ),
                current_user=test_user,
                db=test_db,
                attachment_service=service,
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "Uploaded parts do not match expected part count"
        assert service.complete_calls == []

    @pytest.mark.asyncio
    async def test_complete_upload_sorts_parts_before_storage_completion(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        attachment = _make_attachment(
            "attachment-complete",
            project_id=test_project_db.id,
            tenant_id=test_project_db.tenant_id,
            status=AttachmentStatus.PENDING,
            total_parts=2,
        )
        service = FakeAttachmentService([attachment])

        response = await complete_multipart_upload(
            request=CompleteUploadRequest(
                attachment_id=attachment.id,
                parts=[
                    CompleteUploadPart(part_number=2, etag="etag-2"),
                    CompleteUploadPart(part_number=1, etag="etag-1"),
                ],
            ),
            current_user=test_user,
            db=test_db,
            attachment_service=service,
        )

        assert response.id == attachment.id
        assert response.status == AttachmentStatus.UPLOADED.value
        assert len(service.complete_calls) == 1
        assert [part.part_number for part in service.complete_calls[0][1]] == [1, 2]

    @pytest.mark.asyncio
    async def test_initiate_upload_sanitizes_service_value_errors(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await initiate_multipart_upload(
                request=InitiateUploadRequest(
                    conversation_id="conversation-1",
                    project_id=test_project_db.id,
                    filename="example.txt",
                    mime_type="text/plain",
                    size_bytes=12,
                ),
                current_user=test_user,
                db=test_db,
                attachment_service=FailingAttachmentService(),
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "Invalid upload request"
        assert "internal" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_initiate_upload_error_log_omits_service_exception_text(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(
            logging.ERROR,
            logger="src.infrastructure.adapters.primary.web.routers.attachments_upload",
        )

        with pytest.raises(HTTPException) as exc_info:
            await initiate_multipart_upload(
                request=InitiateUploadRequest(
                    conversation_id="conversation-1",
                    project_id=test_project_db.id,
                    filename="example.txt",
                    mime_type="text/plain",
                    size_bytes=12,
                ),
                current_user=test_user,
                db=test_db,
                attachment_service=UnexpectedFailingAttachmentService(),
            )

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc_info.value.detail == "Failed to initiate upload"
        assert "Failed to initiate multipart upload" in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "internal multipart runtime secret" not in caplog.text

    @pytest.mark.asyncio
    async def test_simple_upload_sanitizes_service_value_errors(
        self,
        test_db: AsyncSession,
        test_project_db: Project,
        test_user: User,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await upload_simple(
                conversation_id="conversation-1",
                project_id=test_project_db.id,
                purpose="both",
                file=UploadFile(BytesIO(b"file-data"), filename="example.txt"),
                current_user=test_user,
                db=test_db,
                attachment_service=FailingAttachmentService(),
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "Invalid upload request"
        assert "internal" not in exc_info.value.detail
