"""Unit tests for the AgentExecution domain entity."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.domain.model.agent import (
    AgentExecution,
    ExecutionStatus,
)


class TestAgentExecution:
    """Test AgentExecution domain entity behavior."""

    def test_create_execution(self):
        """Test creating an agent execution."""
        execution = AgentExecution(
            id="exec-1",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.THINKING,
            started_at=datetime.now(ZoneInfo("UTC")),
        )

        assert execution.id == "exec-1"
        assert execution.conversation_id == "conv-1"
        assert execution.message_id == "msg-1"
        assert execution.status == ExecutionStatus.THINKING
        assert execution.thought is None
        assert execution.action is None
        assert execution.observation is None
        assert execution.tool_name is None
        assert execution.tool_input == {}
        assert execution.tool_output is None
        assert execution.metadata == {}

    def test_mark_completed(self):
        """Test marking execution as completed."""
        execution = AgentExecution(
            id="exec-1",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.THINKING,
            started_at=datetime.now(ZoneInfo("UTC")),
        )

        assert execution.completed_at is None

        execution.mark_completed()

        assert execution.status == ExecutionStatus.COMPLETED
        assert isinstance(execution.completed_at, datetime)

    def test_mark_failed(self):
        """Test marking execution as failed."""
        execution = AgentExecution(
            id="exec-1",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.THINKING,
            started_at=datetime.now(ZoneInfo("UTC")),
        )

        error_msg = "LLM API error"
        execution.mark_failed(error_msg)

        assert execution.status == ExecutionStatus.FAILED
        assert isinstance(execution.completed_at, datetime)
        assert execution.metadata.get("error") == error_msg

    def test_set_thinking(self):
        """Test setting execution to thinking state."""
        execution = AgentExecution(
            id="exec-1",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.ACTING,
            started_at=datetime.now(ZoneInfo("UTC")),
        )

        thought = "I need to search the knowledge graph for relevant information."
        execution.set_thinking(thought)

        assert execution.status == ExecutionStatus.THINKING
        assert execution.thought == thought

    def test_set_acting(self):
        """Test setting execution to acting state."""
        execution = AgentExecution(
            id="exec-1",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.THINKING,
            started_at=datetime.now(ZoneInfo("UTC")),
        )

        tool_name = "memory_search"
        tool_input = {"query": "test query"}

        execution.set_acting(tool_name, tool_input)

        assert execution.status == ExecutionStatus.ACTING
        assert execution.action == "call_memory_search"
        assert execution.tool_name == tool_name
        assert execution.tool_input == tool_input

    def test_set_observing(self):
        """Test setting execution to observing state."""
        execution = AgentExecution(
            id="exec-1",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.ACTING,
            started_at=datetime.now(ZoneInfo("UTC")),
        )

        observation = "Found 3 relevant memories in the knowledge graph."
        tool_output = "Raw tool output here"
        execution.set_observing(observation, tool_output)

        assert execution.status == ExecutionStatus.OBSERVING
        assert execution.observation == observation
        assert execution.tool_output == tool_output

    def test_duration_ms_completed(self):
        """Test duration_ms property for completed execution."""
        started_at = datetime.now(ZoneInfo("UTC"))
        completed_at = started_at + timedelta(seconds=5)

        execution = AgentExecution(
            id="exec-1",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.COMPLETED,
            started_at=started_at,
            completed_at=completed_at,
        )

        duration = execution.duration_ms
        assert duration is not None
        assert 4900 <= duration <= 5100  # Allow for small timing variations

    def test_duration_ms_incomplete(self):
        """Test duration_ms property for incomplete execution."""
        execution = AgentExecution(
            id="exec-1",
            conversation_id="conv-1",
            message_id="msg-1",
            status=ExecutionStatus.THINKING,
            started_at=datetime.now(ZoneInfo("UTC")),
        )

        # Incomplete execution should return None
        duration = execution.duration_ms
        assert duration is None
