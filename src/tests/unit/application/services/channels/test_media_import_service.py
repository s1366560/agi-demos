"""Unit tests for channel media import service."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.services.channels.media_import_service import (
    MediaImportError,
    MediaImportService,
)
from src.domain.model.channels.message import (
    ChatType,
    Message,
    MessageContent,
    MessageType,
    SenderInfo,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("content", "project_id", "raw_data"),
    [
        (MessageContent(type=MessageType.TEXT, text="hello"), "project-1", None),
        (
            MessageContent(
                type=MessageType.FILE,
                file_key="secret-file-key",
                file_name="private-roadmap.pdf",
            ),
            "",
            {"event": {"message": {"message_id": "secret-platform-message-id"}}},
        ),
        (
            MessageContent(type=MessageType.IMAGE),
            "project-1",
            {"event": {"message": {"message_id": "secret-platform-message-id"}}},
        ),
    ],
)
async def test_import_media_skip_logs_omit_message_identifiers(
    caplog: pytest.LogCaptureFixture,
    content: MessageContent,
    project_id: str,
    raw_data: dict[str, object] | None,
) -> None:
    """Media import skip logs should not expose domain or platform message IDs."""
    message = Message(
        id="secret-domain-message-id",
        channel="feishu",
        chat_type=ChatType.P2P,
        chat_id="chat-1",
        sender=SenderInfo(id="sender-1"),
        content=content,
        project_id=project_id or None,
        raw_data=raw_data,
    )
    downloader = SimpleNamespace(download_media=AsyncMock())
    service = MediaImportService(feishu_downloader=downloader)

    with caplog.at_level(
        "DEBUG",
        logger="src.application.services.channels.media_import_service",
    ):
        result = await service.import_media_to_workspace(
            message=message,
            project_id=project_id,
            tenant_id="tenant-1",
            conversation_id="conv-1",
            mcp_adapter=SimpleNamespace(),
            artifact_service=SimpleNamespace(),
            db_session=SimpleNamespace(),
        )

    assert result is None
    downloader.download_media.assert_not_awaited()
    assert "secret-domain-message-id" not in caplog.text
    assert "secret-platform-message-id" not in caplog.text
    assert "secret-file-key" not in caplog.text
    assert "private-roadmap.pdf" not in caplog.text
    assert "has_domain_message_id=True" in caplog.text


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
async def test_import_to_sandbox_no_sandbox_error_omits_project_id() -> None:
    """Sandbox lookup failures should not expose project identifiers."""
    service = MediaImportService(feishu_downloader=AsyncMock())
    mcp_adapter = SimpleNamespace(
        get_or_create_sandbox=AsyncMock(return_value=None),
    )

    with pytest.raises(MediaImportError) as exc_info:
        await service._import_to_sandbox(
            content=b"file-bytes",
            filename="private-roadmap.pdf",
            project_id="secret-project-id",
            mcp_adapter=mcp_adapter,
            db_session=SimpleNamespace(),
        )

    message = str(exc_info.value)
    assert "secret-project-id" not in message
    assert "private-roadmap.pdf" not in message
    assert "No sandbox available" in message


@pytest.mark.unit
@pytest.mark.parametrize(
    "tool_result",
    [
        {"is_error": True, "error": "secret-sandbox-token"},
        {
            "is_error": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "success": False,
                            "error": "secret-sandbox-token",
                        }
                    ),
                }
            ],
        },
    ],
)
async def test_import_to_sandbox_failure_error_omits_backend_details(
    tool_result: dict[str, object],
) -> None:
    """Sandbox import failures should not expose backend error text."""
    service = MediaImportService(feishu_downloader=AsyncMock())
    mcp_adapter = SimpleNamespace(
        get_or_create_sandbox=AsyncMock(return_value=SimpleNamespace(id="secret-sandbox-id")),
        call_tool=AsyncMock(return_value=tool_result),
    )

    with pytest.raises(MediaImportError) as exc_info:
        await service._import_to_sandbox(
            content=b"file-bytes",
            filename="private-roadmap.pdf",
            project_id="secret-project-id",
            mcp_adapter=mcp_adapter,
            db_session=SimpleNamespace(),
        )

    message = str(exc_info.value)
    assert "secret-sandbox-token" not in message
    assert "secret-project-id" not in message
    assert "secret-sandbox-id" not in message
    assert "private-roadmap.pdf" not in message
    assert "Sandbox import failed" in message


@pytest.mark.unit
async def test_import_to_sandbox_unexpected_error_omits_exception_text() -> None:
    """Unexpected sandbox adapter failures should not expose exception text."""
    service = MediaImportService(feishu_downloader=AsyncMock())
    mcp_adapter = SimpleNamespace(
        get_or_create_sandbox=AsyncMock(return_value=SimpleNamespace(id="secret-sandbox-id")),
        call_tool=AsyncMock(side_effect=RuntimeError("secret-sandbox-token")),
    )

    with pytest.raises(MediaImportError) as exc_info:
        await service._import_to_sandbox(
            content=b"file-bytes",
            filename="private-roadmap.pdf",
            project_id="secret-project-id",
            mcp_adapter=mcp_adapter,
            db_session=SimpleNamespace(),
        )

    message = str(exc_info.value)
    assert "secret-sandbox-token" not in message
    assert "secret-project-id" not in message
    assert "secret-sandbox-id" not in message
    assert "private-roadmap.pdf" not in message
    assert "Failed to import to sandbox" in message


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
