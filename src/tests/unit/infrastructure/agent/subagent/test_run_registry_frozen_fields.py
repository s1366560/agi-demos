"""Tests for SubAgentRunRegistry frozen fields serialization/deserialization."""

from datetime import UTC, datetime

import pytest

from src.domain.model.agent.subagent_run import SubAgentRunStatus
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry


@pytest.mark.unit
class TestSubAgentRunRegistryFrozenFields:
    """Test frozen_result_text and frozen_at deserialization."""

    def test_registry_deserialize_run_with_frozen_fields(self) -> None:
        """Test deserialization of run with frozen_result_text and frozen_at."""
        # Arrange
        now = datetime.now(UTC)
        payload = {
            "run_id": "run-123",
            "conversation_id": "conv-456",
            "subagent_name": "researcher",
            "task": "Find references",
            "status": SubAgentRunStatus.COMPLETED.value,
            "created_at": datetime.now(UTC).isoformat(),
            "started_at": datetime.now(UTC).isoformat(),
            "ended_at": datetime.now(UTC).isoformat(),
            "summary": "Completed successfully",
            "metadata": {},
            "frozen_result_text": "Final answer",
            "frozen_at": now.isoformat(),
        }

        # Act
        run = SubAgentRunRegistry._deserialize_run(payload)

        # Assert
        assert run is not None
        assert run.frozen_result_text == "Final answer"
        assert run.frozen_at is not None
        assert run.frozen_at.isoformat() == now.isoformat()

    def test_registry_deserialize_run_without_frozen_fields(self) -> None:
        """Test deserialization of run without frozen fields (should be None)."""
        # Arrange
        payload = {
            "run_id": "run-123",
            "conversation_id": "conv-456",
            "subagent_name": "researcher",
            "task": "Find references",
            "status": SubAgentRunStatus.RUNNING.value,
            "created_at": datetime.now(UTC).isoformat(),
            "metadata": {},
        }

        # Act
        run = SubAgentRunRegistry._deserialize_run(payload)

        # Assert
        assert run is not None
        assert run.frozen_result_text is None
        assert run.frozen_at is None

    def test_registry_round_trip_with_frozen(self) -> None:
        """Test round-trip serialization and deserialization with frozen fields."""
        # Arrange
        registry = SubAgentRunRegistry()
        run = registry.create_run(
            conversation_id="conv-1",
            subagent_name="researcher",
            task="Find references",
            metadata={"source": "delegate"},
        )

        # Act - Complete the run and freeze it
        running = registry.mark_running("conv-1", run.run_id)
        assert running is not None

        completed = registry.mark_completed("conv-1", run.run_id, summary="done")
        assert completed is not None

        frozen = completed.freeze_result("Final answer")

        # Serialize via to_event_data
        event_data = frozen.to_event_data()

        # Deserialize back
        deserialized = SubAgentRunRegistry._deserialize_run(event_data)

        # Assert - all fields including frozen ones match
        assert deserialized is not None
        assert deserialized.frozen_result_text == "Final answer"
        assert deserialized.frozen_at is not None
        assert deserialized.run_id == frozen.run_id
        assert deserialized.conversation_id == frozen.conversation_id
        assert deserialized.subagent_name == frozen.subagent_name
        assert deserialized.task == frozen.task
        assert deserialized.status == frozen.status

    def test_registry_persist_and_load_with_frozen_fields(self, tmp_path) -> None:
        """Test that frozen fields survive persist/load cycle."""
        # Arrange - Create registry with persistence
        persistence_path = tmp_path / "runs.json"
        registry = SubAgentRunRegistry(persistence_path=persistence_path)

        run = registry.create_run(
            conversation_id="conv-1",
            subagent_name="researcher",
            task="Find references",
        )

        # Act - Complete and freeze the run
        running = registry.mark_running("conv-1", run.run_id)
        assert running is not None

        completed = registry.mark_completed("conv-1", run.run_id, summary="done")
        assert completed is not None

        frozen = completed.freeze_result("Final answer")

        # Manually update the registry's internal dict with frozen run
        registry._runs_by_conversation["conv-1"][run.run_id] = frozen

        # Persist to disk
        registry._persist()

        # Create new registry loading from the same path
        new_registry = SubAgentRunRegistry(persistence_path=persistence_path)

        # Assert - Frozen fields survived the persist/load cycle
        loaded = new_registry.get_run("conv-1", run.run_id)
        assert loaded is not None
        assert loaded.frozen_result_text == "Final answer"
        assert loaded.frozen_at is not None
