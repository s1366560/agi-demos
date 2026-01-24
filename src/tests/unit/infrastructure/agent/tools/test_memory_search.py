"""Unit tests for MemorySearchTool."""

import pytest
from src.infrastructure.agent.tools.memory_search import MemorySearchTool


class TestMemorySearchToolInit:
    """Test MemorySearchTool initialization."""

    def test_init_sets_correct_name(self, mock_graph_service):
        """Test tool initializes with correct name."""
        tool = MemorySearchTool(mock_graph_service)
        assert tool.name == "memory_search"

    def test_init_sets_description(self, mock_graph_service):
        """Test tool initializes with meaningful description."""
        tool = MemorySearchTool(mock_graph_service)
        assert "search" in tool.description.lower()
        assert "memories" in tool.description.lower() or "memory" in tool.description.lower()


class TestMemorySearchToolValidation:
    """Test MemorySearchTool argument validation."""

    def test_validate_args_with_valid_query(self, mock_graph_service):
        """Test validation passes with valid query."""
        tool = MemorySearchTool(mock_graph_service)
        assert tool.validate_args(query="test query") is True

    def test_validate_args_with_empty_query(self, mock_graph_service):
        """Test validation fails with empty query."""
        tool = MemorySearchTool(mock_graph_service)
        assert tool.validate_args(query="") is False

    def test_validate_args_with_whitespace_only(self, mock_graph_service):
        """Test validation fails with whitespace-only query."""
        tool = MemorySearchTool(mock_graph_service)
        assert tool.validate_args(query="   ") is False
        assert tool.validate_args(query="\t\n") is False

    def test_validate_args_missing_query(self, mock_graph_service):
        """Test validation fails when query is missing."""
        tool = MemorySearchTool(mock_graph_service)
        assert tool.validate_args() is False
        assert tool.validate_args(other="value") is False

    def test_validate_args_non_string_query(self, mock_graph_service):
        """Test validation fails with non-string query."""
        tool = MemorySearchTool(mock_graph_service)
        assert tool.validate_args(query=123) is False
        assert tool.validate_args(query=None) is False
        assert tool.validate_args(query=["list"]) is False


class TestMemorySearchToolExecute:
    """Test MemorySearchTool execute method."""

    @pytest.mark.asyncio
    async def test_execute_returns_formatted_results(self, mock_graph_service):
        """Test execute returns formatted search results."""
        mock_graph_service.search.return_value = [
            {"type": "episode", "content": "Test episode content", "uuid": "ep-123"},
            {"type": "entity", "name": "TestEntity", "summary": "Entity summary"},
        ]

        tool = MemorySearchTool(mock_graph_service)
        result = await tool.execute(query="test")

        assert "Found 2 result(s)" in result
        assert "[EPISODE]" in result
        assert "[ENTITY]" in result
        assert "Test episode content" in result
        assert "TestEntity" in result

    @pytest.mark.asyncio
    async def test_execute_with_episode_results(self, mock_graph_service):
        """Test execute formats episode results correctly."""
        mock_graph_service.search.return_value = [
            {
                "type": "episode",
                "content": "Meeting with Alice about project deadline",
                "uuid": "ep-456",
            }
        ]

        tool = MemorySearchTool(mock_graph_service)
        result = await tool.execute(query="meeting")

        assert "[EPISODE]" in result
        assert "Meeting with Alice" in result
        assert "ep-456" in result

    @pytest.mark.asyncio
    async def test_execute_with_entity_results(self, mock_graph_service):
        """Test execute formats entity results correctly."""
        mock_graph_service.search.return_value = [
            {
                "type": "entity",
                "name": "Alice",
                "summary": "Software engineer working on AI projects",
            }
        ]

        tool = MemorySearchTool(mock_graph_service)
        result = await tool.execute(query="Alice")

        assert "[ENTITY]" in result
        assert "Name: Alice" in result
        assert "Summary: Software engineer" in result

    @pytest.mark.asyncio
    async def test_execute_no_results(self, mock_graph_service):
        """Test execute returns appropriate message when no results found."""
        mock_graph_service.search.return_value = []

        tool = MemorySearchTool(mock_graph_service)
        result = await tool.execute(query="nonexistent")

        assert "No memories found" in result
        assert "nonexistent" in result

    @pytest.mark.asyncio
    async def test_execute_with_project_id(self, mock_graph_service):
        """Test execute passes project_id to graph service."""
        mock_graph_service.search.return_value = []

        tool = MemorySearchTool(mock_graph_service)
        await tool.execute(query="test", project_id="proj-123")

        mock_graph_service.search.assert_called_once_with(
            query="test",
            project_id="proj-123",
            limit=10,
        )

    @pytest.mark.asyncio
    async def test_execute_with_custom_limit(self, mock_graph_service):
        """Test execute passes custom limit to graph service."""
        mock_graph_service.search.return_value = []

        tool = MemorySearchTool(mock_graph_service)
        await tool.execute(query="test", limit=5)

        mock_graph_service.search.assert_called_once_with(
            query="test",
            project_id=None,
            limit=5,
        )

    @pytest.mark.asyncio
    async def test_execute_default_limit_is_10(self, mock_graph_service):
        """Test execute uses default limit of 10."""
        mock_graph_service.search.return_value = []

        tool = MemorySearchTool(mock_graph_service)
        await tool.execute(query="test")

        mock_graph_service.search.assert_called_once_with(
            query="test",
            project_id=None,
            limit=10,
        )

    @pytest.mark.asyncio
    async def test_execute_missing_query_returns_error(self, mock_graph_service):
        """Test execute returns error when query is missing."""
        tool = MemorySearchTool(mock_graph_service)
        result = await tool.execute()

        assert "Error" in result
        assert "query parameter is required" in result

    @pytest.mark.asyncio
    async def test_execute_truncates_long_content(self, mock_graph_service):
        """Test execute truncates long episode content."""
        long_content = "A" * 500  # 500 characters
        mock_graph_service.search.return_value = [
            {"type": "episode", "content": long_content, "uuid": "ep-123"}
        ]

        tool = MemorySearchTool(mock_graph_service)
        result = await tool.execute(query="test")

        # Content should be truncated to 200 chars with ...
        assert "..." in result
        assert "A" * 200 in result
        assert "A" * 201 not in result


