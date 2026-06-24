"""Unit tests for attachment service behavior."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest

from src.application.services.attachment_service import AttachmentService
from src.domain.model.agent.attachment import (
    Attachment,
    AttachmentPurpose,
    AttachmentStatus,
)
from src.domain.ports.services.storage_service_port import (
    MultipartUploadResult,
    PartUploadResult,
    UploadResult,
)


class _Storage:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    async def upload_file(
        self,
        file_content: bytes,
        object_key: str,
        content_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> UploadResult:
        self._files[object_key] = file_content
        return UploadResult(
            object_key=object_key,
            size_bytes=len(file_content),
            content_type=content_type,
        )

    async def generate_presigned_url(
        self,
        object_key: str,
        expiration_seconds: int = 3600,
        content_disposition: str | None = None,
    ) -> str:
        return f"https://storage.example/{object_key}"

    async def delete_file(self, object_key: str) -> bool:
        return self._files.pop(object_key, None) is not None

    async def file_exists(self, object_key: str) -> bool:
        return object_key in self._files

    async def get_file(self, object_key: str) -> bytes | None:
        return self._files.get(object_key)

    async def list_files(self, prefix: str, max_keys: int = 1000) -> list[str]:
        return [key for key in self._files if key.startswith(prefix)][:max_keys]

    async def create_multipart_upload(
        self,
        object_key: str,
        content_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> MultipartUploadResult:
        return MultipartUploadResult(upload_id="upload-1", object_key=object_key)

    async def upload_part(
        self,
        object_key: str,
        upload_id: str,
        part_number: int,
        data: bytes,
    ) -> PartUploadResult:
        return PartUploadResult(part_number=part_number, etag="etag")

    async def complete_multipart_upload(
        self,
        object_key: str,
        upload_id: str,
        parts: list[PartUploadResult],
    ) -> UploadResult:
        return UploadResult(
            object_key=object_key, size_bytes=0, content_type="application/octet-stream"
        )

    async def abort_multipart_upload(self, object_key: str, upload_id: str) -> bool:
        return True

    async def generate_presigned_upload_url(
        self,
        object_key: str,
        content_type: str,
        expiration_seconds: int = 3600,
    ) -> str:
        return f"https://storage.example/upload/{object_key}"


class _Repository:
    async def save(self, attachment: Attachment) -> Attachment:
        return attachment

    async def get(self, attachment_id: str) -> Attachment | None:
        return None

    async def get_by_conversation(
        self,
        conversation_id: str,
        status: AttachmentStatus | None = None,
    ) -> list[Attachment]:
        return []

    async def get_by_ids(self, attachment_ids: list[str]) -> list[Attachment]:
        return []

    async def delete(self, attachment_id: str) -> bool:
        return False

    async def delete_expired(self) -> int:
        return 0

    async def update_status(
        self,
        attachment_id: str,
        status: AttachmentStatus,
        error_message: str | None = None,
    ) -> bool:
        return False

    async def update_upload_progress(self, attachment_id: str, uploaded_parts: int) -> bool:
        return False

    async def update_sandbox_path(self, attachment_id: str, sandbox_path: str) -> bool:
        return False


def _make_attachment(
    *,
    attachment_id: str = "attachment-1",
    purpose: AttachmentPurpose = AttachmentPurpose.LLM_CONTEXT,
) -> Attachment:
    return Attachment(
        id=attachment_id,
        conversation_id="conversation-1",
        project_id="project-1",
        tenant_id="tenant-1",
        filename="secret.txt",
        mime_type="text/plain",
        size_bytes=12,
        object_key="attachments/tenant/project/conversation/secret.txt",
        purpose=purpose,
        status=AttachmentStatus.UPLOADED,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.unit
async def test_prepare_for_llm_batch_log_omits_attachment_id_and_exception_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_attachment_id = "attachment-llm-secret"
    exception_detail = "llm prepare leaked attachment attachment-llm-secret"

    class _FailingLLMService(AttachmentService):
        async def prepare_for_llm(self, attachment: Attachment) -> dict[str, Any]:
            raise RuntimeError(exception_detail)

    service = _FailingLLMService(
        storage_service=_Storage({}),
        attachment_repository=_Repository(),
    )

    with caplog.at_level("WARNING", logger="src.application.services.attachment_service"):
        result = await service.prepare_for_llm_batch(
            [_make_attachment(attachment_id=secret_attachment_id)]
        )

    assert result == []
    assert secret_attachment_id not in caplog.text
    assert exception_detail not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
async def test_prepare_for_sandbox_batch_log_omits_attachment_id_and_exception_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_attachment_id = "attachment-sandbox-secret"
    exception_detail = "sandbox prepare leaked attachment attachment-sandbox-secret"

    class _FailingSandboxService(AttachmentService):
        async def prepare_for_sandbox(self, attachment: Attachment) -> dict[str, Any]:
            raise RuntimeError(exception_detail)

    service = _FailingSandboxService(
        storage_service=_Storage({}),
        attachment_repository=_Repository(),
    )

    with caplog.at_level("WARNING", logger="src.application.services.attachment_service"):
        result = await service.prepare_for_sandbox_batch(
            [
                _make_attachment(
                    attachment_id=secret_attachment_id,
                    purpose=AttachmentPurpose.SANDBOX_INPUT,
                )
            ]
        )

    assert result == []
    assert secret_attachment_id not in caplog.text
    assert exception_detail not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
async def test_delete_log_omits_storage_exception_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_attachment_id = "attachment-delete-secret"
    exception_detail = "delete storage leaked attachment attachment-delete-secret"
    attachment = _make_attachment(attachment_id=secret_attachment_id)

    class _FailingDeleteStorage(_Storage):
        async def delete_file(self, object_key: str) -> bool:
            raise RuntimeError(exception_detail)

    class _DeleteRepository(_Repository):
        async def get(self, attachment_id: str) -> Attachment | None:
            return attachment

        async def delete(self, attachment_id: str) -> bool:
            return True

    service = AttachmentService(
        storage_service=_FailingDeleteStorage({attachment.object_key: b"secret"}),
        attachment_repository=_DeleteRepository(),
    )

    with caplog.at_level("WARNING", logger="src.application.services.attachment_service"):
        deleted = await service.delete(secret_attachment_id)

    assert deleted is True
    assert secret_attachment_id not in caplog.text
    assert exception_detail not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
async def test_prepare_for_sandbox_log_omits_content_fingerprints(
    caplog: pytest.LogCaptureFixture,
) -> None:
    content = b"secret-token-value from uploaded file"
    object_key = "attachments/tenant/project/conversation/secret.txt"
    service = AttachmentService(
        storage_service=_Storage({object_key: content}),
        attachment_repository=_Repository(),
    )
    attachment = Attachment(
        id="attachment-1",
        conversation_id="conversation-1",
        project_id="project-1",
        tenant_id="tenant-1",
        filename="secret.txt",
        mime_type="text/plain",
        size_bytes=len(content),
        object_key=object_key,
        purpose=AttachmentPurpose.SANDBOX_INPUT,
        status=AttachmentStatus.UPLOADED,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    with caplog.at_level("INFO", logger="src.application.services.attachment_service"):
        result = await service.prepare_for_sandbox(attachment)

    assert result["source_md5"] == hashlib.md5(content).hexdigest()
    assert "secret.txt" in caplog.text
    assert "source_md5" not in caplog.text
    assert hashlib.md5(content).hexdigest() not in caplog.text
    assert content[:16].hex() not in caplog.text
    assert "secret-token-value" not in caplog.text
