"""Unit tests for channel media import service."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.services.channels.media_import_service import MediaImportService


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