class TestMemorySearchToolErrorHandling:
    """Test MemorySearchTool error handling."""

    @pytest.mark.asyncio
    async def test_execute_handles_vector_dimension_mismatch(self, mock_graph_service):
        """Test execute handles vector dimension mismatch error gracefully."""
        mock_graph_service.search.side_effect = Exception(
            "Failed to invoke procedure vector.similarity.cosine(): "
            "All vectors must have the same dimension - expected 768 but got 1536"
        )

        tool = MemorySearchTool(mock_graph_service)
        result = await tool.execute(query="test")

        assert "embedding dimension mismatch" in result.lower()
        assert "switching LLM providers" in result.lower() or "cannot search" in result.lower()

    @pytest.mark.asyncio
    async def test_execute_handles_generic_exception(self, mock_graph_service):
        """Test execute handles generic exceptions gracefully."""
        mock_graph_service.search.side_effect = Exception("Database connection failed")

        tool = MemorySearchTool(mock_graph_service)
        result = await tool.execute(query="test")

        assert "Error searching memories" in result
        assert "Database connection failed" in result

    @pytest.mark.asyncio
    async def test_execute_handles_timeout_exception(self, mock_graph_service):
        """Test execute handles timeout exceptions."""
        mock_graph_service.search.side_effect = TimeoutError("Query timed out")

        tool = MemorySearchTool(mock_graph_service)
        result = await tool.execute(query="test")

        assert "Error searching memories" in result
        assert "timed out" in result.lower()


class TestMemorySearchToolResultFormatting:
    """Test MemorySearchTool result formatting edge cases."""

    @pytest.mark.asyncio
    async def test_execute_handles_missing_content(self, mock_graph_service):
        """Test execute handles episode with missing content."""
        mock_graph_service.search.return_value = [
            {"type": "episode", "uuid": "ep-123"}  # No content field
        ]

        tool = MemorySearchTool(mock_graph_service)
        result = await tool.execute(query="test")

        assert "[EPISODE]" in result
        assert "ep-123" in result

    @pytest.mark.asyncio
    async def test_execute_handles_missing_uuid(self, mock_graph_service):
        """Test execute handles episode with missing uuid."""
        mock_graph_service.search.return_value = [
            {"type": "episode", "content": "Some content"}  # No uuid field
        ]

        tool = MemorySearchTool(mock_graph_service)
        result = await tool.execute(query="test")

        assert "[EPISODE]" in result
        assert "Some content" in result

    @pytest.mark.asyncio
    async def test_execute_handles_unknown_type(self, mock_graph_service):
        """Test execute handles unknown result type."""
        mock_graph_service.search.return_value = [{"type": "unknown", "data": "some data"}]

        tool = MemorySearchTool(mock_graph_service)
        result = await tool.execute(query="test")

        assert "Found 1 result(s)" in result
        assert "[UNKNOWN]" in result

    @pytest.mark.asyncio
    async def test_execute_handles_entity_without_summary(self, mock_graph_service):
        """Test execute handles entity without summary."""
        mock_graph_service.search.return_value = [
            {"type": "entity", "name": "TestEntity"}  # No summary
        ]

        tool = MemorySearchTool(mock_graph_service)
        result = await tool.execute(query="test")

        assert "[ENTITY]" in result
        assert "Name: TestEntity" in result
