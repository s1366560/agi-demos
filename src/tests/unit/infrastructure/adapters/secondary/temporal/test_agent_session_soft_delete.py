"""Tests for Agent Session Pool soft delete mechanism.

This test suite ensures that the soft delete mechanism with grace period
works correctly, allowing sessions to be recovered if reused within the grace period.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
    AgentSessionContext,
    _agent_session_pool,
    cleanup_marked_sessions,
    clear_session_cache,
    compute_tools_hash,
    generate_session_key,
    get_or_create_agent_session,
)


@pytest.fixture(autouse=True)
def clear_session_pool_between_tests():
    """Clear the session pool before each test to avoid state leakage."""
    _agent_session_pool.clear()
    yield
    _agent_session_pool.clear()


class TestSoftDeleteMechanism:
    """Test soft delete mechanism with grace period."""

    @pytest.mark.asyncio
    async def test_soft_delete_marks_session_for_deletion(self):
        """Test that clear_session_cache marks session for deletion when use_count > 1."""
        mock_tools = {"test": MagicMock()}
        mock_config = MagicMock()

        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_session_pool.get_system_prompt_manager"
        ) as mock_get_manager:
            mock_get_manager.return_value = MagicMock()

            # Create session
            session = await get_or_create_agent_session(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                tools=mock_tools,
                skills=[],
                subagents=[],
                processor_config=mock_config,
            )

            # Use session multiple times
            session.touch()
            session.touch()
            assert session.use_count == 3

            # Clear with grace period
            result = await clear_session_cache(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                grace_period_seconds=300,
            )

            assert result is True
            # Session should be marked for deletion, not removed
            assert hasattr(session, "_marked_for_deletion_at")

    @pytest.mark.asyncio
    async def test_soft_delete_with_low_use_count_hard_deletes(self):
        """Test that sessions with low use_count are hard deleted immediately."""
        # Use unique ID to avoid collision with other tests
        test_id = "unique_low_use"
        mock_tools = {"test": MagicMock()}
        mock_config = MagicMock()

        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_session_pool.get_system_prompt_manager"
        ) as mock_get_manager:
            mock_get_manager.return_value = MagicMock()

            session = await get_or_create_agent_session(
                tenant_id=f"tenant_{test_id}",
                project_id=f"project_{test_id}",
                agent_mode="default",
                tools=mock_tools,
                skills=[],
                subagents=[],
                processor_config=mock_config,
            )

            session_key = generate_session_key(f"tenant_{test_id}", f"project_{test_id}", "default")

            # Clear with grace period - should hard delete since use_count == 1
            result = await clear_session_cache(
                tenant_id=f"tenant_{test_id}",
                project_id=f"project_{test_id}",
                agent_mode="default",
                grace_period_seconds=300,
            )

            assert result is True
            # Session should be removed from pool
            from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
                _agent_session_pool,
            )
            assert session_key not in _agent_session_pool

    @pytest.mark.asyncio
    async def test_session_recovered_after_soft_delete(self):
        """Test that a soft-deleted session can be recovered if reused."""
        mock_tools = {"test": MagicMock()}
        mock_config = MagicMock()

        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_session_pool.get_system_prompt_manager"
        ) as mock_get_manager:
            mock_get_manager.return_value = MagicMock()

            # Create and use session multiple times
            session1 = await get_or_create_agent_session(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                tools=mock_tools,
                skills=[],
                subagents=[],
                processor_config=mock_config,
            )
            session1.touch()
            session1.touch()  # use_count = 3

            # Soft delete
            await clear_session_cache(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                grace_period_seconds=300,
            )

            # Session should be marked
            assert hasattr(session1, "_marked_for_deletion_at")

            # Get session again - should recover the same session
            session2 = await get_or_create_agent_session(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                tools=mock_tools,
                skills=[],
                subagents=[],
                processor_config=mock_config,
            )

            # Should be the same session object
            assert session1 is session2
            # Should no longer be marked for deletion
            assert not hasattr(session2, "_marked_for_deletion_at")

    @pytest.mark.asyncio
    async def test_cleanup_marked_sessions_removes_expired(self):
        """Test that cleanup_marked_sessions removes sessions past grace period."""
        mock_tools = {"test": MagicMock()}
        mock_config = MagicMock()

        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_session_pool.get_system_prompt_manager"
        ) as mock_get_manager:
            mock_get_manager.return_value = MagicMock()

            # Create and use session
            session = await get_or_create_agent_session(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                tools=mock_tools,
                skills=[],
                subagents=[],
                processor_config=mock_config,
            )
            session.touch()
            session.touch()  # use_count = 3

            # Mark for deletion with short grace period
            session._marked_for_deletion_at = time.time() - 10  # Already expired

            session_key = generate_session_key("tenant1", "project1", "default")

            # Run cleanup
            cleaned = await cleanup_marked_sessions()

            assert cleaned == 1

            from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
                _agent_session_pool,
            )
            assert session_key not in _agent_session_pool

    @pytest.mark.asyncio
    async def test_cleanup_marked_sessions_keeps_valid(self):
        """Test that cleanup_marked_sessions keeps sessions within grace period."""
        mock_tools = {"test": MagicMock()}
        mock_config = MagicMock()

        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_session_pool.get_system_prompt_manager"
        ) as mock_get_manager:
            mock_get_manager.return_value = MagicMock()

            session = await get_or_create_agent_session(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                tools=mock_tools,
                skills=[],
                subagents=[],
                processor_config=mock_config,
            )
            session.touch()
            session.touch()

            # Mark for deletion with future timestamp
            session._marked_for_deletion_at = time.time() + 300  # Expires in 5 minutes

            session_key = generate_session_key("tenant1", "project1", "default")

            # Run cleanup
            cleaned = await cleanup_marked_sessions()

            assert cleaned == 0

            from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
                _agent_session_pool,
            )
            assert session_key in _agent_session_pool

    @pytest.mark.asyncio
    async def test_soft_delete_with_zero_grace_period_hard_deletes(self):
        """Test that grace_period_seconds=0 results in hard delete."""
        mock_tools = {"test": MagicMock()}
        mock_config = MagicMock()

        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_session_pool.get_system_prompt_manager"
        ) as mock_get_manager:
            mock_get_manager.return_value = MagicMock()

            session = await get_or_create_agent_session(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                tools=mock_tools,
                skills=[],
                subagents=[],
                processor_config=mock_config,
            )
            session.touch()
            session.touch()  # use_count = 3

            session_key = generate_session_key("tenant1", "project1", "default")

            # Clear with zero grace period - should hard delete regardless of use_count
            result = await clear_session_cache(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                grace_period_seconds=0,
            )

            assert result is True

            from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
                _agent_session_pool,
            )
            assert session_key not in _agent_session_pool
