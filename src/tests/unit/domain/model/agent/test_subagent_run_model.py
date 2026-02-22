"""Tests for SubAgentRun model."""

import pytest

from src.domain.model.agent import SubAgentRun, SubAgentRunStatus


@pytest.mark.unit
class TestSubAgentRunModel:
    """SubAgentRun model tests."""

    def test_create_defaults_to_pending(self):
        run = SubAgentRun(
            conversation_id="conv-1",
            subagent_name="researcher",
            task="Find references",
        )

        assert run.status is SubAgentRunStatus.PENDING
        assert run.started_at is None
        assert run.ended_at is None

    def test_start_transitions_to_running(self):
        run = SubAgentRun(
            conversation_id="conv-1",
            subagent_name="researcher",
            task="Find references",
        )

        started = run.start()
        assert started.status is SubAgentRunStatus.RUNNING
        assert started.started_at is not None

    def test_complete_transitions_to_completed(self):
        run = SubAgentRun(
            conversation_id="conv-1",
            subagent_name="researcher",
            task="Find references",
        ).start()

        completed = run.complete(summary="done", execution_time_ms=12)
        assert completed.status is SubAgentRunStatus.COMPLETED
        assert completed.summary == "done"
        assert completed.execution_time_ms == 12
        assert completed.ended_at is not None

    def test_fail_transitions_to_failed(self):
        run = SubAgentRun(
            conversation_id="conv-1",
            subagent_name="researcher",
            task="Find references",
        ).start()

        failed = run.fail("boom", execution_time_ms=3)
        assert failed.status is SubAgentRunStatus.FAILED
        assert failed.error == "boom"
        assert failed.execution_time_ms == 3
        assert failed.ended_at is not None

    def test_complete_requires_running_status(self):
        run = SubAgentRun(
            conversation_id="conv-1",
            subagent_name="researcher",
            task="Find references",
        )

        with pytest.raises(ValueError, match="Invalid status transition"):
            run.complete(summary="done")

    def test_to_event_data_contains_core_fields(self):
        run = (
            SubAgentRun(
                conversation_id="conv-1",
                subagent_name="researcher",
                task="Find references",
            )
            .start()
            .complete(summary="done", execution_time_ms=9)
        )

        event_data = run.to_event_data()
        assert event_data["conversation_id"] == "conv-1"
        assert event_data["subagent_name"] == "researcher"
        assert event_data["status"] == "completed"
        assert event_data["summary"] == "done"
