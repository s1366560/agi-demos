"""Tests for Phase 5.1: SubAgent Memory Sharing (MemoryAccessor)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.subagent.memory_accessor import (
    MemoryAccessor,
    MemoryItem,
    MemoryWriteResult,
)


@pytest.mark.unit
class TestMemoryItem:
    def test_defaults(self):
        item = MemoryItem(content="test content")
        assert item.content == "test content"
        assert item.item_type == "episode"
        assert item.score == 0.0
        assert item.source_id == ""
        assert item.metadata == {}

    def test_all_fields(self):
        item = MemoryItem(
            content="hello",
            item_type="entity",
            score=0.95,
            source_id="abc-123",
            metadata={"key": "val"},
        )
        assert item.item_type == "entity"
        assert item.score == 0.95
        assert item.source_id == "abc-123"


@pytest.mark.unit
class TestMemoryWriteResult:
    def test_success(self):
        r = MemoryWriteResult(success=True, episode_id="ep-1")
        assert r.success
        assert r.episode_id == "ep-1"
        assert r.error is None

    def test_failure(self):
        r = MemoryWriteResult(success=False, error="Access denied")
        assert not r.success
        assert r.error == "Access denied"


@pytest.mark.unit
class TestMemoryAccessorSearch:
    async def test_search_returns_items(self):
        graph = AsyncMock()
        graph.search.return_value = [
            {"content": "User likes Python", "type": "entity", "score": 0.9, "uuid": "e1"},
            {"content": "Meeting on Monday", "type": "episode", "score": 0.7, "uuid": "e2"},
        ]

        accessor = MemoryAccessor(graph, project_id="proj-1")
        items = await accessor.search("user preferences")

        assert len(items) == 2
        assert items[0].content == "User likes Python"
        assert items[0].item_type == "entity"
        assert items[0].score == 0.9
        assert items[1].content == "Meeting on Monday"
        graph.search.assert_called_once_with(query="user preferences", project_id="proj-1", limit=5)

    async def test_search_with_custom_limit(self):
        graph = AsyncMock()
        graph.search.return_value = []

        accessor = MemoryAccessor(graph, project_id="proj-1", max_results=10)
        await accessor.search("test", limit=3)

        graph.search.assert_called_once_with(query="test", project_id="proj-1", limit=3)

    async def test_search_uses_default_limit(self):
        graph = AsyncMock()
        graph.search.return_value = []

        accessor = MemoryAccessor(graph, project_id="proj-1", max_results=7)
        await accessor.search("test")

        graph.search.assert_called_once_with(query="test", project_id="proj-1", limit=7)

    async def test_search_handles_error_gracefully(self):
        graph = AsyncMock()
        graph.search.side_effect = RuntimeError("connection failed")

        accessor = MemoryAccessor(graph, project_id="proj-1")
        items = await accessor.search("test")

        assert items == []

    async def test_search_empty_results(self):
        graph = AsyncMock()
        graph.search.return_value = []

        accessor = MemoryAccessor(graph, project_id="proj-1")
        items = await accessor.search("nonexistent")

        assert items == []

    async def test_search_normalizes_objects(self):
        """Test normalization of object-based results (e.g., SearchResultItem)."""
        result_obj = MagicMock()
        result_obj.content = "object content"
        result_obj.type = "entity"
        result_obj.score = 0.85
        result_obj.uuid = "obj-1"
        result_obj.metadata = {"key": "val"}

        graph = AsyncMock()
        graph.search.return_value = [result_obj]

        accessor = MemoryAccessor(graph, project_id="proj-1")
        items = await accessor.search("query")

        assert len(items) == 1
        assert items[0].content == "object content"
        assert items[0].item_type == "entity"

    async def test_search_normalizes_summary_fallback(self):
        """Test that 'summary' field is used when 'content' is absent."""
        graph = AsyncMock()
        graph.search.return_value = [
            {"summary": "Entity summary", "type": "entity", "score": 0.5, "id": "s-1"},
        ]

        accessor = MemoryAccessor(graph, project_id="proj-1")
        items = await accessor.search("query")

        assert items[0].content == "Entity summary"


@pytest.mark.unit
class TestMemoryAccessorWrite:
    async def test_write_denied_when_not_writable(self):
        graph = AsyncMock()
        accessor = MemoryAccessor(graph, project_id="proj-1", writable=False)

        result = await accessor.write("test content")

        assert not result.success
        assert "not granted" in result.error
        graph.add_episode.assert_not_called()

    async def test_write_succeeds_when_writable(self):
        saved_episode = MagicMock()
        saved_episode.uuid = "ep-new-1"

        graph = AsyncMock()
        graph.add_episode.return_value = saved_episode

        accessor = MemoryAccessor(graph, project_id="proj-1", writable=True)
        result = await accessor.write("important finding", source_description="researcher")

        assert result.success
        assert result.episode_id == "ep-new-1"
        graph.add_episode.assert_called_once()

        # Verify the episode passed to add_episode
        call_args = graph.add_episode.call_args
        episode = call_args[1].get("episode") or call_args[0][0]
        assert episode.content == "important finding"
        assert episode.project_id == "proj-1"
        assert "subagent" in episode.name

    async def test_write_handles_error(self):
        graph = AsyncMock()
        graph.add_episode.side_effect = RuntimeError("DB error")

        accessor = MemoryAccessor(graph, project_id="proj-1", writable=True)
        result = await accessor.write("content")

        assert not result.success
        assert "DB error" in result.error

    async def test_is_writable_property(self):
        graph = AsyncMock()
        assert not MemoryAccessor(graph, "p1", writable=False).is_writable
        assert MemoryAccessor(graph, "p1", writable=True).is_writable


@pytest.mark.unit
class TestMemoryAccessorFormat:
    def test_format_empty(self):
        graph = AsyncMock()
        accessor = MemoryAccessor(graph, project_id="proj-1")

        assert accessor.format_for_context([]) == ""

    def test_format_single_item(self):
        graph = AsyncMock()
        accessor = MemoryAccessor(graph, project_id="proj-1")

        items = [MemoryItem(content="User prefers Python", item_type="entity")]
        result = accessor.format_for_context(items)

        assert "[Relevant memories" in result
        assert "1. [entity] User prefers Python" in result

    def test_format_multiple_items(self):
        graph = AsyncMock()
        accessor = MemoryAccessor(graph, project_id="proj-1")

        items = [
            MemoryItem(content="Fact A", item_type="episode"),
            MemoryItem(content="Fact B", item_type="entity"),
        ]
        result = accessor.format_for_context(items)

        assert "1. [episode] Fact A" in result
        assert "2. [entity] Fact B" in result

    def test_format_respects_max_chars(self):
        graph = AsyncMock()
        accessor = MemoryAccessor(graph, project_id="proj-1", max_chars=50)

        items = [
            MemoryItem(content="A" * 100, item_type="episode"),
            MemoryItem(content="B" * 100, item_type="episode"),
        ]
        result = accessor.format_for_context(items)

        # Should truncate
        assert len(result) < 200


@pytest.mark.unit
class TestContextBridgeMemoryIntegration:
    """Test that ContextBridge correctly handles memory_context."""

    def test_build_context_with_memory(self):
        from src.infrastructure.agent.subagent.context_bridge import ContextBridge

        bridge = ContextBridge()
        context = bridge.build_subagent_context(
            user_message="Analyze code",
            subagent_system_prompt="You are a code analyst.",
            memory_context="[Relevant memories]\n1. User prefers Python",
            project_id="proj-1",
        )

        assert context.memory_context == "[Relevant memories]\n1. User prefers Python"

    def test_build_context_without_memory(self):
        from src.infrastructure.agent.subagent.context_bridge import ContextBridge

        bridge = ContextBridge()
        context = bridge.build_subagent_context(
            user_message="Analyze code",
            subagent_system_prompt="You are a code analyst.",
        )

        assert context.memory_context == ""

    def test_build_messages_includes_memory(self):
        from src.infrastructure.agent.subagent.context_bridge import (
            ContextBridge,
            SubAgentContext,
        )

        bridge = ContextBridge()
        context = SubAgentContext(
            task_description="Do analysis",
            system_prompt="You are an analyst.",
            memory_context="[Memories] 1. Important fact",
        )

        messages = bridge.build_messages(context)

        # Should be: system, memory, user_task
        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are an analyst."
        assert messages[1]["role"] == "system"
        assert "[Memories]" in messages[1]["content"]
        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "Do analysis"

    def test_build_messages_skips_empty_memory(self):
        from src.infrastructure.agent.subagent.context_bridge import (
            ContextBridge,
            SubAgentContext,
        )

        bridge = ContextBridge()
        context = SubAgentContext(
            task_description="Do analysis",
            system_prompt="You are an analyst.",
            memory_context="",
        )

        messages = bridge.build_messages(context)

        # Should be: system, user_task (no memory message)
        assert len(messages) == 2

    def test_build_messages_memory_after_context(self):
        from src.infrastructure.agent.subagent.context_bridge import (
            ContextBridge,
            SubAgentContext,
        )

        bridge = ContextBridge()
        context = SubAgentContext(
            task_description="Do analysis",
            system_prompt="You are an analyst.",
            context_messages=[{"role": "user", "content": "Previous turn"}],
            memory_context="[Memories] Fact A",
        )

        messages = bridge.build_messages(context)

        # system, context_msg, memory, user_task
        assert len(messages) == 4
        assert messages[0]["role"] == "system"
        assert messages[1]["content"] == "Previous turn"
        assert messages[2]["content"] == "[Memories] Fact A"
        assert messages[3]["content"] == "Do analysis"
