"""Tests for RedisAgentSessionRegistry with mocked Redis."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.orchestration.redis_session_registry import (
    RedisAgentSessionRegistry,
)
from src.infrastructure.agent.orchestration.session_registry import AgentSession


@pytest.fixture
def mock_redis() -> MagicMock:
    """Create a mocked Redis client with proper pipeline mocking.

    The redis.pipeline() method itself is synchronous and returns a pipeline
    object (not a coroutine). The pipeline object's methods (setex, sadd, etc)
    are also synchronous and return self for chaining. Only execute() is async.
    Direct methods like get() and smembers() are async and should be AsyncMock.
    """
    redis = MagicMock()
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[True, True])
    pipe.setex = MagicMock(return_value=pipe)
    pipe.sadd = MagicMock(return_value=pipe)
    pipe.delete = MagicMock(return_value=pipe)
    pipe.srem = MagicMock(return_value=pipe)
    redis.pipeline.return_value = pipe
    redis.get = AsyncMock(return_value=None)
    redis.smembers = AsyncMock(return_value=set())
    return redis


@pytest.fixture
def registry(mock_redis: AsyncMock) -> RedisAgentSessionRegistry:
    """Create a RedisAgentSessionRegistry with mocked Redis."""
    return RedisAgentSessionRegistry(mock_redis, namespace="test:session", ttl_seconds=3600)


@pytest.mark.unit
class TestRedisSessionRegistryInitialization:
    """Tests for RedisAgentSessionRegistry initialization."""

    def test_initialization_with_defaults(self, mock_redis: AsyncMock):
        """Test registry initializes with default namespace and TTL."""
        registry = RedisAgentSessionRegistry(mock_redis)

        assert registry._redis is mock_redis
        assert registry._namespace == "agent:session"
        assert registry._ttl == 86400  # 24 hours

    def test_initialization_with_custom_namespace(self, mock_redis: AsyncMock):
        """Test registry initializes with custom namespace."""
        registry = RedisAgentSessionRegistry(mock_redis, namespace="custom:ns", ttl_seconds=7200)

        assert registry._namespace == "custom:ns"
        assert registry._ttl == 7200

    def test_initialization_with_custom_ttl(self, mock_redis: AsyncMock):
        """Test registry initializes with custom TTL."""
        registry = RedisAgentSessionRegistry(mock_redis, namespace="test:session", ttl_seconds=1800)

        assert registry._ttl == 1800


@pytest.mark.unit
class TestRedisSessionRegistryKeyNaming:
    """Tests for key naming conventions."""

    def test_session_key_format(self, registry: RedisAgentSessionRegistry):
        """Test session key format."""
        key = registry._session_key("proj-1", "conv-1")

        assert key == "test:session:proj-1:conv-1"

    def test_project_index_key_format(self, registry: RedisAgentSessionRegistry):
        """Test project index key format."""
        key = registry._project_index_key("proj-1")

        assert key == "test:session:project:proj-1"

    def test_compound_member_format(self):
        """Test compound member format for set members."""
        member = RedisAgentSessionRegistry._compound_member("proj-1", "conv-1")

        assert member == "proj-1:conv-1"

    def test_session_key_with_different_project_ids(self, registry: RedisAgentSessionRegistry):
        """Test session keys are different for different projects."""
        key1 = registry._session_key("proj-1", "conv-1")
        key2 = registry._session_key("proj-2", "conv-1")

        assert key1 != key2

    def test_session_key_with_different_conversation_ids(self, registry: RedisAgentSessionRegistry):
        """Test session keys are different for different conversations."""
        key1 = registry._session_key("proj-1", "conv-1")
        key2 = registry._session_key("proj-1", "conv-2")

        assert key1 != key2


@pytest.mark.unit
class TestRedisSessionRegistrySerialization:
    """Tests for serialization and deserialization."""

    def test_serialize_agent_session(self):
        """Test serialization of AgentSession."""
        session = AgentSession(
            agent_id="agent-1",
            conversation_id="conv-1",
            project_id="proj-1",
            registered_at="2026-03-19T10:00:00+00:00",
        )

        serialized = RedisAgentSessionRegistry._serialize(session)

        assert isinstance(serialized, str)
        data = json.loads(serialized)
        assert data["agent_id"] == "agent-1"
        assert data["conversation_id"] == "conv-1"
        assert data["project_id"] == "proj-1"

    def test_deserialize_from_string(self):
        """Test deserialization from string."""
        raw = json.dumps(
            {
                "agent_id": "agent-1",
                "conversation_id": "conv-1",
                "project_id": "proj-1",
                "registered_at": "2026-03-19T10:00:00+00:00",
            }
        )

        session = RedisAgentSessionRegistry._deserialize(raw)

        assert session.agent_id == "agent-1"
        assert session.conversation_id == "conv-1"
        assert session.project_id == "proj-1"

    def test_deserialize_from_bytes(self):
        """Test deserialization from bytes."""
        raw = json.dumps(
            {
                "agent_id": "agent-1",
                "conversation_id": "conv-1",
                "project_id": "proj-1",
                "registered_at": "2026-03-19T10:00:00+00:00",
            }
        ).encode("utf-8")

        session = RedisAgentSessionRegistry._deserialize(raw)

        assert session.agent_id == "agent-1"
        assert session.conversation_id == "conv-1"
        assert session.project_id == "proj-1"

    def test_serialize_deserialize_roundtrip(self):
        """Test that serialize/deserialize roundtrip preserves data."""
        original = AgentSession(
            agent_id="agent-1",
            conversation_id="conv-1",
            project_id="proj-1",
            registered_at="2026-03-19T10:00:00+00:00",
        )

        serialized = RedisAgentSessionRegistry._serialize(original)
        deserialized = RedisAgentSessionRegistry._deserialize(serialized)

        assert deserialized.agent_id == original.agent_id
        assert deserialized.conversation_id == original.conversation_id
        assert deserialized.project_id == original.project_id
        assert deserialized.registered_at == original.registered_at


@pytest.mark.unit
class TestRedisSessionRegistryRegister:
    """Tests for register() method."""

    async def test_register_success(self, registry: RedisAgentSessionRegistry):
        """Test successful session registration."""
        result = await registry.register("agent-1", "conv-1", "proj-1")

        assert result.agent_id == "agent-1"
        assert result.conversation_id == "conv-1"
        assert result.project_id == "proj-1"
        assert result.registered_at is not None

    async def test_register_calls_redis_pipeline(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test that register uses Redis pipeline."""
        await registry.register("agent-1", "conv-1", "proj-1")

        # Verify pipeline was created
        mock_redis.pipeline.assert_called_once()
        # Verify pipeline execute was called
        pipe = mock_redis.pipeline.return_value
        pipe.execute.assert_called_once()

    async def test_register_calls_setex(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test that register calls setex with correct parameters."""
        await registry.register("agent-1", "conv-1", "proj-1")

        pipe = mock_redis.pipeline.return_value
        calls = pipe.setex.call_args_list
        assert len(calls) > 0
        key, ttl, _ = calls[0][0]
        assert key == "test:session:proj-1:conv-1"
        assert ttl == 3600

    async def test_register_calls_sadd(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test that register calls sadd for project index."""
        await registry.register("agent-1", "conv-1", "proj-1")

        pipe = mock_redis.pipeline.return_value
        # Check that sadd was called with index key and member
        calls = pipe.sadd.call_args_list
        assert len(calls) > 0
        index_key, member = calls[0][0]
        assert index_key == "test:session:project:proj-1"
        assert member == "proj-1:conv-1"

    async def test_register_returns_session_on_redis_error(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test that register returns session even when Redis fails."""
        # Make pipeline.execute raise an error
        pipe = mock_redis.pipeline.return_value
        pipe.execute.side_effect = Exception("Redis error")

        result = await registry.register("agent-1", "conv-1", "proj-1")

        # Should still return the session object
        assert result.agent_id == "agent-1"
        assert result.conversation_id == "conv-1"
        assert result.project_id == "proj-1"


@pytest.mark.unit
class TestRedisSessionRegistryUnregister:
    """Tests for unregister() method."""

    async def test_unregister_success(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test successful session unregistration."""
        session_data = {
            "agent_id": "agent-1",
            "conversation_id": "conv-1",
            "project_id": "proj-1",
            "registered_at": "2026-03-19T10:00:00+00:00",
        }
        serialized = json.dumps(session_data)
        mock_redis.get.return_value = serialized

        result = await registry.unregister("conv-1", "proj-1")

        assert result is not None
        assert result.agent_id == "agent-1"
        assert result.conversation_id == "conv-1"

    async def test_unregister_returns_none_when_not_found(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test unregister returns None when session not found."""
        mock_redis.get.return_value = None

        result = await registry.unregister("conv-1", "proj-1")

        assert result is None

    async def test_unregister_calls_delete(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test that unregister calls delete."""
        session_data = {
            "agent_id": "agent-1",
            "conversation_id": "conv-1",
            "project_id": "proj-1",
            "registered_at": "2026-03-19T10:00:00+00:00",
        }
        serialized = json.dumps(session_data)
        mock_redis.get.return_value = serialized

        await registry.unregister("conv-1", "proj-1")

        pipe = mock_redis.pipeline.return_value
        calls = pipe.delete.call_args_list
        assert len(calls) > 0
        assert calls[0][0][0] == "test:session:proj-1:conv-1"

    async def test_unregister_calls_srem(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test that unregister calls srem."""
        session_data = {
            "agent_id": "agent-1",
            "conversation_id": "conv-1",
            "project_id": "proj-1",
            "registered_at": "2026-03-19T10:00:00+00:00",
        }
        serialized = json.dumps(session_data)
        mock_redis.get.return_value = serialized

        await registry.unregister("conv-1", "proj-1")

        pipe = mock_redis.pipeline.return_value
        calls = pipe.srem.call_args_list
        assert len(calls) > 0
        index_key, member = calls[0][0]
        assert index_key == "test:session:project:proj-1"
        assert member == "proj-1:conv-1"

    async def test_unregister_returns_none_on_redis_error(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test that unregister returns None when Redis fails."""
        mock_redis.get.side_effect = Exception("Redis error")

        result = await registry.unregister("conv-1", "proj-1")

        assert result is None


@pytest.mark.unit
class TestRedisSessionRegistryGetSession:
    """Tests for get_session_for_conversation() method."""

    async def test_get_session_success(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test successful session retrieval."""
        session_data = {
            "agent_id": "agent-1",
            "conversation_id": "conv-1",
            "project_id": "proj-1",
            "registered_at": "2026-03-19T10:00:00+00:00",
        }
        serialized = json.dumps(session_data)
        mock_redis.get.return_value = serialized

        result = await registry.get_session_for_conversation("conv-1", "proj-1")

        assert result is not None
        assert result.agent_id == "agent-1"
        assert result.conversation_id == "conv-1"

    async def test_get_session_returns_none_when_not_found(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test get_session returns None when session not found."""
        mock_redis.get.return_value = None

        result = await registry.get_session_for_conversation("conv-1", "proj-1")

        assert result is None

    async def test_get_session_with_correct_key(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test that get_session uses correct Redis key."""
        mock_redis.get.return_value = None

        await registry.get_session_for_conversation("conv-1", "proj-1")

        mock_redis.get.assert_called_once_with("test:session:proj-1:conv-1")

    async def test_get_session_returns_none_on_redis_error(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test that get_session returns None when Redis fails."""
        mock_redis.get.side_effect = Exception("Redis error")

        result = await registry.get_session_for_conversation("conv-1", "proj-1")

        assert result is None

    async def test_get_session_handles_bytes_response(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test that get_session handles bytes response from Redis."""
        session_data = {
            "agent_id": "agent-1",
            "conversation_id": "conv-1",
            "project_id": "proj-1",
            "registered_at": "2026-03-19T10:00:00+00:00",
        }
        serialized = json.dumps(session_data).encode("utf-8")
        mock_redis.get.return_value = serialized

        result = await registry.get_session_for_conversation("conv-1", "proj-1")

        assert result is not None
        assert result.agent_id == "agent-1"


@pytest.mark.unit
class TestRedisSessionRegistryGetSessions:
    """Tests for get_sessions() method."""

    async def test_get_sessions_empty_project(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test get_sessions returns empty list for project with no sessions."""
        mock_redis.smembers.return_value = set()

        result = await registry.get_sessions("proj-1")

        assert result == []

    async def test_get_sessions_single_session(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test get_sessions returns single session."""
        mock_redis.smembers.return_value = {"proj-1:conv-1"}
        session_data = {
            "agent_id": "agent-1",
            "conversation_id": "conv-1",
            "project_id": "proj-1",
            "registered_at": "2026-03-19T10:00:00+00:00",
        }
        mock_redis.get.return_value = json.dumps(session_data)

        result = await registry.get_sessions("proj-1")

        assert len(result) == 1
        assert result[0].agent_id == "agent-1"

    async def test_get_sessions_multiple_sessions(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test get_sessions returns multiple sessions."""
        mock_redis.smembers.return_value = {"proj-1:conv-1", "proj-1:conv-2"}
        session_data_1 = {
            "agent_id": "agent-1",
            "conversation_id": "conv-1",
            "project_id": "proj-1",
            "registered_at": "2026-03-19T10:00:00+00:00",
        }
        session_data_2 = {
            "agent_id": "agent-2",
            "conversation_id": "conv-2",
            "project_id": "proj-1",
            "registered_at": "2026-03-19T10:00:00+00:00",
        }
        mock_redis.get.side_effect = [
            json.dumps(session_data_1),
            json.dumps(session_data_2),
        ]

        result = await registry.get_sessions("proj-1")

        assert len(result) == 2
        agent_ids = {s.agent_id for s in result}
        assert agent_ids == {"agent-1", "agent-2"}

    async def test_get_sessions_handles_bytes_members(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test get_sessions handles bytes members from Redis."""
        mock_redis.smembers.return_value = {b"proj-1:conv-1"}
        session_data = {
            "agent_id": "agent-1",
            "conversation_id": "conv-1",
            "project_id": "proj-1",
            "registered_at": "2026-03-19T10:00:00+00:00",
        }
        mock_redis.get.return_value = json.dumps(session_data)

        result = await registry.get_sessions("proj-1")

        assert len(result) == 1
        assert result[0].agent_id == "agent-1"

    async def test_get_sessions_skips_invalid_members(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test get_sessions skips malformed members."""
        # Member without colon separator
        mock_redis.smembers.return_value = {
            "proj-1:conv-1",
            "invalid_member",
            "proj-1:conv-2",
        }
        session_data = {
            "agent_id": "agent-1",
            "conversation_id": "conv-1",
            "project_id": "proj-1",
            "registered_at": "2026-03-19T10:00:00+00:00",
        }
        mock_redis.get.side_effect = [json.dumps(session_data), json.dumps(session_data)]

        result = await registry.get_sessions("proj-1")

        # Should only include valid members
        assert len(result) == 2

    async def test_get_sessions_returns_empty_on_redis_error(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test get_sessions returns empty list when Redis fails."""
        mock_redis.smembers.side_effect = Exception("Redis error")

        result = await registry.get_sessions("proj-1")

        assert result == []


@pytest.mark.unit
class TestRedisSessionRegistryGetActiveAgentIds:
    """Tests for get_active_agent_ids() method."""

    async def test_get_active_agent_ids_empty(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test get_active_agent_ids returns empty set for project with no sessions."""
        mock_redis.smembers.return_value = set()

        result = await registry.get_active_agent_ids("proj-1")

        assert result == set()

    async def test_get_active_agent_ids_single_agent(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test get_active_agent_ids returns single agent ID."""
        mock_redis.smembers.return_value = {"proj-1:conv-1"}
        session_data = {
            "agent_id": "agent-1",
            "conversation_id": "conv-1",
            "project_id": "proj-1",
            "registered_at": "2026-03-19T10:00:00+00:00",
        }
        mock_redis.get.return_value = json.dumps(session_data)

        result = await registry.get_active_agent_ids("proj-1")

        assert result == {"agent-1"}

    async def test_get_active_agent_ids_multiple_agents(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test get_active_agent_ids returns multiple agent IDs."""
        mock_redis.smembers.return_value = {"proj-1:conv-1", "proj-1:conv-2"}
        session_data_1 = {
            "agent_id": "agent-1",
            "conversation_id": "conv-1",
            "project_id": "proj-1",
            "registered_at": "2026-03-19T10:00:00+00:00",
        }
        session_data_2 = {
            "agent_id": "agent-2",
            "conversation_id": "conv-2",
            "project_id": "proj-1",
            "registered_at": "2026-03-19T10:00:00+00:00",
        }
        mock_redis.get.side_effect = [
            json.dumps(session_data_1),
            json.dumps(session_data_2),
        ]

        result = await registry.get_active_agent_ids("proj-1")

        assert result == {"agent-1", "agent-2"}

    async def test_get_active_agent_ids_duplicate_agents(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test get_active_agent_ids deduplicates agent IDs."""
        mock_redis.smembers.return_value = {"proj-1:conv-1", "proj-1:conv-2"}
        session_data = {
            "agent_id": "agent-1",
            "conversation_id": "conv-1",
            "project_id": "proj-1",
            "registered_at": "2026-03-19T10:00:00+00:00",
        }
        # Same agent for both conversations
        mock_redis.get.side_effect = [json.dumps(session_data), json.dumps(session_data)]

        result = await registry.get_active_agent_ids("proj-1")

        # Should only have one entry due to set deduplication
        assert result == {"agent-1"}


@pytest.mark.unit
class TestRedisSessionRegistryClearProject:
    """Tests for clear_project() method."""

    async def test_clear_project_empty(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test clear_project returns 0 for project with no sessions."""
        mock_redis.smembers.return_value = set()

        result = await registry.clear_project("proj-1")

        assert result == 0

    async def test_clear_project_single_session(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test clear_project deletes single session."""
        mock_redis.smembers.return_value = {"proj-1:conv-1"}

        result = await registry.clear_project("proj-1")

        assert result == 1
        pipe = mock_redis.pipeline.return_value
        # Should delete session key and index key
        assert pipe.delete.call_count >= 2

    async def test_clear_project_multiple_sessions(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test clear_project deletes multiple sessions."""
        mock_redis.smembers.return_value = {"proj-1:conv-1", "proj-1:conv-2"}

        result = await registry.clear_project("proj-1")

        assert result == 2

    async def test_clear_project_calls_delete_for_each_session(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test clear_project deletes each session key."""
        mock_redis.smembers.return_value = {"proj-1:conv-1", "proj-1:conv-2"}

        await registry.clear_project("proj-1")

        pipe = mock_redis.pipeline.return_value
        # Check that delete was called for session keys
        delete_calls = [call[0][0] for call in pipe.delete.call_args_list]
        assert "test:session:proj-1:conv-1" in delete_calls
        assert "test:session:proj-1:conv-2" in delete_calls

    async def test_clear_project_deletes_index_key(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test clear_project deletes the project index key."""
        mock_redis.smembers.return_value = {"proj-1:conv-1"}

        await registry.clear_project("proj-1")

        pipe = mock_redis.pipeline.return_value
        delete_calls = [call[0][0] for call in pipe.delete.call_args_list]
        # Should delete the project index key
        assert "test:session:project:proj-1" in delete_calls

    async def test_clear_project_skips_invalid_members(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test clear_project skips malformed members."""
        mock_redis.smembers.return_value = {
            "proj-1:conv-1",
            "invalid_member",
            "proj-1:conv-2",
        }

        result = await registry.clear_project("proj-1")

        # Should only count valid members
        assert result == 2

    async def test_clear_project_returns_zero_on_redis_error(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test clear_project returns 0 when Redis fails."""
        mock_redis.smembers.side_effect = Exception("Redis error")

        result = await registry.clear_project("proj-1")

        assert result == 0

    async def test_clear_project_handles_bytes_members(
        self, registry: RedisAgentSessionRegistry, mock_redis: AsyncMock
    ):
        """Test clear_project handles bytes members from Redis."""
        mock_redis.smembers.return_value = {b"proj-1:conv-1", b"proj-1:conv-2"}

        result = await registry.clear_project("proj-1")

        assert result == 2
