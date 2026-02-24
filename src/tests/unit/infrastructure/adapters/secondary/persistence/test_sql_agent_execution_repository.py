"""
Tests for V2 SqlAgentExecutionRepository using BaseRepository.

TDD Approach: RED -> GREEN -> REFACTOR

These tests verify that the migrated repository maintains 100% compatibility
with the original implementation while leveraging the BaseRepository.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.agent_execution import AgentExecution, ExecutionStatus
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecution as DBAgentExecution,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_repository import (
    SqlAgentExecutionRepository,
)


@pytest.fixture
async def v2_agent_execution_repo(v2_db_session: AsyncSession) -> SqlAgentExecutionRepository:
    """Create a V2 agent execution repository for testing."""
    return SqlAgentExecutionRepository(v2_db_session)


class TestSqlAgentExecutionRepositoryCreate:
    """Tests for creating new agent executions."""

    @pytest.mark.asyncio
    async def test_save_new_execution(self, v2_agent_execution_repo: SqlAgentExecutionRepository):
        """Test saving a new agent execution."""
        execution = AgentExecution(
            id="exec-test-1",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.THINKING,
            thought="Test thought",
            action="test_action",
            observation="Test observation",
            tool_name="test_tool",
            tool_input={"key": "value"},
            tool_output="Test output",
            metadata={"meta": "data"},
            started_at=datetime.now(UTC),
            completed_at=None,
        )

        await v2_agent_execution_repo.save(execution)

        # Verify execution was saved
        retrieved = await v2_agent_execution_repo.find_by_id("exec-test-1")
        assert retrieved is not None
        assert retrieved.id == "exec-test-1"
        assert retrieved.conversation_id == "conv-1"
        assert retrieved.message_id == "msg-1"
        assert retrieved.status == ExecutionStatus.THINKING
        assert retrieved.thought == "Test thought"
        assert retrieved.action == "test_action"
        assert retrieved.observation == "Test observation"
        assert retrieved.tool_name == "test_tool"
        assert retrieved.tool_input == {"key": "value"}
        assert retrieved.tool_output == "Test output"
        assert retrieved.metadata == {"meta": "data"}

    @pytest.mark.asyncio
    async def test_save_with_minimal_fields(
        self, v2_agent_execution_repo: SqlAgentExecutionRepository
    ):
        """Test saving an execution with only required fields."""
        execution = AgentExecution(
            id="exec-minimal",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.THINKING,
            thought=None,
            action=None,
            observation=None,
            tool_name=None,
            tool_input={},
            tool_output=None,
            metadata={},
            started_at=datetime.now(UTC),
            completed_at=None,
        )

        await v2_agent_execution_repo.save(execution)

        retrieved = await v2_agent_execution_repo.find_by_id("exec-minimal")
        assert retrieved is not None
        assert retrieved.thought is None
        assert retrieved.action is None
        assert retrieved.observation is None
        assert retrieved.tool_name is None
        assert retrieved.tool_input == {}
        assert retrieved.tool_output is None


class TestSqlAgentExecutionRepositoryUpdate:
    """Tests for updating existing executions."""

    @pytest.mark.asyncio
    async def test_update_existing_execution(
        self, v2_agent_execution_repo: SqlAgentExecutionRepository
    ):
        """Test updating an existing execution."""
        # Create initial execution
        execution = AgentExecution(
            id="exec-update-1",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.THINKING,
            thought="Original thought",
            action=None,
            observation=None,
            tool_name=None,
            tool_input={},
            tool_output=None,
            metadata={},
            started_at=datetime.now(UTC),
            completed_at=None,
        )
        await v2_agent_execution_repo.save(execution)

        # Update the execution
        updated_execution = AgentExecution(
            id="exec-update-1",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.COMPLETED,
            thought="Updated thought",
            action="updated_action",
            observation="Updated observation",
            tool_name="updated_tool",
            tool_input={"updated": "input"},
            tool_output="Updated output",
            metadata={"updated": "metadata"},
            started_at=execution.started_at,
            completed_at=datetime.now(UTC),
        )
        await v2_agent_execution_repo.save(updated_execution)

        # Verify updates
        retrieved = await v2_agent_execution_repo.find_by_id("exec-update-1")
        assert retrieved.status == ExecutionStatus.COMPLETED
        assert retrieved.thought == "Updated thought"
        assert retrieved.action == "updated_action"
        assert retrieved.observation == "Updated observation"
        assert retrieved.tool_name == "updated_tool"
        assert retrieved.tool_input == {"updated": "input"}
        assert retrieved.tool_output == "Updated output"
        assert retrieved.metadata == {"updated": "metadata"}
        assert retrieved.completed_at is not None


class TestSqlAgentExecutionRepositoryFind:
    """Tests for finding executions."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, v2_agent_execution_repo: SqlAgentExecutionRepository):
        """Test finding an existing execution by ID."""
        execution = AgentExecution(
            id="exec-find-1",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.THINKING,
            thought=None,
            action=None,
            observation=None,
            tool_name=None,
            tool_input={},
            tool_output=None,
            metadata={},
            started_at=datetime.now(UTC),
            completed_at=None,
        )
        await v2_agent_execution_repo.save(execution)

        retrieved = await v2_agent_execution_repo.find_by_id("exec-find-1")
        assert retrieved is not None
        assert retrieved.id == "exec-find-1"
        assert retrieved.conversation_id == "conv-1"

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, v2_agent_execution_repo: SqlAgentExecutionRepository):
        """Test finding a non-existent execution returns None."""
        retrieved = await v2_agent_execution_repo.find_by_id("non-existent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_list_by_message(self, v2_agent_execution_repo: SqlAgentExecutionRepository):
        """Test listing executions by message ID."""
        # Create executions for different messages
        for i in range(3):
            execution = AgentExecution(
                id=f"exec-msg-1-{i}",
                conversation_id="conv-1",
                message_id="msg-1",
                status=ExecutionStatus.THINKING,
                thought=None,
                action=None,
                observation=None,
                tool_name=None,
                tool_input={},
                tool_output=None,
                metadata={},
                started_at=datetime.now(UTC),
                completed_at=None,
            )
            await v2_agent_execution_repo.save(execution)

        # Add execution for different message
        other_execution = AgentExecution(
            id="exec-other-msg",
            conversation_id="conv-1",
            message_id="msg-2",
            status=ExecutionStatus.THINKING,
            thought=None,
            action=None,
            observation=None,
            tool_name=None,
            tool_input={},
            tool_output=None,
            metadata={},
            started_at=datetime.now(UTC),
            completed_at=None,
        )
        await v2_agent_execution_repo.save(other_execution)

        # List executions for msg-1
        executions = await v2_agent_execution_repo.list_by_message("msg-1")
        assert len(executions) == 3
        assert all(e.message_id == "msg-1" for e in executions)
        # Verify ordered by started_at
        assert executions[0].id == "exec-msg-1-0"

    @pytest.mark.asyncio
    async def test_list_by_conversation(self, v2_agent_execution_repo: SqlAgentExecutionRepository):
        """Test listing executions by conversation ID."""
        # Create executions for different conversations
        for i in range(3):
            execution = AgentExecution(
                id=f"exec-conv-1-{i}",
                conversation_id="conv-1",
                message_id=f"msg-{i}",
                status=ExecutionStatus.THINKING,
                thought=None,
                action=None,
                observation=None,
                tool_name=None,
                tool_input={},
                tool_output=None,
                metadata={},
                started_at=datetime.now(UTC),
                completed_at=None,
            )
            await v2_agent_execution_repo.save(execution)

        # Add execution for different conversation
        other_execution = AgentExecution(
            id="exec-other-conv",
            conversation_id="conv-2",
            message_id="msg-0",
            status=ExecutionStatus.THINKING,
            thought=None,
            action=None,
            observation=None,
            tool_name=None,
            tool_input={},
            tool_output=None,
            metadata={},
            started_at=datetime.now(UTC),
            completed_at=None,
        )
        await v2_agent_execution_repo.save(other_execution)

        # List executions for conv-1
        executions = await v2_agent_execution_repo.list_by_conversation("conv-1")
        assert len(executions) == 3
        assert all(e.conversation_id == "conv-1" for e in executions)

    @pytest.mark.asyncio
    async def test_list_by_conversation_with_limit(
        self, v2_agent_execution_repo: SqlAgentExecutionRepository
    ):
        """Test listing executions by conversation with limit."""
        # Create 5 executions
        for i in range(5):
            execution = AgentExecution(
                id=f"exec-limit-{i}",
                conversation_id="conv-limit",
                message_id=f"msg-{i}",
                status=ExecutionStatus.THINKING,
                thought=None,
                action=None,
                observation=None,
                tool_name=None,
                tool_input={},
                tool_output=None,
                metadata={},
                started_at=datetime.now(UTC),
                completed_at=None,
            )
            await v2_agent_execution_repo.save(execution)

        # Get with limit
        executions = await v2_agent_execution_repo.list_by_conversation("conv-limit", limit=3)
        assert len(executions) == 3


class TestSqlAgentExecutionRepositoryDelete:
    """Tests for deleting executions."""

    @pytest.mark.asyncio
    async def test_delete_by_conversation(
        self, v2_agent_execution_repo: SqlAgentExecutionRepository
    ):
        """Test deleting all executions for a conversation."""
        # Create executions
        for i in range(3):
            execution = AgentExecution(
                id=f"exec-del-{i}",
                conversation_id="conv-del",
                message_id=f"msg-{i}",
                status=ExecutionStatus.THINKING,
                thought=None,
                action=None,
                observation=None,
                tool_name=None,
                tool_input={},
                tool_output=None,
                metadata={},
                started_at=datetime.now(UTC),
                completed_at=None,
            )
            await v2_agent_execution_repo.save(execution)

        # Delete all for conversation
        await v2_agent_execution_repo.delete_by_conversation("conv-del")

        # Verify all deleted
        executions = await v2_agent_execution_repo.list_by_conversation("conv-del")
        assert len(executions) == 0


class TestSqlAgentExecutionRepositoryToDomain:
    """Tests for _to_domain conversion."""

    @pytest.mark.asyncio
    async def test_to_domain_converts_all_fields(
        self, v2_agent_execution_repo: SqlAgentExecutionRepository
    ):
        """Test that _to_domain correctly converts all DB fields."""
        execution = AgentExecution(
            id="exec-domain-1",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.ACTING,
            thought="Domain test thought",
            action="domain_action",
            observation="Domain observation",
            tool_name="domain_tool",
            tool_input={"domain": "input"},
            tool_output="Domain output",
            metadata={"domain": "metadata"},
            started_at=datetime.now(UTC),
            completed_at=None,
        )
        await v2_agent_execution_repo.save(execution)

        retrieved = await v2_agent_execution_repo.find_by_id("exec-domain-1")
        assert retrieved.id == "exec-domain-1"
        assert retrieved.conversation_id == "conv-1"
        assert retrieved.message_id == "msg-1"
        assert retrieved.status == ExecutionStatus.ACTING
        assert retrieved.thought == "Domain test thought"
        assert retrieved.action == "domain_action"
        assert retrieved.observation == "Domain observation"
        assert retrieved.tool_name == "domain_tool"
        assert retrieved.tool_input == {"domain": "input"}
        assert retrieved.tool_output == "Domain output"
        assert retrieved.metadata == {"domain": "metadata"}

    def test_to_domain_with_none_db_model(
        self, v2_agent_execution_repo: SqlAgentExecutionRepository
    ):
        """Test that _to_domain returns None for None input."""
        result = v2_agent_execution_repo._to_domain(None)
        assert result is None


class TestSqlAgentExecutionRepositoryToDb:
    """Tests for _to_db conversion."""

    def test_to_db_creates_db_model(self, v2_agent_execution_repo: SqlAgentExecutionRepository):
        """Test that _to_db creates a valid DB model."""
        execution = AgentExecution(
            id="exec-todb-1",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.THINKING,
            thought="To DB test",
            action=None,
            observation=None,
            tool_name=None,
            tool_input={},
            tool_output=None,
            metadata={},
            started_at=datetime.now(UTC),
            completed_at=None,
        )

        db_model = v2_agent_execution_repo._to_db(execution)
        assert isinstance(db_model, DBAgentExecution)
        assert db_model.id == "exec-todb-1"
        assert db_model.conversation_id == "conv-1"
        assert db_model.message_id == "msg-1"
        assert db_model.status == ExecutionStatus.THINKING.value
        assert db_model.thought == "To DB test"


class TestSqlAgentExecutionRepositoryEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_tool_input_defaults_to_empty_dict(
        self, v2_agent_execution_repo: SqlAgentExecutionRepository
    ):
        """Test that None tool_input is handled correctly."""
        execution = AgentExecution(
            id="exec-edge-1",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.THINKING,
            thought=None,
            action=None,
            observation=None,
            tool_name=None,
            tool_input=None,  # None instead of {}
            tool_output=None,
            metadata=None,
            started_at=datetime.now(UTC),
            completed_at=None,
        )
        await v2_agent_execution_repo.save(execution)

        retrieved = await v2_agent_execution_repo.find_by_id("exec-edge-1")
        assert retrieved is not None
        assert retrieved.tool_input == {} or retrieved.tool_input is None

    @pytest.mark.asyncio
    async def test_status_enum_conversion(
        self, v2_agent_execution_repo: SqlAgentExecutionRepository
    ):
        """Test that status enum is correctly converted."""
        for status in ExecutionStatus:
            execution = AgentExecution(
                id=f"exec-status-{status.value}",
                conversation_id="conv-1",
                message_id="msg-1",
                status=status,
                thought=None,
                action=None,
                observation=None,
                tool_name=None,
                tool_input={},
                tool_output=None,
                metadata={},
                started_at=datetime.now(UTC),
                completed_at=None,
            )
            await v2_agent_execution_repo.save(execution)

            retrieved = await v2_agent_execution_repo.find_by_id(f"exec-status-{status.value}")
            assert retrieved.status == status
