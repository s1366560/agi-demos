"""Unit tests for channel media import service."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.services.channels.media_import_service import MediaImportService
from src.domain.model.channels.message import (
    ChatType,
    Message,
    MessageContent,
    MessageType,
    SenderInfo,
)


@pytest.mark.unit
async def test_import_media_success_logs_omit_platform_keys_and_paths(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Successful media import logs should not expose file keys, names, or sandbox paths."""
    message = Message(
        channel="feishu",
        chat_type=ChatType.P2P,
        chat_id="chat-1",
        sender=SenderInfo(id="sender-1"),
        content=MessageContent(
            type=MessageType.FILE,
            file_key="file-secret-key",
            file_name="private-roadmap.pdf",
        ),
        project_id="project-1",
        raw_data={"event": {"message": {"message_id": "message-secret-id"}}},
    )
    downloader = SimpleNamespace(
        download_media=AsyncMock(
            return_value=(
                b"file-bytes",
                {
                    "filename": "private-roadmap.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 42,
                },
            )
        )
    )
    mcp_adapter = SimpleNamespace(
        get_or_create_sandbox=AsyncMock(return_value=SimpleNamespace(id="sandbox-1")),
        call_tool=AsyncMock(
            return_value={
                "is_error": False,
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "success": True,
                                "path": "/workspace/input/private-roadmap.pdf",
                            }
                        ),
                    }
                ],
            }
        ),
    )
    artifact = SimpleNamespace(id="artifact-1")
    artifact_service = SimpleNamespace(create_artifact=AsyncMock(return_value=artifact))
    service = MediaImportService(feishu_downloader=downloader)

    with caplog.at_level(
        "INFO",
        logger="src.application.services.channels.media_import_service",
    ):
        result = await service.import_media_to_workspace(
            message=message,
            project_id="project-1",
            tenant_id="tenant-1",
            conversation_id="conv-1",
            mcp_adapter=mcp_adapter,
            artifact_service=artifact_service,
            db_session=SimpleNamespace(),
        )

    assert result == "/workspace/input/private-roadmap.pdf"
    downloader.download_media.assert_awaited_once_with(
        file_key="file-secret-key",
        media_type="file",
        message_id="message-secret-id",
        file_name="private-roadmap.pdf",
    )
    assert "file-secret-key" not in caplog.text
    assert "message-secret-id" not in caplog.text
    assert "private-roadmap.pdf" not in caplog.text
    assert "/workspace/input/private-roadmap.pdf" not in caplog.text
    assert "artifact-1" in caplog.text


@pytest.mark.unit
async def test_create_artifact_success_log_omits_filename(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Artifact success logs should not expose user-provided filenames."""
    artifact = SimpleNamespace(id="artifact-1")
    artifact_service = SimpleNamespace(create_artifact=AsyncMock(return_value=artifact))
    service = MediaImportService(feishu_downloader=AsyncMock())

    with caplog.at_level(
        "INFO",
        logger="src.application.services.channels.media_import_service",
    ):
        result = await service._create_artifact(
            content=b"file-bytes",
            filename="private-roadmap.pdf",
            metadata={"mime_type": "application/pdf", "size_bytes": 42},
            project_id="project-1",
            tenant_id="tenant-1",
            conversation_id="conv-1",
            sandbox_path="/workspace/input/private-roadmap.pdf",
            artifact_service=artifact_service,
        )

    assert result is artifact
    artifact_service.create_artifact.assert_awaited_once_with(
        file_content=b"file-bytes",
        filename="private-roadmap.pdf",
        project_id="project-1",
        tenant_id="tenant-1",
        source_path="/workspace/input/private-roadmap.pdf",
        conversation_id="conv-1",
        metadata={
            "source": "feishu",
            "mime_type": "application/pdf",
            "size_bytes": 42,
            "original_mime_type": "application/pdf",
        },
    )
    assert "artifact-1" in caplog.text
    assert "private-roadmap.pdf" not in caplog.text
    assert "/workspace/input/private-roadmap.pdf" not in caplog.text


@pytest.mark.unit
async def test_create_artifact_failure_log_omits_filename_and_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Artifact failure logs should not expose filenames or backend exception text."""
    artifact_service = SimpleNamespace(
        create_artifact=AsyncMock(side_effect=RuntimeError("secret-storage-token"))
    )
    service = MediaImportService(feishu_downloader=AsyncMock())

    with caplog.at_level(
        "ERROR",
        logger="src.application.services.channels.media_import_service",
    ):
        result = await service._create_artifact(
            content=b"file-bytes",
            filename="private-roadmap.pdf",
            metadata={"mime_type": "application/pdf", "size_bytes": 42},
            project_id="project-1",
            tenant_id="tenant-1",
            conversation_id="conv-1",
            sandbox_path="/workspace/input/private-roadmap.pdf",
            artifact_service=artifact_service,
        )

    assert result is None
    assert "private-roadmap.pdf" not in caplog.text
    assert "/workspace/input/private-roadmap.pdf" not in caplog.text
    assert "secret-storage-token" not in caplog.text
    assert "RuntimeError" in caplog.text
