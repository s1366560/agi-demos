"""
Tests for V2 SqlMessageExecutionStatusRepository using BaseRepository.
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.execution_status import AgentExecution, AgentExecutionStatus
from src.infrastructure.adapters.secondary.persistence.v2_sql_message_execution_status_repository import (
    V2SqlMessageExecutionStatusRepository,
)


@pytest.fixture
async def v2_msg_exec_status_repo(v2_db_session: AsyncSession) -> V2SqlMessageExecutionStatusRepository:
    """Create a V2 message execution status repository for testing."""
    return V2SqlMessageExecutionStatusRepository(v2_db_session)


def make_agent_execution(
    execution_id: str,
    conversation_id: str,
    message_id: str,
    status: AgentExecutionStatus = AgentExecutionStatus.RUNNING,
) -> AgentExecution:
    """Factory for creating AgentExecution objects."""
    return AgentExecution(
        id=execution_id,
        conversation_id=conversation_id,
        message_id=message_id,
        status=status,
        last_event_sequence=0,
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        error_message=None,
        tenant_id="tenant-1",
        project_id="project-1",
    )


class TestV2SqlMessageExecutionStatusRepositoryCreate:
    """Tests for creating execution status records."""

    @pytest.mark.asyncio
    async def test_create_new_execution(self, v2_msg_exec_status_repo: V2SqlMessageExecutionStatusRepository):
        """Test creating a new execution status record."""
        execution = make_agent_execution("exec-1", "conv-1", "msg-1")

        result = await v2_msg_exec_status_repo.create(execution)

        assert result.id == "exec-1"
        assert result.status == AgentExecutionStatus.RUNNING


class TestV2SqlMessageExecutionStatusRepositoryFind:
    """Tests for finding execution status records."""

    @pytest.mark.asyncio
    async def test_get_by_id_existing(self, v2_msg_exec_status_repo: V2SqlMessageExecutionStatusRepository):
        """Test getting an execution status by ID."""
        execution = make_agent_execution("exec-find-1", "conv-1", "msg-1")
        await v2_msg_exec_status_repo.create(execution)

        result = await v2_msg_exec_status_repo.get_by_id("exec-find-1")
        assert result is not None
        assert result.message_id == "msg-1"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, v2_msg_exec_status_repo: V2SqlMessageExecutionStatusRepository):
        """Test getting a non-existent execution returns None."""
        result = await v2_msg_exec_status_repo.get_by_id("non-existent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_message_id(self, v2_msg_exec_status_repo: V2SqlMessageExecutionStatusRepository):
        """Test getting execution by message ID."""
        execution = make_agent_execution("exec-msg-1", "conv-1", "msg-find-1")
        await v2_msg_exec_status_repo.create(execution)

        result = await v2_msg_exec_status_repo.get_by_message_id("msg-find-1")
        assert result is not None
        assert result.id == "exec-msg-1"

    @pytest.mark.asyncio
    async def test_get_by_message_id_with_conversation(self, v2_msg_exec_status_repo: V2SqlMessageExecutionStatusRepository):
        """Test getting execution by message ID and conversation."""
        execution1 = make_agent_execution("exec-msg-conv-1", "conv-1", "msg-shared-1")
        execution2 = make_agent_execution("exec-msg-conv-2", "conv-2", "msg-shared-2")
        await v2_msg_exec_status_repo.create(execution1)
        await v2_msg_exec_status_repo.create(execution2)

        result = await v2_msg_exec_status_repo.get_by_message_id("msg-shared-1", "conv-1")
        assert result is not None
        assert result.conversation_id == "conv-1"

    @pytest.mark.asyncio
    async def test_get_running_by_conversation(self, v2_msg_exec_status_repo: V2SqlMessageExecutionStatusRepository):
        """Test getting running execution by conversation."""
        execution = make_agent_execution("exec-running-1", "conv-running-1", "msg-1")
        await v2_msg_exec_status_repo.create(execution)

        result = await v2_msg_exec_status_repo.get_running_by_conversation("conv-running-1")
        assert result is not None
        assert result.status == AgentExecutionStatus.RUNNING


class TestV2SqlMessageExecutionStatusRepositoryUpdate:
    """Tests for updating execution status."""

    @pytest.mark.asyncio
    async def test_update_status_to_completed(self, v2_msg_exec_status_repo: V2SqlMessageExecutionStatusRepository):
        """Test updating status to completed."""
        execution = make_agent_execution("exec-update-1", "conv-1", "msg-1")
        await v2_msg_exec_status_repo.create(execution)

        result = await v2_msg_exec_status_repo.update_status("exec-update-1", AgentExecutionStatus.COMPLETED)
        assert result is not None
        assert result.status == AgentExecutionStatus.COMPLETED
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_update_status_with_error(self, v2_msg_exec_status_repo: V2SqlMessageExecutionStatusRepository):
        """Test updating status with error message."""
        execution = make_agent_execution("exec-error-1", "conv-1", "msg-1")
        await v2_msg_exec_status_repo.create(execution)

        result = await v2_msg_exec_status_repo.update_status(
            "exec-error-1", AgentExecutionStatus.FAILED, "Test error"
        )
        assert result is not None
        assert result.status == AgentExecutionStatus.FAILED
        assert result.error_message == "Test error"

    @pytest.mark.asyncio
    async def test_update_status_nonexistent(self, v2_msg_exec_status_repo: V2SqlMessageExecutionStatusRepository):
        """Test updating status of non-existent execution returns None."""
        result = await v2_msg_exec_status_repo.update_status("non-existent", AgentExecutionStatus.COMPLETED)
        assert result is None

    @pytest.mark.asyncio
    async def test_update_sequence(self, v2_msg_exec_status_repo: V2SqlMessageExecutionStatusRepository):
        """Test updating last event sequence."""
        execution = make_agent_execution("exec-seq-1", "conv-1", "msg-1")
        await v2_msg_exec_status_repo.create(execution)

        result = await v2_msg_exec_status_repo.update_sequence("exec-seq-1", 5)
        assert result is not None
        assert result.last_event_sequence == 5

    @pytest.mark.asyncio
    async def test_update_sequence_only_increments(self, v2_msg_exec_status_repo: V2SqlMessageExecutionStatusRepository):
        """Test that sequence only updates if new value is higher."""
        execution = make_agent_execution("exec-seq-inc-1", "conv-1", "msg-1")
        await v2_msg_exec_status_repo.create(execution)
        await v2_msg_exec_status_repo.update_sequence("exec-seq-inc-1", 5)

        # Try to update to lower value - should not update and return None
        result = await v2_msg_exec_status_repo.update_sequence("exec-seq-inc-1", 3)
        assert result is None  # Should return None when update doesn't happen


class TestV2SqlMessageExecutionStatusRepositoryDelete:
    """Tests for deleting execution status."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, v2_msg_exec_status_repo: V2SqlMessageExecutionStatusRepository):
        """Test deleting an existing execution."""
        execution = make_agent_execution("exec-delete-1", "conv-1", "msg-1")
        await v2_msg_exec_status_repo.create(execution)

        result = await v2_msg_exec_status_repo.delete("exec-delete-1")
        assert result is True

        retrieved = await v2_msg_exec_status_repo.get_by_id("exec-delete-1")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, v2_msg_exec_status_repo: V2SqlMessageExecutionStatusRepository):
        """Test deleting a non-existent execution returns False."""
        result = await v2_msg_exec_status_repo.delete("non-existent")
        assert result is False
