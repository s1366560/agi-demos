"""Unit tests for generation-owned attachment upload routes."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from io import BytesIO
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.attachment_service import AttachmentService
from src.domain.model.agent.attachment import Attachment, AttachmentPurpose, AttachmentStatus
from src.domain.ports.services.storage_service_port import PartUploadResult
from src.infrastructure.adapters.primary.web.attachment_application_authority_v2 import (
    AttachmentApplicationAuthorityV2,
)
from src.infrastructure.adapters.primary.web.routers.attachments_upload import (
    CompleteUploadPart,
    CompleteUploadRequest,
    InitiateUploadRequest,
    abort_multipart_upload,
    complete_multipart_upload,
    delete_attachment,
    download_attachment,
    get_attachment,
    initiate_multipart_upload,
    list_attachments,
    upload_part,
    upload_simple,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.attachment_services import (
    AttachmentApplicationServicesV2,
    AttachmentApplicationServiceV2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2

pytestmark = pytest.mark.unit


def _make_attachment(
    attachment_id: str,
    project_id: str = "project-1",
    tenant_id: str = "tenant-1",
    conversation_id: str = "conversation-1",
    status_value: AttachmentStatus = AttachmentStatus.UPLOADED,
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
        status=status_value,
        upload_id="upload-1" if status_value is AttachmentStatus.PENDING else None,
        total_parts=total_parts,
    )


class FakeAttachmentService:
    def __init__(self, attachments: Sequence[Attachment]) -> None:
        self._attachments = {attachment.id: attachment for attachment in attachments}
        self.initiate_calls: list[dict[str, Any]] = []
        self.simple_upload_calls: list[dict[str, Any]] = []
        self.upload_part_calls: list[tuple[str, int, bytes]] = []
        self.complete_calls: list[tuple[str, list[PartUploadResult]]] = []
        self.abort_calls: list[str] = []
        self.delete_calls: list[str] = []
        self.download_urls: dict[str, str | None] = {}

    async def get(self, attachment_id: str) -> Attachment | None:
        return self._attachments.get(attachment_id)

    async def get_by_conversation(
        self,
        conversation_id: str,
        status: AttachmentStatus | None = None,
    ) -> list[Attachment]:
        return [
            attachment
            for attachment in self._attachments.values()
            if attachment.conversation_id == conversation_id
            and (status is None or attachment.status is status)
        ]

    async def initiate_multipart_upload(self, **kwargs: Any) -> Attachment:
        self.initiate_calls.append(kwargs)
        attachment = _make_attachment(
            "attachment-initiated",
            project_id=str(kwargs["project_id"]),
            tenant_id=str(kwargs["tenant_id"]),
            conversation_id=str(kwargs["conversation_id"]),
            status_value=AttachmentStatus.PENDING,
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

    async def abort_multipart_upload(self, attachment_id: str) -> bool:
        self.abort_calls.append(attachment_id)
        return attachment_id in self._attachments

    async def get_download_url(self, attachment_id: str) -> str | None:
        return self.download_urls.get(attachment_id)

    async def delete(self, attachment_id: str) -> bool:
        self.delete_calls.append(attachment_id)
        return self._attachments.pop(attachment_id, None) is not None


class _FakeAccess:
    def __init__(self, project_tenants: dict[str, str]) -> None:
        self.project_tenants = project_tenants

    async def accessible_project_tenants(
        self,
        *,
        project_ids: frozenset[str],
        user_id: str,
        is_superuser: bool,
    ) -> dict[str, str]:
        del user_id, is_superuser
        return {
            project_id: tenant_id
            for project_id, tenant_id in self.project_tenants.items()
            if project_id in project_ids
        }


class _UnreadUpload:
    filename = "unread.bin"
    content_type = "application/octet-stream"

    async def read(self) -> bytes:
        raise AssertionError("authorization must complete before reading upload bytes")


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


class FalseResultAttachmentService(FakeAttachmentService):
    async def abort_multipart_upload(self, attachment_id: str) -> bool:
        self.abort_calls.append(attachment_id)
        return False

    async def delete(self, attachment_id: str) -> bool:
        self.delete_calls.append(attachment_id)
        return False


def _authority(
    service: FakeAttachmentService,
    *,
    project_tenants: dict[str, str] | None = None,
) -> AttachmentApplicationAuthorityV2:
    accessible_projects = {"project-1": "tenant-1"} if project_tenants is None else project_tenants
    application = AttachmentApplicationServiceV2(
        service=cast(AttachmentService, service),
        access=_FakeAccess(accessible_projects),
        user_id="user-1",
        is_superuser=False,
    )
    return AttachmentApplicationAuthorityV2(
        operation=cast(OperationContextV2, SimpleNamespace()),
        db=cast(AsyncSession, SimpleNamespace()),
        current_user=cast(User, SimpleNamespace(id="user-1", is_superuser=False)),
        services=AttachmentApplicationServicesV2(attachments=application),
    )


async def test_initiate_upload_uses_authorized_project_tenant() -> None:
    service = FakeAttachmentService([])

    response = await initiate_multipart_upload(
        request=InitiateUploadRequest(
            conversation_id="conversation-1",
            project_id="project-1",
            filename="example.txt",
            mime_type="text/plain",
            size_bytes=12,
        ),
        attachment_application=_authority(service),
    )

    assert response.attachment_id == "attachment-initiated"
    assert service.initiate_calls[0]["tenant_id"] == "tenant-1"
    assert service.initiate_calls[0]["project_id"] == "project-1"


async def test_initiate_upload_maps_project_denial_without_service_call() -> None:
    service = FakeAttachmentService([])

    with pytest.raises(HTTPException) as error:
        await initiate_multipart_upload(
            request=InitiateUploadRequest(
                conversation_id="conversation-1",
                project_id="project-denied",
                filename="example.txt",
                mime_type="text/plain",
                size_bytes=12,
            ),
            attachment_application=_authority(service, project_tenants={}),
        )

    assert error.value.status_code == status.HTTP_403_FORBIDDEN
    assert error.value.detail == "Access denied to project"
    assert service.initiate_calls == []


async def test_simple_upload_uses_authorized_tenant_and_preserves_file_metadata() -> None:
    service = FakeAttachmentService([])

    response = await upload_simple(
        conversation_id="conversation-1",
        project_id="project-1",
        purpose="both",
        file=UploadFile(
            BytesIO(b"file-data"),
            filename="example.txt",
            headers={"content-type": "text/plain"},
        ),
        attachment_application=_authority(service),
    )

    assert response.id == "attachment-simple"
    assert service.simple_upload_calls[0]["tenant_id"] == "tenant-1"
    assert service.simple_upload_calls[0]["filename"] == "example.txt"
    assert service.simple_upload_calls[0]["mime_type"] == "text/plain"


async def test_invalid_purpose_is_400_without_upload() -> None:
    service = FakeAttachmentService([])

    with pytest.raises(HTTPException) as error:
        await upload_simple(
            conversation_id="conversation-1",
            project_id="project-1",
            purpose="invalid",
            file=UploadFile(BytesIO(b"file-data"), filename="example.txt"),
            attachment_application=_authority(service),
        )

    assert error.value.status_code == status.HTTP_400_BAD_REQUEST
    assert error.value.detail == "Invalid attachment purpose"
    assert service.simple_upload_calls == []


@pytest.mark.parametrize("operation", ["part", "simple"])
async def test_authorization_failure_does_not_read_upload_body(operation: str) -> None:
    service = FakeAttachmentService(
        [
            _make_attachment(
                "attachment-denied",
                project_id="project-denied",
                tenant_id="tenant-denied",
                status_value=AttachmentStatus.PENDING,
                total_parts=1,
            )
        ]
    )
    authority = _authority(service, project_tenants={})
    unread = cast(UploadFile, _UnreadUpload())

    with pytest.raises(HTTPException) as error:
        if operation == "part":
            await upload_part(
                attachment_id="attachment-denied",
                part_number=1,
                file=unread,
                attachment_application=authority,
            )
        else:
            await upload_simple(
                conversation_id="conversation-1",
                project_id="project-denied",
                purpose="both",
                file=unread,
                attachment_application=authority,
            )

    assert error.value.status_code == status.HTTP_403_FORBIDDEN
    assert service.upload_part_calls == []
    assert service.simple_upload_calls == []


@pytest.mark.parametrize(
    ("part_number", "payload", "detail"),
    (
        (3, b"part-data", "Part number exceeds total parts"),
        (1, b"", "Uploaded part cannot be empty"),
    ),
)
async def test_upload_part_validates_part_shape_before_storage(
    part_number: int,
    payload: bytes,
    detail: str,
) -> None:
    attachment = _make_attachment(
        "attachment-pending",
        status_value=AttachmentStatus.PENDING,
        total_parts=2,
    )
    service = FakeAttachmentService([attachment])

    with pytest.raises(HTTPException) as error:
        await upload_part(
            attachment_id=attachment.id,
            part_number=part_number,
            file=UploadFile(BytesIO(payload), filename="part.bin"),
            attachment_application=_authority(service),
        )

    assert error.value.status_code == status.HTTP_400_BAD_REQUEST
    assert error.value.detail == detail
    assert service.upload_part_calls == []


async def test_upload_part_preserves_success_wire() -> None:
    attachment = _make_attachment(
        "attachment-pending",
        status_value=AttachmentStatus.PENDING,
        total_parts=2,
    )
    service = FakeAttachmentService([attachment])

    response = await upload_part(
        attachment_id=attachment.id,
        part_number=1,
        file=UploadFile(BytesIO(b"part-data"), filename="part.bin"),
        attachment_application=_authority(service),
    )

    assert response.model_dump() == {"part_number": 1, "etag": "etag-1"}
    assert service.upload_part_calls == [(attachment.id, 1, b"part-data")]


def test_complete_upload_request_rejects_duplicate_parts() -> None:
    with pytest.raises(ValidationError):
        CompleteUploadRequest(
            attachment_id="attachment-1",
            parts=[
                CompleteUploadPart(part_number=1, etag="etag-1"),
                CompleteUploadPart(part_number=1, etag="etag-1-again"),
            ],
        )


async def test_complete_upload_rejects_missing_parts() -> None:
    attachment = _make_attachment(
        "attachment-missing-part",
        status_value=AttachmentStatus.PENDING,
        total_parts=2,
    )
    service = FakeAttachmentService([attachment])

    with pytest.raises(HTTPException) as error:
        await complete_multipart_upload(
            request=CompleteUploadRequest(
                attachment_id=attachment.id,
                parts=[CompleteUploadPart(part_number=1, etag="etag-1")],
            ),
            attachment_application=_authority(service),
        )

    assert error.value.status_code == status.HTTP_400_BAD_REQUEST
    assert error.value.detail == "Uploaded parts do not match expected part count"
    assert service.complete_calls == []


async def test_complete_upload_sorts_parts_before_storage_completion() -> None:
    attachment = _make_attachment(
        "attachment-complete",
        status_value=AttachmentStatus.PENDING,
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
        attachment_application=_authority(service),
    )

    assert response.id == attachment.id
    assert response.status == AttachmentStatus.UPLOADED.value
    assert [part.part_number for part in service.complete_calls[0][1]] == [1, 2]


async def test_list_filters_inaccessible_projects_and_tenants() -> None:
    visible = _make_attachment("visible")
    wrong_tenant = _make_attachment("wrong-tenant", tenant_id="tenant-other")
    hidden_project = _make_attachment(
        "hidden-project",
        project_id="project-hidden",
        tenant_id="tenant-hidden",
    )
    service = FakeAttachmentService([visible, wrong_tenant, hidden_project])

    response = await list_attachments(
        conversation_id="conversation-1",
        status=None,
        attachment_application=_authority(service),
    )

    assert response.total == 1
    assert [attachment.id for attachment in response.attachments] == ["visible"]


async def test_list_invalid_status_is_400() -> None:
    with pytest.raises(HTTPException) as error:
        await list_attachments(
            conversation_id="conversation-1",
            status="invalid",
            attachment_application=_authority(FakeAttachmentService([])),
        )

    assert error.value.status_code == status.HTTP_400_BAD_REQUEST
    assert error.value.detail == "Invalid attachment status"


async def test_get_missing_attachment_is_404() -> None:
    with pytest.raises(HTTPException) as error:
        await get_attachment(
            attachment_id="missing",
            attachment_application=_authority(FakeAttachmentService([])),
        )

    assert error.value.status_code == status.HTTP_404_NOT_FOUND
    assert error.value.detail == "Attachment not found"


async def test_get_attachment_preserves_public_response_shape() -> None:
    attachment = _make_attachment("visible")

    response = await get_attachment(
        attachment_id=attachment.id,
        attachment_application=_authority(FakeAttachmentService([attachment])),
    )

    payload = response.model_dump()
    assert payload["id"] == attachment.id
    assert payload["project_id"] == attachment.project_id
    assert {"tenant_id", "object_key", "upload_id"}.isdisjoint(payload)


@pytest.mark.parametrize("operation", ["get", "part"])
async def test_project_nonmember_maps_to_project_denial(operation: str) -> None:
    attachment = _make_attachment(
        "attachment-denied",
        status_value=AttachmentStatus.PENDING,
        total_parts=1,
    )
    authority = _authority(FakeAttachmentService([attachment]), project_tenants={})

    with pytest.raises(HTTPException) as error:
        if operation == "get":
            await get_attachment(
                attachment_id=attachment.id,
                attachment_application=authority,
            )
        else:
            await upload_part(
                attachment_id=attachment.id,
                part_number=1,
                file=cast(UploadFile, _UnreadUpload()),
                attachment_application=authority,
            )

    assert error.value.status_code == status.HTTP_403_FORBIDDEN
    assert error.value.detail == "Access denied to project"


async def test_cross_tenant_attachment_maps_to_attachment_denial() -> None:
    attachment = _make_attachment("wrong-tenant", tenant_id="tenant-other")

    with pytest.raises(HTTPException) as error:
        await get_attachment(
            attachment_id=attachment.id,
            attachment_application=_authority(FakeAttachmentService([attachment])),
        )

    assert error.value.status_code == status.HTTP_403_FORBIDDEN
    assert error.value.detail == "Access denied to attachment"


async def test_abort_and_delete_preserve_success_payloads() -> None:
    abort_target = _make_attachment(
        "abort-target",
        status_value=AttachmentStatus.PENDING,
        total_parts=1,
    )
    delete_target = _make_attachment("delete-target")
    service = FakeAttachmentService([abort_target, delete_target])
    authority = _authority(service)

    aborted = await abort_multipart_upload(
        attachment_id=abort_target.id,
        attachment_application=authority,
    )
    deleted = await delete_attachment(
        attachment_id=delete_target.id,
        attachment_application=authority,
    )

    assert aborted == {"success": True, "message": "Upload aborted"}
    assert deleted == {"success": True, "message": "Attachment deleted"}
    assert service.abort_calls == [abort_target.id]
    assert service.delete_calls == [delete_target.id]


@pytest.mark.parametrize("operation", ["abort", "delete"])
async def test_abort_and_delete_false_results_are_404(operation: str) -> None:
    attachment = _make_attachment(
        "stale-target",
        status_value=AttachmentStatus.PENDING,
        total_parts=1,
    )
    service = FalseResultAttachmentService([attachment])
    authority = _authority(service)

    with pytest.raises(HTTPException) as error:
        if operation == "abort":
            await abort_multipart_upload(
                attachment_id=attachment.id,
                attachment_application=authority,
            )
        else:
            await delete_attachment(
                attachment_id=attachment.id,
                attachment_application=authority,
            )

    assert error.value.status_code == status.HTTP_404_NOT_FOUND
    assert error.value.detail == "Attachment not found"


async def test_download_redirect_and_not_ready_wire() -> None:
    ready = _make_attachment("ready")
    not_ready = _make_attachment("not-ready")
    service = FakeAttachmentService([ready, not_ready])
    service.download_urls[ready.id] = "https://storage.invalid/download"
    service.download_urls[not_ready.id] = None
    authority = _authority(service)

    response = await download_attachment(
        attachment_id=ready.id,
        attachment_application=authority,
    )

    assert response.status_code == status.HTTP_302_FOUND
    assert response.headers["location"] == "https://storage.invalid/download"
    with pytest.raises(HTTPException) as error:
        await download_attachment(
            attachment_id=not_ready.id,
            attachment_application=authority,
        )
    assert error.value.status_code == status.HTTP_404_NOT_FOUND
    assert error.value.detail == "Attachment not found or not ready"


async def test_initiate_upload_sanitizes_service_value_errors() -> None:
    with pytest.raises(HTTPException) as error:
        await initiate_multipart_upload(
            request=InitiateUploadRequest(
                conversation_id="conversation-1",
                project_id="project-1",
                filename="example.txt",
                mime_type="text/plain",
                size_bytes=12,
            ),
            attachment_application=_authority(FailingAttachmentService()),
        )

    assert error.value.status_code == status.HTTP_400_BAD_REQUEST
    assert error.value.detail == "Invalid upload request"
    assert "internal" not in error.value.detail


async def test_initiate_upload_error_log_omits_service_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.ERROR,
        logger="src.infrastructure.adapters.primary.web.routers.attachments_upload",
    )

    with pytest.raises(HTTPException) as error:
        await initiate_multipart_upload(
            request=InitiateUploadRequest(
                conversation_id="conversation-1",
                project_id="project-1",
                filename="example.txt",
                mime_type="text/plain",
                size_bytes=12,
            ),
            attachment_application=_authority(UnexpectedFailingAttachmentService()),
        )

    assert error.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert error.value.detail == "Failed to initiate upload"
    assert "Failed to initiate multipart upload" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "internal multipart runtime secret" not in caplog.text


async def test_simple_upload_sanitizes_service_value_errors() -> None:
    with pytest.raises(HTTPException) as error:
        await upload_simple(
            conversation_id="conversation-1",
            project_id="project-1",
            purpose="both",
            file=UploadFile(BytesIO(b"file-data"), filename="example.txt"),
            attachment_application=_authority(FailingAttachmentService()),
        )

    assert error.value.status_code == status.HTTP_400_BAD_REQUEST
    assert error.value.detail == "Invalid upload request"
    assert "internal" not in error.value.detail
