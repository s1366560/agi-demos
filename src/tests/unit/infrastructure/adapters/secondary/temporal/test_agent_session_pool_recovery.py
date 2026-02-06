"""Tests for Agent Session Pool recovery after cache clearing.

This test suite ensures that when a session cache is cleared,
the system can properly recover and continue processing chat messages.
"""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
    AgentSessionContext,
    _agent_session_pool,
    clear_all_caches,
    clear_session_cache,
    compute_tools_hash,
    generate_session_key,
    get_or_create_agent_session,
    get_pool_stats,
    invalidate_agent_session,
)


@pytest.fixture(autouse=True)
def clear_session_pool_between_tests():
    """Clear the session pool before each test to avoid state leakage."""
    _agent_session_pool.clear()
    yield
    _agent_session_pool.clear()


class TestAgentSessionPoolRecovery:
    """Test session pool recovery after cache clearing."""

    @pytest.fixture
    def mock_tools(self):
        """Mock tools dictionary."""
        return {
            "memory_search": MagicMock(name="memory_search"),
            "entity_lookup": MagicMock(name="entity_lookup"),
        }

    @pytest.fixture
    def mock_processor_config(self):
        """Mock processor config."""
        config = MagicMock()
        config.temperature = 0.7
        config.max_tokens = 4096
        config.max_steps = 20
        return config

    @pytest.fixture
    def sample_session(self, mock_tools, mock_processor_config):
        """Create a sample session context."""
        return AgentSessionContext(
            session_key="tenant1:project1:default",
            tenant_id="tenant1",
            project_id="project1",
            agent_mode="default",
            tool_definitions=[],
            raw_tools=mock_tools,
            processor_config=mock_processor_config,
            tools_hash=compute_tools_hash(mock_tools),
            skills_hash="",
            subagents_hash="",
            use_count=5,  # Session has been used multiple times
            created_at=time.time() - 100,  # Created 100 seconds ago
            last_used_at=time.time() - 10,  # Last used 10 seconds ago
        )

    def test_generate_session_key(self):
        """Test session key generation."""
        key = generate_session_key("tenant1", "project1", "default")
        assert key == "tenant1:project1:default"

    def test_session_context_is_valid_for_with_matching_hash(self, sample_session):
        """Test session validity check with matching hashes."""
        assert sample_session.is_valid_for(
            tools_hash=sample_session.tools_hash,
            skills_hash=sample_session.skills_hash,
            subagents_hash=sample_session.subagents_hash,
        )

    def test_session_context_is_valid_for_with_mismatched_tools_hash(self, sample_session):
        """Test session validity check with mismatched tools hash."""
        assert not sample_session.is_valid_for(
            tools_hash="different_hash",
            skills_hash=sample_session.skills_hash,
            subagents_hash=sample_session.subagents_hash,
        )

    def test_session_context_is_expired(self, sample_session):
        """Test session expiration check."""
        # Session should not be expired (last used 10 seconds ago, TTL is 1800)
        assert not sample_session.is_expired()

        # Set last_used_at to make session expired (beyond 86400s TTL)
        sample_session.last_used_at = time.time() - 90000
        assert sample_session.is_expired()

    def test_session_context_touch_increments_use_count(self, sample_session):
        """Test that touch() updates last_used_at and increments use_count."""
        initial_use_count = sample_session.use_count
        initial_last_used = sample_session.last_used_at

        # Small delay to ensure timestamp changes
        time.sleep(0.01)
        sample_session.touch()

        assert sample_session.use_count == initial_use_count + 1
        assert sample_session.last_used_at > initial_last_used

    @pytest.mark.asyncio
    async def test_clear_session_cache_removes_specific_session(self, sample_session):
        """Test that clear_session_cache removes a specific session."""
        # Manually add session to pool
        from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
            _agent_session_pool,
        )

        _agent_session_pool[sample_session.session_key] = sample_session

        # Verify session exists
        assert sample_session.session_key in _agent_session_pool

        # Clear the session with grace_period=0 to force hard delete
        # (use_count > 1 would normally result in soft delete)
        result = await clear_session_cache(
            tenant_id=sample_session.tenant_id,
            project_id=sample_session.project_id,
            agent_mode=sample_session.agent_mode,
            grace_period_seconds=0,  # Force hard delete
        )

        assert result is True
        assert sample_session.session_key not in _agent_session_pool

    @pytest.mark.asyncio
    async def test_clear_session_cache_returns_false_for_nonexistent_session(self):
        """Test that clear_session_cache returns False for non-existent session."""
        result = await clear_session_cache(
            tenant_id="nonexistent",
            project_id="nonexistent",
            agent_mode="default",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_get_or_create_agent_session_reuses_existing_session(
        self, mock_tools, mock_processor_config
    ):
        """Test that get_or_create_agent_session reuses existing valid session."""
        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_session_pool.get_system_prompt_manager"
        ) as mock_get_manager:
            mock_manager = MagicMock()
            mock_get_manager.return_value = mock_manager

            # First call creates session
            session1 = await get_or_create_agent_session(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                tools=mock_tools,
                skills=[],
                subagents=[],
                processor_config=mock_processor_config,
            )

            # Second call should reuse session
            session2 = await get_or_create_agent_session(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                tools=mock_tools,
                skills=[],
                subagents=[],
                processor_config=mock_processor_config,
            )

            # Should be the same session object
            assert session1 is session2
            assert session1.use_count == 2

    @pytest.mark.asyncio
    async def test_get_or_create_agent_session_creates_new_after_clear(
        self, mock_tools, mock_processor_config
    ):
        """Test that get_or_create_agent_session creates new session after cache clear."""
        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_session_pool.get_system_prompt_manager"
        ) as mock_get_manager:
            mock_manager = MagicMock()
            mock_get_manager.return_value = mock_manager

            # Create initial session
            session1 = await get_or_create_agent_session(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                tools=mock_tools,
                skills=[],
                subagents=[],
                processor_config=mock_processor_config,
            )
            initial_use_count = session1.use_count

            # Clear the cache with grace_period=0 to force hard delete
            await clear_session_cache(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                grace_period_seconds=0,  # Force hard delete for testing
            )

            # Get session again - should create new session
            session2 = await get_or_create_agent_session(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                tools=mock_tools,
                skills=[],
                subagents=[],
                processor_config=mock_processor_config,
            )

            # Should be a different session object
            assert session1 is not session2
            # New session should start with use_count=1
            assert session2.use_count == 1

    @pytest.mark.asyncio
    async def test_invalidate_agent_session_with_full_key(self, sample_session):
        """Test invalidate_agent_session with exact key."""
        from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
            _agent_session_pool,
        )

        _agent_session_pool[sample_session.session_key] = sample_session

        count = invalidate_agent_session(
            tenant_id=sample_session.tenant_id,
            project_id=sample_session.project_id,
            agent_mode=sample_session.agent_mode,
        )

        assert count == 1
        assert sample_session.session_key not in _agent_session_pool

    @pytest.mark.asyncio
    async def test_invalidate_agent_session_with_tenant_only(self, sample_session):
        """Test invalidate_agent_session with tenant prefix."""
        from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
            _agent_session_pool,
        )

        # Add multiple sessions for the same tenant
        _agent_session_pool["tenant1:project1:default"] = sample_session
        _agent_session_pool["tenant1:project2:default"] = sample_session

        count = invalidate_agent_session(tenant_id="tenant1")

        assert count == 2

    @pytest.mark.asyncio
    async def test_clear_all_caches(self, sample_session):
        """Test that clear_all_caches clears all cache entries."""
        from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
            _agent_session_pool,
            _subagent_router_cache,
            _tool_definitions_cache,
        )

        _agent_session_pool[sample_session.session_key] = sample_session
        _tool_definitions_cache["test_hash"] = []
        _subagent_router_cache["tenant1:hash"] = MagicMock()

        counts = clear_all_caches()

        assert counts["sessions"] >= 1
        assert counts["tool_definitions"] >= 1
        assert len(_agent_session_pool) == 0
        assert len(_tool_definitions_cache) == 0
        assert len(_subagent_router_cache) == 0

    def test_get_pool_stats(self, sample_session):
        """Test get_pool_stats returns correct statistics."""
        from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
            _agent_session_pool,
            _tool_definitions_cache,
        )

        _agent_session_pool[sample_session.session_key] = sample_session
        _tool_definitions_cache["test_hash"] = []

        stats = get_pool_stats()

        assert stats["total_sessions"] == 1
        assert stats["tool_definitions_cached"] == 1
        assert stats["total_use_count"] == sample_session.use_count


