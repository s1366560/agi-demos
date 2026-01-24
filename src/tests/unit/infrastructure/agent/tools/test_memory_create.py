"""Unit tests for MemoryCreateTool."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from src.infrastructure.agent.tools.memory_create import MemoryCreateTool

from src.domain.model.memory.episode import Episode, SourceType


class TestMemoryCreateToolInit:
    """Test MemoryCreateTool initialization."""

    def test_init_sets_correct_name(self, mock_graph_service):
        """Test tool initializes with correct name."""
        tool = MemoryCreateTool(mock_graph_service)
        assert tool.name == "memory_create"

    def test_init_sets_description(self, mock_graph_service):
        """Test tool initializes with meaningful description."""
        tool = MemoryCreateTool(mock_graph_service)
        assert "memory" in tool.description.lower()
        assert "create" in tool.description.lower()


class TestMemoryCreateToolValidation:
    """Test MemoryCreateTool argument validation."""

    def test_validate_args_with_valid_content(self, mock_graph_service):
        """Test validation passes with valid content."""
        tool = MemoryCreateTool(mock_graph_service)
        assert tool.validate_args(content="This is a test memory") is True

    def test_validate_args_with_empty_content(self, mock_graph_service):
        """Test validation fails with empty content."""
        tool = MemoryCreateTool(mock_graph_service)
        assert tool.validate_args(content="") is False

    def test_validate_args_with_whitespace_only(self, mock_graph_service):
        """Test validation fails with whitespace-only content."""
        tool = MemoryCreateTool(mock_graph_service)
        assert tool.validate_args(content="   ") is False
        assert tool.validate_args(content="\t\n") is False

    def test_validate_args_missing_content(self, mock_graph_service):
        """Test validation fails when content is missing."""
        tool = MemoryCreateTool(mock_graph_service)
        assert tool.validate_args() is False
        assert tool.validate_args(name="Test Name") is False

    def test_validate_args_non_string_content(self, mock_graph_service):
        """Test validation fails with non-string content."""
        tool = MemoryCreateTool(mock_graph_service)
        assert tool.validate_args(content=123) is False
        assert tool.validate_args(content=None) is False
        assert tool.validate_args(content=["list"]) is False


class TestMemoryCreateToolExecute:
    """Test MemoryCreateTool execute method."""

    @pytest.mark.asyncio
    async def test_execute_creates_episode(self, mock_graph_service):
        """Test execute creates an episode successfully."""
        mock_episode = Mock()
        mock_episode.id = "ep-123"
        mock_episode.name = "Test Memory"
        mock_graph_service.add_episode = AsyncMock(return_value=mock_episode)

        tool = MemoryCreateTool(mock_graph_service)
        result = await tool.execute(content="This is a test memory")

        assert "Successfully created memory entry" in result
        mock_graph_service.add_episode.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_with_custom_name(self, mock_graph_service):
        """Test execute uses custom name when provided."""
        mock_episode = Mock()
        mock_episode.id = "ep-123"
        mock_episode.name = "My Custom Memory"
        mock_graph_service.add_episode = AsyncMock(return_value=mock_episode)

        tool = MemoryCreateTool(mock_graph_service)
        result = await tool.execute(content="Memory content", name="My Custom Memory")

        assert "Successfully created" in result
        call_args = mock_graph_service.add_episode.call_args
        episode_arg = call_args[0][0]
        assert episode_arg.name == "My Custom Memory"

    @pytest.mark.asyncio
    async def test_execute_generates_default_name(self, mock_graph_service):
        """Test execute generates default name when not provided."""
        mock_episode = Mock()
        mock_episode.id = "ep-123"
        mock_episode.name = "Agent Memory - 2024-01-15T10:00:00"
        mock_graph_service.add_episode = AsyncMock(return_value=mock_episode)

        tool = MemoryCreateTool(mock_graph_service)
        await tool.execute(content="Memory content")

        call_args = mock_graph_service.add_episode.call_args
        episode_arg = call_args[0][0]
        assert "Agent Memory" in episode_arg.name

    @pytest.mark.asyncio
    async def test_execute_with_project_id(self, mock_graph_service):
        """Test execute passes project_id to episode."""
        mock_episode = Mock()
        mock_episode.id = "ep-123"
        mock_episode.name = "Test"
        mock_graph_service.add_episode = AsyncMock(return_value=mock_episode)

        tool = MemoryCreateTool(mock_graph_service)
        await tool.execute(content="Memory content", project_id="proj-123")

        call_args = mock_graph_service.add_episode.call_args
        episode_arg = call_args[0][0]
        assert episode_arg.project_id == "proj-123"

    @pytest.mark.asyncio
    async def test_execute_with_user_id(self, mock_graph_service):
        """Test execute passes user_id to episode."""
        mock_episode = Mock()
        mock_episode.id = "ep-123"
        mock_episode.name = "Test"
        mock_graph_service.add_episode = AsyncMock(return_value=mock_episode)

        tool = MemoryCreateTool(mock_graph_service)
        await tool.execute(content="Memory content", user_id="user-123")

        call_args = mock_graph_service.add_episode.call_args
        episode_arg = call_args[0][0]
        assert episode_arg.user_id == "user-123"

    @pytest.mark.asyncio
    async def test_execute_with_tenant_id(self, mock_graph_service):
        """Test execute passes tenant_id to episode."""
        mock_episode = Mock()
        mock_episode.id = "ep-123"
        mock_episode.name = "Test"
        mock_graph_service.add_episode = AsyncMock(return_value=mock_episode)

        tool = MemoryCreateTool(mock_graph_service)
        await tool.execute(content="Memory content", tenant_id="tenant-123")

        call_args = mock_graph_service.add_episode.call_args
        episode_arg = call_args[0][0]
        assert episode_arg.tenant_id == "tenant-123"

    @pytest.mark.asyncio
    async def test_execute_generates_uuid(self, mock_graph_service):
        """Test execute generates valid UUID for episode."""
        mock_episode = Mock()
        mock_episode.id = "ep-123"
        mock_episode.name = "Test"
        mock_graph_service.add_episode = AsyncMock(return_value=mock_episode)

        tool = MemoryCreateTool(mock_graph_service)
        await tool.execute(content="Memory content")

        call_args = mock_graph_service.add_episode.call_args
        episode_arg = call_args[0][0]
        # Verify it's a valid UUID string
        try:
            uuid.UUID(episode_arg.id)
            valid_uuid = True
        except ValueError:
            valid_uuid = False
        assert valid_uuid

    @pytest.mark.asyncio
    async def test_execute_sets_source_type_conversation(self, mock_graph_service):
        """Test execute sets source_type to CONVERSATION."""
        mock_episode = Mock()
        mock_episode.id = "ep-123"
        mock_episode.name = "Test"
        mock_graph_service.add_episode = AsyncMock(return_value=mock_episode)

        tool = MemoryCreateTool(mock_graph_service)
        await tool.execute(content="Memory content")

        call_args = mock_graph_service.add_episode.call_args
        episode_arg = call_args[0][0]
        assert episode_arg.source_type == SourceType.CONVERSATION

    @pytest.mark.asyncio
    async def test_execute_sets_metadata(self, mock_graph_service):
        """Test execute sets metadata with created_by field."""
        mock_episode = Mock()
        mock_episode.id = "ep-123"
        mock_episode.name = "Test"
        mock_graph_service.add_episode = AsyncMock(return_value=mock_episode)

        tool = MemoryCreateTool(mock_graph_service)
        await tool.execute(content="Memory content")

        call_args = mock_graph_service.add_episode.call_args
        episode_arg = call_args[0][0]
        assert episode_arg.metadata == {"created_by": "agent_tool"}

    @pytest.mark.asyncio
    async def test_execute_missing_content_returns_error(self, mock_graph_service):
        """Test execute returns error when content is missing."""
        tool = MemoryCreateTool(mock_graph_service)
        result = await tool.execute()

        assert "Error" in result
        assert "content parameter is required" in result

    @pytest.mark.asyncio
    async def test_execute_truncates_long_content_in_response(self, mock_graph_service):
        """Test execute truncates long content in response message."""
        long_content = "A" * 500
        mock_episode = Mock()
        mock_episode.id = "ep-123"
        mock_episode.name = "Test"
        mock_graph_service.add_episode = AsyncMock(return_value=mock_episode)

        tool = MemoryCreateTool(mock_graph_service)
        result = await tool.execute(content=long_content)

        # Content in response should be truncated to 200 chars with ...
        assert "..." in result
        # The full content should still be passed to the episode
        call_args = mock_graph_service.add_episode.call_args
        episode_arg = call_args[0][0]
        assert episode_arg.content == long_content

    @pytest.mark.asyncio
    async def test_execute_returns_episode_uuid(self, mock_graph_service):
        """Test execute returns episode UUID in response."""
        mock_episode = Mock()
        mock_episode.id = "ep-unique-123"
        mock_episode.name = "Test Memory"
        mock_graph_service.add_episode = AsyncMock(return_value=mock_episode)

        tool = MemoryCreateTool(mock_graph_service)
        result = await tool.execute(content="Memory content")

        assert "UUID: ep-unique-123" in result

    @pytest.mark.asyncio
    async def test_execute_returns_episode_name(self, mock_graph_service):
        """Test execute returns episode name in response."""
        mock_episode = Mock()
        mock_episode.id = "ep-123"
        mock_episode.name = "My Test Memory"
        mock_graph_service.add_episode = AsyncMock(return_value=mock_episode)

        tool = MemoryCreateTool(mock_graph_service)
        result = await tool.execute(content="Memory content")

        assert "Name: My Test Memory" in result

    @pytest.mark.asyncio
    async def test_execute_includes_async_processing_note(self, mock_graph_service):
        """Test execute includes note about async processing."""
        mock_episode = Mock()
        mock_episode.id = "ep-123"
        mock_episode.name = "Test"
        mock_graph_service.add_episode = AsyncMock(return_value=mock_episode)

        tool = MemoryCreateTool(mock_graph_service)
        result = await tool.execute(content="Memory content")

        assert "asynchronously" in result.lower()


class TestMemoryCreateToolErrorHandling:
    """Test MemoryCreateTool error handling."""

    @pytest.mark.asyncio
    async def test_execute_handles_graph_service_error(self, mock_graph_service):
        """Test execute handles graph service errors gracefully."""
        mock_graph_service.add_episode = AsyncMock(
            side_effect=Exception("Database connection failed")
        )

        tool = MemoryCreateTool(mock_graph_service)
        result = await tool.execute(content="Memory content")

        assert "Error creating memory" in result
        assert "Database connection failed" in result

    @pytest.mark.asyncio
    async def test_execute_handles_validation_error(self, mock_graph_service):
        """Test execute handles Episode validation errors."""
        mock_graph_service.add_episode = AsyncMock(side_effect=ValueError("Invalid episode data"))

        tool = MemoryCreateTool(mock_graph_service)
        result = await tool.execute(content="Memory content")

        assert "Error creating memory" in result

    @pytest.mark.asyncio
    async def test_execute_handles_timeout_error(self, mock_graph_service):
        """Test execute handles timeout errors."""
        mock_graph_service.add_episode = AsyncMock(side_effect=TimeoutError("Operation timed out"))

        tool = MemoryCreateTool(mock_graph_service)
        result = await tool.execute(content="Memory content")

        assert "Error creating memory" in result


class TestMemoryCreateToolEpisodeCreation:
    """Test MemoryCreateTool episode creation details."""

    @pytest.mark.asyncio
    async def test_execute_sets_valid_at_timestamp(self, mock_graph_service):
        """Test execute sets valid_at timestamp."""
        mock_episode = Mock()
        mock_episode.id = "ep-123"
        mock_episode.name = "Test"
        mock_graph_service.add_episode = AsyncMock(return_value=mock_episode)

        tool = MemoryCreateTool(mock_graph_service)
        await tool.execute(content="Memory content")

        call_args = mock_graph_service.add_episode.call_args
        episode_arg = call_args[0][0]
        assert episode_arg.valid_at is not None
        assert isinstance(episode_arg.valid_at, datetime)

    @pytest.mark.asyncio
    async def test_execute_creates_episode_instance(self, mock_graph_service):
        """Test execute creates proper Episode instance."""
        mock_episode = Mock()
        mock_episode.id = "ep-123"
        mock_episode.name = "Test"
        mock_graph_service.add_episode = AsyncMock(return_value=mock_episode)

        tool = MemoryCreateTool(mock_graph_service)
        await tool.execute(content="Memory content")

        call_args = mock_graph_service.add_episode.call_args
        episode_arg = call_args[0][0]
        assert isinstance(episode_arg, Episode)
