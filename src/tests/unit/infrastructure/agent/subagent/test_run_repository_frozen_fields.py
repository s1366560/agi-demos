"""Tests for frozen result field deserialization in SubAgent run repository."""

import pytest

from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus
from src.infrastructure.agent.subagent.run_repository import _deserialize_run


@pytest.mark.unit
class TestDeserializeRunFrozenFields:
    """Test frozen_result_text and frozen_at deserialization."""

    def test_deserialize_run_with_frozen_fields(self) -> None:
        """Test deserializing a run with frozen fields present."""
        # Arrange
        frozen_at_str = "2025-03-19T10:30:45+00:00"
        payload = {
            "run_id": "run-123",
            "conversation_id": "conv-456",
            "subagent_name": "TestAgent",
            "task": "Test task",
            "status": "completed",
            "created_at": "2025-03-19T10:00:00+00:00",
            "started_at": "2025-03-19T10:10:00+00:00",
            "ended_at": "2025-03-19T10:20:00+00:00",
            "summary": "Task completed",
            "error": None,
            "execution_time_ms": 600000,
            "tokens_used": 150,
            "metadata": {},
            "frozen_result_text": "Final answer",
            "frozen_at": frozen_at_str,
        }

        # Act
        run = _deserialize_run(payload)

        # Assert
        assert run is not None
        assert run.frozen_result_text == "Final answer"
        assert run.frozen_at is not None
        assert run.frozen_at.isoformat() == frozen_at_str

    def test_deserialize_run_without_frozen_fields(self) -> None:
        """Test deserializing a run without frozen fields (both None)."""
        # Arrange
        payload = {
            "run_id": "run-789",
            "conversation_id": "conv-abc",
            "subagent_name": "AnotherAgent",
            "task": "Another task",
            "status": "running",
            "created_at": "2025-03-19T09:00:00+00:00",
            "started_at": "2025-03-19T09:10:00+00:00",
            "ended_at": None,
            "summary": None,
            "error": None,
            "execution_time_ms": None,
            "tokens_used": None,
            "metadata": {},
        }

        # Act
        run = _deserialize_run(payload)

        # Assert
        assert run is not None
        assert run.frozen_result_text is None
        assert run.frozen_at is None

    def test_deserialize_run_round_trip_with_frozen(self) -> None:
        """Test round-trip serialization/deserialization with frozen fields."""
        # Arrange - create a COMPLETED run and freeze it
        original = SubAgentRun(
            run_id="round-trip-1",
            conversation_id="conv-rt-1",
            subagent_name="RoundTripAgent",
            task="Round trip test",
            status=SubAgentRunStatus.PENDING,
        )

        # Progress through states: PENDING -> RUNNING -> COMPLETED
        running_run = original.start()
        completed_run = running_run.complete(summary="Task complete", tokens_used=200)

        # Freeze the result
        frozen_run = completed_run.freeze_result("Round trip frozen result")

        # Serialize via to_event_data()
        serialized = frozen_run.to_event_data()

        # Act - deserialize back
        deserialized = _deserialize_run(serialized)

        # Assert - all fields match, including frozen ones
        assert deserialized is not None
        assert deserialized.run_id == frozen_run.run_id
        assert deserialized.conversation_id == frozen_run.conversation_id
        assert deserialized.subagent_name == frozen_run.subagent_name
        assert deserialized.task == frozen_run.task
        assert deserialized.status == frozen_run.status
        assert deserialized.summary == frozen_run.summary
        assert deserialized.tokens_used == frozen_run.tokens_used
        assert deserialized.frozen_result_text == "Round trip frozen result"
        assert deserialized.frozen_at is not None
        assert deserialized.frozen_at.isoformat() == frozen_run.frozen_at.isoformat()

    def test_deserialize_run_round_trip_without_frozen(self) -> None:
        """Test round-trip serialization/deserialization without frozen fields."""
        # Arrange - create a COMPLETED run but don't freeze it
        original = SubAgentRun(
            run_id="round-trip-2",
            conversation_id="conv-rt-2",
            subagent_name="NoFreezeAgent",
            task="No freeze test",
            status=SubAgentRunStatus.PENDING,
        )

        # Progress through states
        running_run = original.start()
        completed_run = running_run.complete(summary="Task done", tokens_used=100)

        # Serialize via to_event_data() (without freezing)
        serialized = completed_run.to_event_data()

        # Act - deserialize back
        deserialized = _deserialize_run(serialized)

        # Assert - frozen fields should be None
        assert deserialized is not None
        assert deserialized.run_id == completed_run.run_id
        assert deserialized.status == SubAgentRunStatus.COMPLETED
        assert deserialized.frozen_result_text is None
        assert deserialized.frozen_at is None
        assert deserialized.summary == "Task done"
        assert deserialized.tokens_used == 100
