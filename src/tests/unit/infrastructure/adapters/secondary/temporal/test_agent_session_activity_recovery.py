"""Tests for Agent Session Activity recovery after cache clearing.

This test suite ensures that execute_chat_activity can properly recover
when the session pool cache is cleared between requests.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
    clear_session_cache,
    get_or_create_agent_session,
)
from src.infrastructure.adapters.secondary.temporal.activities.agent_session import (
    cleanup_agent_session_activity,
)


class TestExecuteChatActivityRecovery:
    """Test execute_chat_activity recovery after cache clearing."""

    @pytest.mark.asyncio
    async def test_execute_chat_returns_error_on_exception(self):
        """Test that execute_chat_activity handles exceptions gracefully."""
        sample_chat_input = {
            "conversation_id": str(uuid.uuid4()),
            "message_id": str(uuid.uuid4()),
            "user_message": "Hello, test!",
            "user_id": str(uuid.uuid4()),
            "conversation_context": [],
            "session_config": {
                "tenant_id": "tenant1",
                "project_id": "project1",
                "agent_mode": "default",
            },
            "session_data": {},
        }

        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_worker_state.get_agent_graph_service",
            side_effect=Exception("Test exception"),
        ):
            from src.infrastructure.adapters.secondary.temporal.activities.agent_session import (
                execute_chat_activity,
            )

            result = await execute_chat_activity(sample_chat_input)

            assert result["is_error"] is True
            assert "Test exception" in result["error_message"]


class TestSessionCleanupIntegration:
    """Integration tests for session cleanup and recovery."""

    @pytest.mark.asyncio
    async def test_workflow_stop_cleanup_sequence(self):
        """Test the sequence when workflow stops and cleans up session."""
        # Use unique IDs to avoid collision with other tests
        test_id = str(uuid.uuid4())[:8]

        # Create a session first
        mock_tools = {"test": MagicMock()}
        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_session_pool.get_system_prompt_manager"
        ) as mock_get_manager:
            mock_get_manager.return_value = MagicMock()

            session = await get_or_create_agent_session(
                tenant_id=f"tenant{test_id}",
                project_id=f"project{test_id}",
                agent_mode="default",
                tools=mock_tools,
                skills=[],
                subagents=[],
                processor_config=MagicMock(
                    temperature=0.7, max_tokens=4096, max_steps=20
                ),
            )

            assert session is not None
            assert session.use_count == 1

            # Simulate workflow stop cleanup
            config = {
                "tenant_id": f"tenant{test_id}",
                "project_id": f"project{test_id}",
                "agent_mode": "default",
            }

            result = await cleanup_agent_session_activity(config)

            assert result["status"] == "cleaned"
            assert result["cleared"] is True

            # Verify session was cleared
            # Next request should create new session
            new_session = await get_or_create_agent_session(
                tenant_id=f"tenant{test_id}",
                project_id=f"project{test_id}",
                agent_mode="default",
                tools=mock_tools,
                skills=[],
                subagents=[],
                processor_config=MagicMock(
                    temperature=0.7, max_tokens=4096, max_steps=20
                ),
            )

            assert new_session.use_count == 1  # New session starts fresh

    @pytest.mark.asyncio
    async def test_cleanup_nonexistent_session(self):
        """Test cleanup of a session that doesn't exist."""
        config = {
            "tenant_id": "nonexistent",
            "project_id": "nonexistent",
            "agent_mode": "default",
        }

        result = await cleanup_agent_session_activity(config)

        # Should succeed even if session doesn't exist
        assert result["status"] == "cleaned"
        assert result["cleared"] is False
