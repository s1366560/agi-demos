"""
Unit tests for Phase 4: Async Background Execution.

Tests for:
- StateTracker (lifecycle management)
- BackgroundExecutor (non-blocking SubAgent execution)
- SubAgentState serialization
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.subagent_result import SubAgentResult
from src.infrastructure.agent.subagent.background_executor import BackgroundExecutor
from src.infrastructure.agent.subagent.state_tracker import (
    StateTracker,
    SubAgentState,
    SubAgentStatus,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def tracker():
    return StateTracker()


@pytest.fixture
def sample_subagent() -> SubAgent:
    return SubAgent.create(
        tenant_id="t1",
        name="coder",
        display_name="Coder Agent",
        system_prompt="You are a coding assistant.",
        trigger_description="Coding tasks",
        trigger_keywords=["code"],
    )


# ============================================================================
# Test SubAgentStatus
# ============================================================================


@pytest.mark.unit
class TestSubAgentStatus:
    def test_status_values(self):
        assert SubAgentStatus.PENDING.value == "pending"
        assert SubAgentStatus.RUNNING.value == "running"
        assert SubAgentStatus.COMPLETED.value == "completed"
        assert SubAgentStatus.FAILED.value == "failed"
        assert SubAgentStatus.CANCELLED.value == "cancelled"
        assert SubAgentStatus.TIMED_OUT.value == "timed_out"


# ============================================================================
# Test SubAgentState
# ============================================================================


@pytest.mark.unit
class TestSubAgentState:
    def test_state_defaults(self):
        state = SubAgentState(
            execution_id="e1",
            subagent_id="sa1",
            subagent_name="Test",
            conversation_id="c1",
        )
        assert state.status == SubAgentStatus.PENDING
        assert state.progress == 0
        assert state.started_at is None
        assert state.completed_at is None

    def test_to_dict(self):
        state = SubAgentState(
            execution_id="e1",
            subagent_id="sa1",
            subagent_name="Test",
            conversation_id="c1",
            task_description="Do something",
        )
        d = state.to_dict()
        assert d["execution_id"] == "e1"
        assert d["status"] == "pending"
        assert d["task_description"] == "Do something"

    def test_from_dict(self):
        data = {
            "execution_id": "e1",
            "subagent_id": "sa1",
            "subagent_name": "Test",
            "conversation_id": "c1",
            "status": "running",
            "progress": 50,
        }
        state = SubAgentState.from_dict(data)
        assert state.status == SubAgentStatus.RUNNING
        assert state.progress == 50

    def test_roundtrip(self):
        state = SubAgentState(
            execution_id="e1",
            subagent_id="sa1",
            subagent_name="Test",
            conversation_id="c1",
            task_description="Round trip",
        )
        state.status = SubAgentStatus.COMPLETED
        d = state.to_dict()
        restored = SubAgentState.from_dict(d)
        assert restored.execution_id == state.execution_id
        assert restored.status == SubAgentStatus.COMPLETED


# ============================================================================
# Test StateTracker
# ============================================================================


@pytest.mark.unit
class TestStateTracker:
    def test_register(self, tracker):
        state = tracker.register("e1", "sa1", "Test", "c1", "Do task")
        assert state.execution_id == "e1"
        assert state.status == SubAgentStatus.PENDING

    def test_start(self, tracker):
        tracker.register("e1", "sa1", "Test", "c1")
        state = tracker.start("e1", "c1")
        assert state.status == SubAgentStatus.RUNNING
        assert state.started_at is not None

    def test_complete(self, tracker):
        tracker.register("e1", "sa1", "Test", "c1")
        tracker.start("e1", "c1")
        state = tracker.complete("e1", "c1", summary="Done", tokens_used=100)
        assert state.status == SubAgentStatus.COMPLETED
        assert state.completed_at is not None
        assert state.progress == 100
        assert state.tokens_used == 100

    def test_fail(self, tracker):
        tracker.register("e1", "sa1", "Test", "c1")
        state = tracker.fail("e1", "c1", error="Something broke")
        assert state.status == SubAgentStatus.FAILED
        assert state.error == "Something broke"

    def test_cancel(self, tracker):
        tracker.register("e1", "sa1", "Test", "c1")
        state = tracker.cancel("e1", "c1")
        assert state.status == SubAgentStatus.CANCELLED

    def test_update_progress(self, tracker):
        tracker.register("e1", "sa1", "Test", "c1")
        tracker.start("e1", "c1")
        state = tracker.update_progress("e1", "c1", 75)
        assert state.progress == 75

    def test_progress_clamped(self, tracker):
        tracker.register("e1", "sa1", "Test", "c1")
        state = tracker.update_progress("e1", "c1", 150)
        assert state.progress == 100
        state = tracker.update_progress("e1", "c1", -10)
        assert state.progress == 0

    def test_get_active(self, tracker):
        tracker.register("e1", "sa1", "Test1", "c1")
        tracker.register("e2", "sa2", "Test2", "c1")
        tracker.register("e3", "sa3", "Test3", "c1")
        tracker.start("e1", "c1")
        tracker.complete("e2", "c1")

        active = tracker.get_active("c1")
        assert len(active) == 2  # e1 (running) + e3 (pending)
        names = {s.subagent_name for s in active}
        assert "Test1" in names
        assert "Test3" in names

    def test_get_all(self, tracker):
        tracker.register("e1", "sa1", "Test1", "c1")
        tracker.register("e2", "sa2", "Test2", "c1")
        all_states = tracker.get_all("c1")
        assert len(all_states) == 2

    def test_clear(self, tracker):
        tracker.register("e1", "sa1", "Test", "c1")
        tracker.clear("c1")
        assert tracker.get_all("c1") == []

    def test_get_state_missing(self, tracker):
        assert tracker.get_state("nonexistent", "c1") is None

    def test_conversation_isolation(self, tracker):
        tracker.register("e1", "sa1", "Test", "c1")
        tracker.register("e2", "sa2", "Test", "c2")
        assert len(tracker.get_all("c1")) == 1
        assert len(tracker.get_all("c2")) == 1

    def test_eviction(self, tracker):
        # Register more than MAX_TRACKED states
        for i in range(StateTracker.MAX_TRACKED + 5):
            tracker.register(f"e{i}", "sa1", f"Test{i}", "c1")
            tracker.complete(f"e{i}", "c1")

        all_states = tracker.get_all("c1")
        assert len(all_states) <= StateTracker.MAX_TRACKED


# ============================================================================
# Test BackgroundExecutor
# ============================================================================


@pytest.mark.unit
class TestBackgroundExecutor:
    async def test_launch_returns_execution_id(self, sample_subagent):
        executor = BackgroundExecutor()
        with patch(
            "src.infrastructure.agent.subagent.background_executor.SubAgentProcess"
        ) as MockProcess:
            mock_instance = MagicMock()

            async def mock_execute():
                yield {"type": "subagent_completed", "data": {}}

            mock_instance.execute = mock_execute
            mock_instance.result = SubAgentResult(
                subagent_id="sa1",
                subagent_name="coder",
                summary="Done",
                success=True,
            )
            MockProcess.return_value = mock_instance

            eid = executor.launch(
                subagent=sample_subagent,
                user_message="Write code",
                conversation_id="c1",
                tools=[],
                base_model="test",
            )
            assert eid.startswith("bg-")

            # Let the background task run
            await asyncio.sleep(0.2)

            # Check state was tracked
            state = executor.tracker.get_state(eid, "c1")
            assert state is not None
            assert state.status == SubAgentStatus.COMPLETED

    async def test_launch_emits_events(self, sample_subagent):
        events = []

        async def on_event(event):
            events.append(event)

        executor = BackgroundExecutor(on_event=on_event)

        with patch(
            "src.infrastructure.agent.subagent.background_executor.SubAgentProcess"
        ) as MockProcess:
            mock_instance = MagicMock()

            async def mock_execute():
                yield {"type": "subagent_completed", "data": {}}

            mock_instance.execute = mock_execute
            mock_instance.result = SubAgentResult(
                subagent_id="sa1",
                subagent_name="coder",
                summary="Done",
                success=True,
            )
            MockProcess.return_value = mock_instance

            executor.launch(
                subagent=sample_subagent,
                user_message="Write code",
                conversation_id="c1",
                tools=[],
                base_model="test",
            )
            await asyncio.sleep(0.3)

        event_types = [e["type"] for e in events]
        assert "background_subagent_started" in event_types
        assert "background_subagent_completed" in event_types

    async def test_cancel(self, sample_subagent):
        executor = BackgroundExecutor()

        with patch(
            "src.infrastructure.agent.subagent.background_executor.SubAgentProcess"
        ) as MockProcess:
            mock_instance = MagicMock()

            async def mock_execute():
                await asyncio.sleep(10)  # Long running
                yield {"type": "done", "data": {}}

            mock_instance.execute = mock_execute
            mock_instance.result = None
            MockProcess.return_value = mock_instance

            eid = executor.launch(
                subagent=sample_subagent,
                user_message="Long task",
                conversation_id="c1",
                tools=[],
                base_model="test",
            )
            await asyncio.sleep(0.1)

            result = await executor.cancel(eid, "c1")
            assert result is True

            state = executor.tracker.get_state(eid, "c1")
            assert state.status == SubAgentStatus.CANCELLED

    async def test_get_active(self, sample_subagent):
        executor = BackgroundExecutor()

        with patch(
            "src.infrastructure.agent.subagent.background_executor.SubAgentProcess"
        ) as MockProcess:
            mock_instance = MagicMock()

            async def mock_execute():
                await asyncio.sleep(5)
                yield {"type": "done", "data": {}}

            mock_instance.execute = mock_execute
            mock_instance.result = None
            MockProcess.return_value = mock_instance

            executor.launch(
                subagent=sample_subagent,
                user_message="Task 1",
                conversation_id="c1",
                tools=[],
                base_model="test",
            )
            await asyncio.sleep(0.1)

            active = executor.get_active("c1")
            assert len(active) == 1
            assert active[0]["status"] == "running"

            # Cleanup
            for eid in list(executor._tasks.keys()):
                await executor.cancel(eid, "c1")

    async def test_launch_failure_tracked(self, sample_subagent):
        events = []

        async def on_event(event):
            events.append(event)

        executor = BackgroundExecutor(on_event=on_event)

        with patch(
            "src.infrastructure.agent.subagent.background_executor.SubAgentProcess"
        ) as MockProcess:
            MockProcess.side_effect = Exception("Init failed")

            eid = executor.launch(
                subagent=sample_subagent,
                user_message="Fail",
                conversation_id="c1",
                tools=[],
                base_model="test",
            )
            await asyncio.sleep(0.3)

            state = executor.tracker.get_state(eid, "c1")
            assert state.status == SubAgentStatus.FAILED
