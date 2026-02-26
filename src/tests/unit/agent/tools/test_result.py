"""Tests for ToolResult, ToolAttachment, and ToolEvent."""

import time

import pytest

from src.infrastructure.agent.tools.result import ToolAttachment, ToolEvent, ToolResult


@pytest.mark.unit
class TestToolAttachment:
    """Tests for ToolAttachment dataclass."""

    def test_create_with_defaults(self) -> None:
        # Arrange & Act
        attachment = ToolAttachment(name="file.txt", content=b"hello")

        # Assert
        assert attachment.name == "file.txt"
        assert attachment.content == b"hello"
        assert attachment.mime_type == "application/octet-stream"

    def test_create_with_custom_mime_type(self) -> None:
        # Arrange & Act
        attachment = ToolAttachment(
            name="image.png",
            content=b"\x89PNG",
            mime_type="image/png",
        )

        # Assert
        assert attachment.mime_type == "image/png"

    def test_string_content(self) -> None:
        # Arrange & Act
        attachment = ToolAttachment(name="data.json", content='{"key": "value"}')

        # Assert
        assert attachment.content == '{"key": "value"}'


@pytest.mark.unit
class TestToolResult:
    """Tests for ToolResult dataclass."""

    def test_create_minimal(self) -> None:
        # Arrange & Act
        result = ToolResult(output="Hello world")

        # Assert
        assert result.output == "Hello world"
        assert result.title is None
        assert result.metadata == {}
        assert result.attachments == []
        assert result.is_error is False
        assert result.was_truncated is False
        assert result.original_bytes is None
        assert result.full_output_path is None

    def test_create_full(self) -> None:
        # Arrange
        attachment = ToolAttachment(name="f.txt", content=b"data")

        # Act
        result = ToolResult(
            output="output",
            title="My Title",
            metadata={"key": "val"},
            attachments=[attachment],
            is_error=True,
            was_truncated=True,
            original_bytes=1024,
            full_output_path="/tmp/out.txt",
        )

        # Assert
        assert result.title == "My Title"
        assert result.metadata == {"key": "val"}
        assert len(result.attachments) == 1
        assert result.is_error is True
        assert result.was_truncated is True
        assert result.original_bytes == 1024
        assert result.full_output_path == "/tmp/out.txt"

    def test_metadata_default_not_shared(self) -> None:
        # Verify each instance gets its own metadata dict
        r1 = ToolResult(output="a")
        r2 = ToolResult(output="b")
        r1.metadata["x"] = 1

        assert "x" not in r2.metadata

    def test_attachments_default_not_shared(self) -> None:
        r1 = ToolResult(output="a")
        r2 = ToolResult(output="b")
        r1.attachments.append(ToolAttachment(name="f", content=b""))

        assert len(r2.attachments) == 0


@pytest.mark.unit
class TestToolEvent:
    """Tests for ToolEvent dataclass and factory methods."""

    def test_create_direct(self) -> None:
        # Arrange & Act
        event = ToolEvent(type="custom", tool_name="my_tool", data={"k": "v"})

        # Assert
        assert event.type == "custom"
        assert event.tool_name == "my_tool"
        assert event.data == {"k": "v"}
        assert isinstance(event.timestamp, float)

    def test_timestamp_auto_set(self) -> None:
        # Arrange
        before = time.time()

        # Act
        event = ToolEvent(type="test", tool_name="t")

        # Assert
        after = time.time()
        assert before <= event.timestamp <= after

    def test_started_factory(self) -> None:
        # Arrange & Act
        event = ToolEvent.started("read_file", {"path": "/tmp/f.txt"})

        # Assert
        assert event.type == "started"
        assert event.tool_name == "read_file"
        assert event.data == {"args": {"path": "/tmp/f.txt"}}

    def test_completed_factory_without_artifacts(self) -> None:
        # Arrange
        result = ToolResult(output="ok", was_truncated=True)

        # Act
        event = ToolEvent.completed("write_file", result)

        # Assert
        assert event.type == "completed"
        assert event.tool_name == "write_file"
        assert event.data["is_error"] is False
        assert event.data["was_truncated"] is True
        assert event.data["_result"] is result
        assert "artifacts" not in event.data

    def test_completed_factory_with_artifacts(self) -> None:
        # Arrange
        result = ToolResult(output="ok", is_error=True)
        artifacts = [{"id": "a1"}]

        # Act
        event = ToolEvent.completed("tool", result, artifacts=artifacts)

        # Assert
        assert event.data["artifacts"] == [{"id": "a1"}]
        assert event.data["is_error"] is True

    def test_denied_factory(self) -> None:
        event = ToolEvent.denied("dangerous_tool")
        assert event.type == "denied"
        assert event.tool_name == "dangerous_tool"

    def test_doom_loop_factory(self) -> None:
        event = ToolEvent.doom_loop("stuck_tool")
        assert event.type == "doom_loop"
        assert event.tool_name == "stuck_tool"

    def test_permission_asked_factory(self) -> None:
        event = ToolEvent.permission_asked("bash")
        assert event.type == "permission_asked"
        assert event.tool_name == "bash"

    def test_aborted_factory(self) -> None:
        event = ToolEvent.aborted("long_tool")
        assert event.type == "aborted"
        assert event.tool_name == "long_tool"

    def test_data_default_not_shared(self) -> None:
        e1 = ToolEvent(type="a", tool_name="t")
        e2 = ToolEvent(type="b", tool_name="t")
        e1.data["x"] = 1
        assert "x" not in e2.data
