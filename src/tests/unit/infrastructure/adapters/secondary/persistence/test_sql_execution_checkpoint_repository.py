"""
Tests for V2 SqlExecutionCheckpointRepository using BaseRepository.

TDD Approach: RED -> GREEN -> REFACTOR
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import ExecutionCheckpoint
from src.infrastructure.adapters.secondary.persistence.models import (
    ExecutionCheckpoint as DBExecutionCheckpoint,
)
from src.infrastructure.adapters.secondary.persistence.sql_execution_checkpoint_repository import (
    SqlExecutionCheckpointRepository,
)


@pytest.fixture
async def v2_checkpoint_repo(v2_db_session: AsyncSession) -> SqlExecutionCheckpointRepository:
    """Create a V2 execution checkpoint repository for testing."""
    return SqlExecutionCheckpointRepository(v2_db_session)


class TestSqlExecutionCheckpointRepositoryCreate:
    """Tests for creating checkpoints."""

    @pytest.mark.asyncio
    async def test_save_new_checkpoint(self, v2_checkpoint_repo: SqlExecutionCheckpointRepository):
        """Test saving a new checkpoint."""
        checkpoint = ExecutionCheckpoint(
            id="ckpt-test-1",
            conversation_id="conv-1",
            message_id="msg-1",
            checkpoint_type="llm_complete",
            execution_state={"step": 1, "data": "test"},
            step_number=1,
            created_at=datetime.now(UTC),
        )

        await v2_checkpoint_repo.save(checkpoint)

        # Verify checkpoint was saved
        retrieved = await v2_checkpoint_repo.get_latest("conv-1", "msg-1")
        assert retrieved is not None
        assert retrieved.id == "ckpt-test-1"
        assert retrieved.conversation_id == "conv-1"
        assert retrieved.message_id == "msg-1"
        assert retrieved.checkpoint_type == "llm_complete"
        assert retrieved.execution_state == {"step": 1, "data": "test"}

    @pytest.mark.asyncio
    async def test_save_without_message_id(self, v2_checkpoint_repo: SqlExecutionCheckpointRepository):
        """Test saving a checkpoint without message_id."""
        checkpoint = ExecutionCheckpoint(
            id="ckpt-no-msg-1",
            conversation_id="conv-1",
            message_id=None,
            checkpoint_type="tool_start",
            execution_state={"tool": "search"},
            step_number=None,
            created_at=datetime.now(UTC),
        )

        await v2_checkpoint_repo.save(checkpoint)

        retrieved = await v2_checkpoint_repo.get_latest("conv-1")
        assert retrieved is not None
        assert retrieved.message_id is None


class TestSqlExecutionCheckpointRepositoryFind:
    """Tests for finding checkpoints."""

    @pytest.mark.asyncio
    async def test_get_latest(self, v2_checkpoint_repo: SqlExecutionCheckpointRepository):
        """Test getting the latest checkpoint for a conversation."""
        # Create multiple checkpoints
        for i in range(3):
            checkpoint = ExecutionCheckpoint(
                id=f"ckpt-latest-{i}",
                conversation_id="conv-latest",
                message_id="msg-1",
                checkpoint_type="test",
                execution_state={"index": i},
                step_number=i,
                created_at=datetime.now(UTC),
            )
            await v2_checkpoint_repo.save(checkpoint)

        retrieved = await v2_checkpoint_repo.get_latest("conv-latest", "msg-1")
        assert retrieved is not None
        assert retrieved.execution_state == {"index": 2}

    @pytest.mark.asyncio
    async def test_get_latest_none_when_empty(self, v2_checkpoint_repo: SqlExecutionCheckpointRepository):
        """Test getting latest checkpoint returns None when no checkpoints exist."""
        retrieved = await v2_checkpoint_repo.get_latest("conv-empty")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_by_type(self, v2_checkpoint_repo: SqlExecutionCheckpointRepository):
        """Test getting checkpoints of a specific type."""
        # Create checkpoints with different types
        for checkpoint_type in ["llm_complete", "tool_start", "tool_complete"]:
            checkpoint = ExecutionCheckpoint(
                id=f"ckpt-type-{checkpoint_type}",
                conversation_id="conv-type",
                message_id="msg-1",
                checkpoint_type=checkpoint_type,
                execution_state={"type": checkpoint_type},
                step_number=1,
                created_at=datetime.now(UTC),
            )
            await v2_checkpoint_repo.save(checkpoint)

        # Get only llm_complete checkpoints
        llm_checkpoints = await v2_checkpoint_repo.get_by_type("conv-type", "llm_complete")
        assert len(llm_checkpoints) == 1
        assert llm_checkpoints[0].checkpoint_type == "llm_complete"

    @pytest.mark.asyncio
    async def test_get_by_type_with_limit(self, v2_checkpoint_repo: SqlExecutionCheckpointRepository):
        """Test getting checkpoints with a limit."""
        # Create 5 checkpoints
        for i in range(5):
            checkpoint = ExecutionCheckpoint(
                id=f"ckpt-limit-{i}",
                conversation_id="conv-limit",
                message_id="msg-1",
                checkpoint_type="test",
                execution_state={"index": i},
                step_number=i,
                created_at=datetime.now(UTC),
            )
            await v2_checkpoint_repo.save(checkpoint)

        # Get with limit
        checkpoints = await v2_checkpoint_repo.get_by_type("conv-limit", "test", limit=3)
        assert len(checkpoints) == 3


class TestSqlExecutionCheckpointRepositoryDelete:
    """Tests for deleting checkpoints."""

    @pytest.mark.asyncio
    async def test_delete_by_conversation(self, v2_checkpoint_repo: SqlExecutionCheckpointRepository):
        """Test deleting all checkpoints for a conversation."""
        # Create checkpoints
        for i in range(3):
            checkpoint = ExecutionCheckpoint(
                id=f"ckpt-del-{i}",
                conversation_id="conv-del",
                message_id=f"msg-{i}",
                checkpoint_type="test",
                execution_state={},
                step_number=None,
                created_at=datetime.now(UTC),
            )
            await v2_checkpoint_repo.save(checkpoint)

        # Delete all for conversation
        await v2_checkpoint_repo.delete_by_conversation("conv-del")

        # Verify all deleted
        retrieved = await v2_checkpoint_repo.get_latest("conv-del")
        assert retrieved is None


class TestSqlExecutionCheckpointRepositoryToDomain:
    """Tests for _to_domain conversion."""

    def test_to_domain_with_none(self, v2_checkpoint_repo: SqlExecutionCheckpointRepository):
        """Test that _to_domain returns None for None input."""
        result = v2_checkpoint_repo._to_domain(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_to_domain_handles_empty_state(self, v2_checkpoint_repo: SqlExecutionCheckpointRepository):
        """Test that _to_domain handles empty execution_state."""
        checkpoint = ExecutionCheckpoint(
            id="ckpt-empty-state",
            conversation_id="conv-1",
            message_id="msg-1",
            checkpoint_type="test",
            execution_state=None,
            step_number=None,
            created_at=datetime.now(UTC),
        )
        await v2_checkpoint_repo.save(checkpoint)

        retrieved = await v2_checkpoint_repo.get_latest("conv-1")
        assert retrieved is not None
        assert retrieved.execution_state == {} or retrieved.execution_state is None


class TestSqlExecutionCheckpointRepositoryToDb:
    """Tests for _to_db conversion."""

    def test_to_db_creates_db_model(self, v2_checkpoint_repo: SqlExecutionCheckpointRepository):
        """Test that _to_db creates a valid DB model."""
        checkpoint = ExecutionCheckpoint(
            id="ckpt-todb-1",
            conversation_id="conv-1",
            message_id="msg-1",
            checkpoint_type="test",
            execution_state={"test": "data"},
            step_number=1,
            created_at=datetime.now(UTC),
        )

        db_model = v2_checkpoint_repo._to_db(checkpoint)
        assert isinstance(db_model, DBExecutionCheckpoint)
        assert db_model.id == "ckpt-todb-1"
        assert db_model.conversation_id == "conv-1"
        assert db_model.checkpoint_type == "test"
