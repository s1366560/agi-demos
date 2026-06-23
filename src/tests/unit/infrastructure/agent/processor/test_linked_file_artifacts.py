"""Tests for persisting previewable file links from assistant text."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.events.agent_events import AgentArtifactCreatedEvent
from src.domain.model.artifact.artifact import ArtifactCategory
from src.infrastructure.agent.core.llm_stream import StreamEvent
from src.infrastructure.agent.processor.artifact_handler import (
    ArtifactHandler,
    extract_previewable_session_file_paths,
)
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)
from src.infrastructure.agent.tools.result import ToolResult


class _FakeArtifactService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create_artifact(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        filename = kwargs["filename"]
        mime_type = "text/markdown" if filename.endswith(".md") else "text/plain"
        return SimpleNamespace(
            id=f"artifact-{len(self.calls)}",
            filename=filename,
            mime_type=mime_type,
            category=ArtifactCategory.DOCUMENT,
            size_bytes=len(kwargs["file_content"]),
            url=f"https://files.example.com/{filename}",
            preview_url=None,
        )


class _TextWithLinkedFileStream:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    async def generate(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[StreamEvent]:
        text = "Report: [/workspace/output/report.md](/workspace/output/report.md)"
        yield StreamEvent.text_start()
        yield StreamEvent.text_delta(text)
        yield StreamEvent.text_end(text)
        yield StreamEvent.finish("stop")


def _export_result(path: str, content: str = "# report") -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": content}],
        "isError": False,
        "artifact": {
            "filename": path.rsplit("/", 1)[-1],
            "path": path,
            "mime_type": "text/markdown",
            "category": "text",
            "size": len(content.encode("utf-8")),
            "encoding": "utf-8",
            "is_binary": False,
        },
    }


@pytest.mark.unit
def test_extract_previewable_session_file_paths_normalizes_and_deduplicates() -> None:
    text = (
        "Report: [full](output/report.md), duplicate /workspace/output/report.md, "
        "ignored archive /workspace/output/archive.zip, image ~/output/chart.png"
    )

    paths = extract_previewable_session_file_paths(text)

    assert paths == ["/workspace/output/report.md", "/workspace/output/chart.png"]


@pytest.mark.unit
async def test_process_text_file_links_exports_and_uploads_linked_file() -> None:
    service = _FakeArtifactService()
    handler = ArtifactHandler(service, langfuse_context=None)
    handler.set_langfuse_context(
        {
            "project_id": "project-1",
            "tenant_id": "tenant-1",
            "conversation_id": "conversation-1",
            "sandbox_id": "sandbox-1",
        }
    )
    exported_paths: list[str] = []

    async def export_file(path: str) -> dict[str, Any]:
        exported_paths.append(path)
        return _export_result(path)

    events = [
        event
        async for event in handler.process_text_file_links(
            "Open /workspace/output/report.md",
            export_file=export_file,
        )
    ]

    assert exported_paths == ["/workspace/output/report.md"]
    assert service.calls[0]["source_path"] == "/workspace/output/report.md"
    assert service.calls[0]["source_tool"] == "session_file_link"
    assert service.calls[0]["file_content"] == b"# report"
    assert isinstance(events[0], AgentArtifactCreatedEvent)
    assert events[0].source_path == "/workspace/output/report.md"


@pytest.mark.unit
async def test_process_text_file_links_falls_back_to_raw_read_for_text_files() -> None:
    service = _FakeArtifactService()
    handler = ArtifactHandler(service, langfuse_context=None)
    handler.set_langfuse_context({"project_id": "project-1", "tenant_id": "tenant-1"})

    async def export_file(_path: str) -> dict[str, Any]:
        return {"isError": True}

    async def read_text_file(path: str) -> str:
        assert path == "/workspace/output/report.md"
        return "# fallback"

    events = [
        event
        async for event in handler.process_text_file_links(
            "Open output/report.md",
            export_file=export_file,
            read_text_file=read_text_file,
        )
    ]

    assert service.calls[0]["source_path"] == "/workspace/output/report.md"
    assert service.calls[0]["file_content"] == b"# fallback"
    assert isinstance(events[0], AgentArtifactCreatedEvent)


@pytest.mark.unit
async def test_process_step_persists_previewable_links_after_text_end(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.infrastructure.agent.processor.processor.LLMStream",
        _TextWithLinkedFileStream,
    )
    service = _FakeArtifactService()

    async def export_artifact(**kwargs: Any) -> ToolResult:
        return ToolResult(
            output="Exported",
            metadata=_export_result(str(kwargs["file_path"])),
        )

    processor = SessionProcessor(
        config=ProcessorConfig(model="test-model"),
        tools=[
            ToolDefinition(
                name="export_artifact",
                description="Export artifact",
                parameters={},
                execute=export_artifact,
            )
        ],
        artifact_service=service,
    )
    processor._langfuse_context = {
        "project_id": "project-1",
        "tenant_id": "tenant-1",
        "conversation_id": "conversation-1",
    }
    processor._artifact_handler.set_langfuse_context(processor._langfuse_context)

    events = [
        event
        async for event in processor._process_step(
            "session-1",
            [{"role": "user", "content": "make a report"}],
        )
    ]

    event_names = [event.__class__.__name__ for event in events]
    assert event_names.index("AgentTextEndEvent") < event_names.index("AgentArtifactCreatedEvent")
    artifact_events = [event for event in events if isinstance(event, AgentArtifactCreatedEvent)]
    assert artifact_events[0].source_path == "/workspace/output/report.md"
    assert service.calls[0]["source_path"] == "/workspace/output/report.md"
