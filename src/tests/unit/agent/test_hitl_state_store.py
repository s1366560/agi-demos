"""
Unit tests for HITL State Store.

Tests the Redis-based state persistence for Agent pause/resume.
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.hitl.state_store import (
    HITLAgentState,
    HITLStateStore,
)


@pytest.mark.unit
class TestHITLAgentState:
    """Test HITLAgentState dataclass."""

    def test_create_state(self):
        """Test creating HITLAgentState with required fields."""
        state = HITLAgentState(
            conversation_id="conv-123",
            message_id="msg-456",
            tenant_id="tenant-1",
            project_id="project-1",
            hitl_request_id="clarif_abc",
            hitl_type="clarification",
            hitl_request_data={"question": "Which approach?"},
            messages=[{"role": "user", "content": "Hello"}],
            user_message="Hello",
            user_id="user-1",
        )

        assert state.conversation_id == "conv-123"
        assert state.message_id == "msg-456"
        assert state.tenant_id == "tenant-1"
        assert state.project_id == "project-1"
        assert state.hitl_request_id == "clarif_abc"
        assert state.hitl_type == "clarification"
        assert state.step_count == 0
        assert state.timeout_seconds == 300.0

    def test_state_with_optional_fields(self):
        """Test state with optional fields."""
        state = HITLAgentState(
            conversation_id="conv-789",
            message_id="msg-xyz",
            tenant_id="tenant-2",
            project_id="project-2",
            hitl_request_id="decision_123",
            hitl_type="decision",
            hitl_request_data={},
            messages=[],
            user_message="Test",
            user_id="user-2",
            step_count=5,
            timeout_seconds=600.0,
        )

        assert state.step_count == 5
        assert state.timeout_seconds == 600.0

    def test_to_dict(self):
        """Test state serialization to dict."""
        state = HITLAgentState(
            conversation_id="conv-dict",
            message_id="msg-dict",
            tenant_id="tenant-dict",
            project_id="project-dict",
            hitl_request_id="test_123",
            hitl_type="env_var",
            hitl_request_data={"tool_name": "github"},
            messages=[{"role": "user", "content": "Test"}],
            user_message="Test",
            user_id="user-dict",
            step_count=3,
        )

        data = state.to_dict()

        assert data["conversation_id"] == "conv-dict"
        assert data["hitl_type"] == "env_var"
        assert data["step_count"] == 3
        assert "created_at" in data

    def test_from_dict(self):
        """Test state deserialization from dict."""
        data = {
            "conversation_id": "conv-from",
            "message_id": "msg-from",
            "tenant_id": "tenant-from",
            "project_id": "project-from",
            "hitl_request_id": "perm_456",
            "hitl_type": "permission",
            "hitl_request_data": {"action": "write"},
            "messages": [{"role": "assistant", "content": "Sure"}],
            "user_message": "Can you write?",
            "user_id": "user-from",
            "step_count": 7,
            "timeout_seconds": 120.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        state = HITLAgentState.from_dict(data)

        assert state.conversation_id == "conv-from"
        assert state.hitl_type == "permission"
        assert state.step_count == 7
        assert state.timeout_seconds == 120.0

    def test_roundtrip_serialization(self):
        """Test that to_dict/from_dict roundtrip preserves data."""
        original = HITLAgentState(
            conversation_id="conv-round",
            message_id="msg-round",
            tenant_id="tenant-round",
            project_id="project-round",
            hitl_request_id="round_789",
            hitl_type="clarification",
            hitl_request_data={"question": "Test?", "options": ["A", "B"]},
            messages=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
            ],
            user_message="Hello",
            user_id="user-round",
            step_count=10,
            timeout_seconds=180.0,
        )

        data = original.to_dict()
        restored = HITLAgentState.from_dict(data)

        assert restored.conversation_id == original.conversation_id
        assert restored.hitl_request_id == original.hitl_request_id
        assert restored.step_count == original.step_count
        assert restored.messages == original.messages


@pytest.mark.unit
class TestHITLStateStore:
    """Test HITLStateStore Redis operations."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis = AsyncMock()
        redis.setex = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=None)
        redis.delete = AsyncMock(return_value=1)
        return redis

    @pytest.fixture
    def state_store(self, mock_redis):
        """Create HITLStateStore with mock Redis."""
        return HITLStateStore(mock_redis)

    @pytest.fixture
    def sample_state(self):
        """Create sample HITLAgentState."""
        return HITLAgentState(
            conversation_id="conv-sample",
            message_id="msg-sample",
            tenant_id="tenant-sample",
            project_id="project-sample",
            hitl_request_id="sample_123",
            hitl_type="clarification",
            hitl_request_data={"question": "Test question?"},
            messages=[{"role": "user", "content": "Test"}],
            user_message="Test",
            user_id="user-sample",
        )

    async def test_save_state(self, state_store, mock_redis, sample_state):
        """Test saving state to Redis."""
        key = await state_store.save_state(sample_state)

        # Check key format - now uses request_id instead of message_id
        assert key.startswith("hitl:agent_state:")
        assert "conv-sample" in key
        assert "sample_123" in key  # request_id, not message_id

        # Check Redis was called
        assert mock_redis.setex.called

    async def test_load_state_found(self, state_store, mock_redis, sample_state):
        """Test loading existing state from Redis."""
        # Setup mock to return serialized state
        mock_redis.get.return_value = json.dumps(sample_state.to_dict())

        loaded = await state_store.load_state("hitl:agent_state:conv-sample:sample_123")

        assert loaded is not None
        assert loaded.conversation_id == "conv-sample"
        assert loaded.hitl_request_id == "sample_123"

    async def test_load_state_not_found(self, state_store, mock_redis):
        """Test loading non-existent state."""
        mock_redis.get.return_value = None

        loaded = await state_store.load_state("hitl:agent_state:nonexistent:key")

        assert loaded is None

    async def test_load_state_by_request(self, state_store, mock_redis, sample_state):
        """Test loading state by request ID."""
        # Setup mock to return the main key, then the state
        mock_redis.get.side_effect = [
            "hitl:agent_state:conv-sample:sample_123",  # First call returns the key
            json.dumps(sample_state.to_dict()),  # Second call returns the state
        ]

        loaded = await state_store.load_state_by_request("sample_123")

        assert loaded is not None
        assert loaded.hitl_request_id == "sample_123"

    async def test_delete_state(self, state_store, mock_redis):
        """Test deleting state from Redis."""
        result = await state_store.delete_state("hitl:agent_state:conv-del:req-del")

        assert result is True
        assert mock_redis.delete.called

    async def test_key_generation(self, state_store, sample_state):
        """Test that save generates correct keys."""
        # We need to verify that both main key and request key are set
        redis = state_store._redis
        
        await state_store.save_state(sample_state)

        # Should have called setex twice (main key + request key)
        assert redis.setex.call_count == 2
