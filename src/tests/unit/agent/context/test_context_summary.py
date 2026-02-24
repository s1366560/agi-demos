"""Tests for ContextSummary value object, ContextLoader, and SqlContextSummaryAdapter."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.services.agent.context_loader import ContextLoader
from src.domain.model.agent.conversation.context_summary import ContextSummary


@pytest.mark.unit
class TestContextSummary:
    """Tests for ContextSummary value object."""

    def test_create_summary(self):
        summary = ContextSummary(
            summary_text="User discussed project setup.",
            summary_tokens=50,
            messages_covered_up_to=1700000000000000,
            messages_covered_count=20,
            compression_level="l2_summarize",
            model="gemini-2.0-flash",
        )
        assert summary.summary_text == "User discussed project setup."
        assert summary.summary_tokens == 50
        assert summary.messages_covered_up_to == 1700000000000000
        assert summary.messages_covered_count == 20
        assert summary.compression_level == "l2_summarize"
        assert summary.model == "gemini-2.0-flash"

    def test_frozen_immutability(self):
        summary = ContextSummary(
            summary_text="test",
            summary_tokens=10,
            messages_covered_up_to=0,
            messages_covered_count=0,
        )
        with pytest.raises(AttributeError):
            summary.summary_text = "modified"

    def test_to_dict(self):
        now = datetime.now(UTC)
        summary = ContextSummary(
            summary_text="Summary text",
            summary_tokens=100,
            messages_covered_up_to=1700000000000000,
            messages_covered_count=10,
            compression_level="l2_summarize",
            created_at=now,
            model="gpt-4",
        )
        d = summary.to_dict()
        assert d["summary_text"] == "Summary text"
        assert d["summary_tokens"] == 100
        assert d["messages_covered_up_to"] == 1700000000000000
        assert d["messages_covered_count"] == 10
        assert d["compression_level"] == "l2_summarize"
        assert d["created_at"] == now.isoformat()
        assert d["model"] == "gpt-4"

    def test_from_dict(self):
        data = {
            "summary_text": "Restored summary",
            "summary_tokens": 200,
            "messages_covered_up_to": 1700000000000000,
            "messages_covered_count": 30,
            "compression_level": "l3_deep_compress",
            "created_at": "2024-01-01T00:00:00+00:00",
            "model": "gemini-2.0-flash",
        }
        summary = ContextSummary.from_dict(data)
        assert summary.summary_text == "Restored summary"
        assert summary.summary_tokens == 200
        assert summary.messages_covered_count == 30
        assert summary.compression_level == "l3_deep_compress"
        assert summary.model == "gemini-2.0-flash"

    def test_from_dict_missing_optional_fields(self):
        data = {
            "summary_text": "Minimal summary",
        }
        summary = ContextSummary.from_dict(data)
        assert summary.summary_text == "Minimal summary"
        assert summary.summary_tokens == 0
        assert summary.messages_covered_up_to == 0
        assert summary.messages_covered_count == 0
        assert summary.compression_level == "l2_summarize"
        assert summary.model is None

    def test_roundtrip_serialization(self):
        original = ContextSummary(
            summary_text="Round trip test",
            summary_tokens=150,
            messages_covered_up_to=1700000000000000,
            messages_covered_count=25,
            compression_level="l2_summarize",
            model="test-model",
        )
        restored = ContextSummary.from_dict(original.to_dict())
        assert restored.summary_text == original.summary_text
        assert restored.summary_tokens == original.summary_tokens
        assert restored.messages_covered_up_to == original.messages_covered_up_to
        assert restored.messages_covered_count == original.messages_covered_count
        assert restored.compression_level == original.compression_level
        assert restored.model == original.model


def _make_event(event_id, role, content, event_time_us=0):
    """Helper to create mock AgentExecutionEvent."""
    event = MagicMock()
    event.id = event_id
    event.event_data = {"role": role, "content": content}
    event.event_time_us = event_time_us
    return event


@pytest.mark.unit
class TestContextLoader:
    """Tests for ContextLoader smart context loading."""

    def _make_loader(self, event_repo=None, summary_adapter=None):
        event_repo = event_repo or AsyncMock()
        summary_adapter = summary_adapter or AsyncMock()
        return ContextLoader(
            event_repo=event_repo,
            summary_adapter=summary_adapter,
        )

    async def test_load_without_summary_fallback(self):
        """When no summary exists, falls back to loading last N messages."""
        event_repo = AsyncMock()
        event_repo.count_messages.return_value = 10
        event_repo.get_message_events.return_value = [
            _make_event("e1", "user", "Hello"),
            _make_event("e2", "assistant", "Hi there"),
        ]
        summary_adapter = AsyncMock()
        summary_adapter.get_summary.return_value = None

        loader = self._make_loader(event_repo, summary_adapter)
        result = await loader.load_context("conv-1")

        assert not result.from_cache
        assert result.summary is None
        assert len(result.messages) == 2
        assert result.messages[0]["role"] == "user"
        assert result.messages[1]["role"] == "assistant"
        assert result.total_message_count == 10
        event_repo.get_message_events.assert_called_once_with(
            conversation_id="conv-1", limit=50
        )

    async def test_load_with_cached_summary(self):
        """When summary exists, loads summary + recent messages."""
        summary = ContextSummary(
            summary_text="Earlier discussion about architecture.",
            summary_tokens=100,
            messages_covered_up_to=1700000000000000,
            messages_covered_count=15,
        )
        event_repo = AsyncMock()
        event_repo.count_messages.return_value = 20
        event_repo.get_message_events_after.return_value = [
            _make_event("e16", "user", "Recent question"),
            _make_event("e17", "assistant", "Recent answer"),
        ]
        summary_adapter = AsyncMock()
        summary_adapter.get_summary.return_value = summary

        loader = self._make_loader(event_repo, summary_adapter)
        result = await loader.load_context("conv-1")

        assert result.from_cache
        assert result.summary is summary
        assert len(result.messages) == 2
        assert result.summarized_message_count == 15
        assert result.recent_message_count == 2
        assert result.total_message_count == 20
        event_repo.get_message_events_after.assert_called_once_with(
            conversation_id="conv-1",
            after_time_us=1700000000000000,
        )
        # Should NOT call the fallback method
        event_repo.get_message_events.assert_not_called()

    async def test_exclude_event_id(self):
        """Should exclude specified event ID from results."""
        event_repo = AsyncMock()
        event_repo.count_messages.return_value = 3
        event_repo.get_message_events.return_value = [
            _make_event("e1", "user", "First"),
            _make_event("e2", "assistant", "Reply"),
            _make_event("e3", "user", "Current"),
        ]
        summary_adapter = AsyncMock()
        summary_adapter.get_summary.return_value = None

        loader = self._make_loader(event_repo, summary_adapter)
        result = await loader.load_context("conv-1", exclude_event_id="e3")

        assert len(result.messages) == 2
        assert result.messages[0]["content"] == "First"
        assert result.messages[1]["content"] == "Reply"

    async def test_summary_with_zero_cutoff_falls_back(self):
        """Summary with messages_covered_up_to=0 should fall back."""
        summary = ContextSummary(
            summary_text="Invalid summary",
            summary_tokens=10,
            messages_covered_up_to=0,
            messages_covered_count=0,
        )
        event_repo = AsyncMock()
        event_repo.count_messages.return_value = 5
        event_repo.get_message_events.return_value = []
        summary_adapter = AsyncMock()
        summary_adapter.get_summary.return_value = summary

        loader = self._make_loader(event_repo, summary_adapter)
        result = await loader.load_context("conv-1")

        assert not result.from_cache
        event_repo.get_message_events.assert_called_once()

    async def test_save_summary(self):
        """Should delegate save to summary adapter."""
        summary_adapter = AsyncMock()
        loader = self._make_loader(summary_adapter=summary_adapter)

        summary = ContextSummary(
            summary_text="Test",
            summary_tokens=10,
            messages_covered_up_to=100,
            messages_covered_count=5,
        )
        await loader.save_summary("conv-1", summary)
        summary_adapter.save_summary.assert_called_once_with("conv-1", summary)

    async def test_invalidate_summary(self):
        """Should delegate invalidation to summary adapter."""
        summary_adapter = AsyncMock()
        loader = self._make_loader(summary_adapter=summary_adapter)

        await loader.invalidate_summary("conv-1")
        summary_adapter.invalidate_summary.assert_called_once_with("conv-1")