class TestAgentSessionRecoveryIntegration:
    """Integration tests for session recovery in chat workflow."""

    @pytest.mark.asyncio
    async def test_session_recovery_scenario(self):
        """
        Test the full scenario:
        1. Create a session and use it
        2. Cache gets cleared
        3. Next request should create new session and succeed
        """
        mock_tools = {
            "test_tool": MagicMock(name="test_tool"),
        }
        mock_processor_config = MagicMock()
        mock_processor_config.temperature = 0.7
        mock_processor_config.max_tokens = 4096
        mock_processor_config.max_steps = 20

        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_session_pool.get_system_prompt_manager"
        ) as mock_get_manager:
            mock_manager = MagicMock()
            mock_get_manager.return_value = mock_manager

            # Step 1: Create session
            session = await get_or_create_agent_session(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                tools=mock_tools,
                skills=[],
                subagents=[],
                processor_config=mock_processor_config,
            )

            assert session is not None
            assert session.use_count == 1

            # Step 2: Use session a few times
            session.touch()
            session.touch()
            assert session.use_count == 3

            # Step 3: Simulate cache clear (e.g., workflow timeout)
            # Use grace_period_seconds=0 to force hard delete
            await clear_session_cache(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                grace_period_seconds=0,  # Force hard delete for testing
            )

            # Step 4: Next request should create new session
            new_session = await get_or_create_agent_session(
                tenant_id="tenant1",
                project_id="project1",
                agent_mode="default",
                tools=mock_tools,
                skills=[],
                subagents=[],
                processor_config=mock_processor_config,
            )

            assert new_session is not None
            assert new_session.use_count == 1  # New session starts fresh
            assert new_session.session_key == session.session_key  # Same key

    @pytest.mark.asyncio
    async def test_concurrent_session_access_after_clear(self):
        """Test that concurrent requests after cache clear are handled correctly."""
        mock_tools = {"test": MagicMock()}
        mock_config = MagicMock()
        mock_config.temperature = 0.7
        mock_config.max_tokens = 4096
        mock_config.max_steps = 20

        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_session_pool.get_system_prompt_manager"
        ) as mock_get_manager:
            mock_get_manager.return_value = MagicMock()

            # Clear any existing sessions
            await clear_session_cache("tenant1", "project1", "default")

            # Create concurrent requests
            async def get_session():
                return await get_or_create_agent_session(
                    tenant_id="tenant1",
                    project_id="project1",
                    agent_mode="default",
                    tools=mock_tools,
                    skills=[],
                    subagents=[],
                    processor_config=mock_config,
                )

            # Run multiple concurrent requests
            sessions = await asyncio.gather(*[get_session() for _ in range(5)])

            # All should get the same session instance (after first one creates it)
            first_session = sessions[0]
            for session in sessions[1:]:
                # Due to lock, they should all get the same cached session
                assert session is first_session

            # Use count should be 5 (one per concurrent request)
            assert first_session.use_count == 5
