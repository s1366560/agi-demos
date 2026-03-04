# pyright: reportPrivateUsage=false, reportUnusedCallResult=false
"""Tests for Phase 3 sub-agent reliability features.

Covers three areas of the SubAgent runtime:
1. SubAgentSessionRunner.check_spawn_limits() -- depth and concurrency guards
2. BackgroundExecutor orphan sweep -- timeout detection and cleanup
3. StateTracker -- thread-safe CRUD, eviction, Redis write-through, recovery
"""

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.infrastructure.agent.core.subagent_runner import (
    SubAgentRunnerDeps,
    SubAgentSessionRunner,
)
from src.infrastructure.agent.subagent.background_executor import BackgroundExecutor
from src.infrastructure.agent.subagent.state_tracker import (
    StateTracker,
    SubAgentState,
    SubAgentStatus,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_deps(**overrides: object) -> Mock:
    """Build a mock SubAgentRunnerDeps with sensible defaults."""
    deps = Mock(spec=SubAgentRunnerDeps)
    deps.max_subagent_delegation_depth = overrides.get("max_depth", 2)
    deps.max_subagent_active_runs = overrides.get("max_active", 16)

    registry = Mock()
    registry.count_active_runs = Mock(return_value=overrides.get("active_count", 0))
    deps.subagent_run_registry = registry
    return deps


def _make_runner(**overrides: object) -> SubAgentSessionRunner:
    """Construct a SubAgentSessionRunner with mocked deps."""
    return SubAgentSessionRunner(deps=_make_deps(**overrides))


# =============================================================================
# Test Group 1: check_spawn_limits
# =============================================================================


@pytest.mark.unit
class TestCheckSpawnLimits:
    """Tests for SubAgentSessionRunner.check_spawn_limits()."""

    def test_spawn_allowed_when_within_limits(self) -> None:
        """Spawn is allowed when depth < max and active < max_active."""
        runner = _make_runner(max_depth=3, max_active=16, active_count=0)
        allowed, events = runner.check_spawn_limits("conv-1", 0, "coder")
        assert allowed is True
        assert events == []

    def test_spawn_refused_when_depth_at_limit(self) -> None:
        """Spawn is refused when current_depth == max_depth."""
        runner = _make_runner(max_depth=2, max_active=16, active_count=0)
        allowed, events = runner.check_spawn_limits("conv-1", 2, "coder")
        assert allowed is False
        assert len(events) == 1

    def test_spawn_refused_when_depth_exceeds_limit(self) -> None:
        """Spawn is refused when current_depth > max_depth."""
        runner = _make_runner(max_depth=2, max_active=16, active_count=0)
        _allowed, _events = runner.check_spawn_limits("conv-1", 5, "coder")
        assert _allowed is False

    def test_spawn_refused_when_active_at_limit(self) -> None:
        """Spawn is refused when active_count == max_active."""
        runner = _make_runner(max_depth=3, max_active=4, active_count=4)
        allowed, events = runner.check_spawn_limits("conv-1", 0, "coder")
        assert allowed is False
        assert len(events) == 1

    def test_spawn_refused_when_active_exceeds_limit(self) -> None:
        """Spawn is refused when active_count > max_active."""
        runner = _make_runner(max_depth=3, max_active=4, active_count=10)
        _allowed, _events = runner.check_spawn_limits("conv-1", 0, "coder")
        assert _allowed is False

    def test_depth_one_below_limit_allowed(self) -> None:
        """Spawn is allowed when current_depth == max_depth - 1."""
        runner = _make_runner(max_depth=3, max_active=16, active_count=0)
        allowed, events = runner.check_spawn_limits("conv-1", 2, "coder")
        assert allowed is True
        assert events == []

    def test_active_one_below_limit_allowed(self) -> None:
        """Spawn is allowed when active_count == max_active - 1."""
        runner = _make_runner(max_depth=3, max_active=4, active_count=3)
        allowed, events = runner.check_spawn_limits("conv-1", 0, "coder")
        assert allowed is True
        assert events == []

    def test_depth_limit_event_has_correct_type(self) -> None:
        """Depth-limited event dict contains the correct event type string."""
        runner = _make_runner(max_depth=2, max_active=16, active_count=0)
        _, events = runner.check_spawn_limits("conv-1", 2, "coder")
        assert events[0]["type"] == "subagent_depth_limited"

    def test_depth_limit_event_contains_depth_data(self) -> None:
        """Depth-limited event data includes current_depth and max_depth."""
        runner = _make_runner(max_depth=2, max_active=16, active_count=0)
        _, events = runner.check_spawn_limits("conv-1", 2, "architect")
        data = events[0]["data"]
        assert data["current_depth"] == 2
        assert data["max_depth"] == 2
        assert data["subagent_name"] == "architect"

    def test_queued_event_has_correct_type(self) -> None:
        """Queued event dict contains the correct event type string."""
        runner = _make_runner(max_depth=5, max_active=4, active_count=4)
        _, events = runner.check_spawn_limits("conv-1", 0, "coder")
        assert events[0]["type"] == "subagent_queued"

    def test_queued_event_contains_reason(self) -> None:
        """Queued event data includes reason='concurrency_limit'."""
        runner = _make_runner(max_depth=5, max_active=4, active_count=4)
        _, events = runner.check_spawn_limits("conv-1", 0, "coder")
        data = events[0]["data"]
        assert data["reason"] == "concurrency_limit"
        assert data["subagent_name"] == "coder"

    def test_custom_limits(self) -> None:
        """Custom max_depth=5 and max_active=32 are respected."""
        runner = _make_runner(max_depth=5, max_active=32, active_count=0)
        allowed, _ = runner.check_spawn_limits("conv-1", 4, "coder")
        assert allowed is True

        runner2 = _make_runner(max_depth=5, max_active=32, active_count=0)
        allowed2, _ = runner2.check_spawn_limits("conv-1", 5, "coder")
        assert allowed2 is False

    def test_depth_check_before_concurrency_check(self) -> None:
        """When both limits are exceeded, depth error is returned (checked first)."""
        runner = _make_runner(max_depth=2, max_active=4, active_count=10)
        allowed, events = runner.check_spawn_limits("conv-1", 5, "coder")
        assert allowed is False
        assert events[0]["type"] == "subagent_depth_limited"

    def test_event_dict_has_timestamp(self) -> None:
        """Event dict returned by check_spawn_limits has a timestamp key."""
        runner = _make_runner(max_depth=1, max_active=16, active_count=0)
        _, events = runner.check_spawn_limits("conv-1", 1, "coder")
        assert "timestamp" in events[0]


# =============================================================================
# Test Group 2: BackgroundExecutor orphan sweep
# =============================================================================


@pytest.mark.unit
class TestOrphanSweep:
    """Tests for BackgroundExecutor orphan sweep lifecycle."""

    def test_start_orphan_sweep_creates_task(self) -> None:
        """start_orphan_sweep() creates a background asyncio task."""
        loop = asyncio.new_event_loop()

        async def _run() -> None:
            executor = BackgroundExecutor(timeout_seconds=300)
            executor.start_orphan_sweep(interval_seconds=60)
            assert executor._sweep_task is not None
            assert not executor._sweep_task.done()
            executor.stop_orphan_sweep()
            # give cancellation time to propagate
            await asyncio.sleep(0.05)

        loop.run_until_complete(_run())
        loop.close()

    def test_start_orphan_sweep_no_duplicate(self) -> None:
        """Calling start_orphan_sweep() twice does not create a second task."""
        loop = asyncio.new_event_loop()

        async def _run() -> None:
            executor = BackgroundExecutor(timeout_seconds=300)
            executor.start_orphan_sweep(interval_seconds=60)
            first_task = executor._sweep_task
            executor.start_orphan_sweep(interval_seconds=60)
            assert executor._sweep_task is first_task
            executor.stop_orphan_sweep()
            await asyncio.sleep(0.05)

        loop.run_until_complete(_run())
        loop.close()

    def test_stop_orphan_sweep_cancels_task(self) -> None:
        """stop_orphan_sweep() cancels the running sweep task."""
        loop = asyncio.new_event_loop()

        async def _run() -> None:
            executor = BackgroundExecutor(timeout_seconds=300)
            executor.start_orphan_sweep(interval_seconds=60)
            task = executor._sweep_task
            executor.stop_orphan_sweep()
            await asyncio.sleep(0.05)
            assert task is not None
            assert task.cancelled() or task.done()

        loop.run_until_complete(_run())
        loop.close()

    def test_stop_orphan_sweep_noop_when_not_running(self) -> None:
        """stop_orphan_sweep() is a no-op when no sweep is active."""
        executor = BackgroundExecutor(timeout_seconds=300)
        # Should not raise
        executor.stop_orphan_sweep()
        assert executor._sweep_task is None

    async def test_sweep_removes_done_tasks(self) -> None:
        """_sweep_orphans() removes tasks that are already done."""
        tracker = Mock(spec=StateTracker)
        executor = BackgroundExecutor(state_tracker=tracker, timeout_seconds=300)

        done_task = Mock(spec=asyncio.Task)
        done_task.done.return_value = True
        executor._tasks["exec-done"] = done_task

        await executor._sweep_orphans()

        assert "exec-done" not in executor._tasks

    async def test_sweep_cancels_timed_out_tasks(self) -> None:
        """_sweep_orphans() cancels tasks exceeding timeout_seconds."""
        tracker = Mock(spec=StateTracker)
        on_event = AsyncMock()
        executor = BackgroundExecutor(
            state_tracker=tracker,
            on_event=on_event,
            timeout_seconds=60,
        )

        # A running task
        running_task = Mock(spec=asyncio.Task)
        running_task.done.return_value = False
        executor._tasks["exec-old"] = running_task

        # State shows it started 120s ago
        state = SubAgentState(
            execution_id="exec-old",
            subagent_id="sa-1",
            subagent_name="architect",
            conversation_id="conv-1",
            status=SubAgentStatus.RUNNING,
            started_at=datetime.now(UTC) - timedelta(seconds=120),
        )
        tracker.get_state_by_execution_id = Mock(return_value=state)
        tracker.fail = Mock()

        await executor._sweep_orphans()

        running_task.cancel.assert_called_once()
        tracker.fail.assert_called_once()
        assert "exec-old" not in executor._tasks

    async def test_sweep_emits_killed_event_for_timed_out(self) -> None:
        """_sweep_orphans() emits SubAgentKilledEvent for timed-out tasks."""
        tracker = Mock(spec=StateTracker)
        on_event = AsyncMock()
        executor = BackgroundExecutor(
            state_tracker=tracker,
            on_event=on_event,
            timeout_seconds=60,
        )

        running_task = Mock(spec=asyncio.Task)
        running_task.done.return_value = False
        executor._tasks["exec-timeout"] = running_task

        state = SubAgentState(
            execution_id="exec-timeout",
            subagent_id="sa-2",
            subagent_name="coder",
            conversation_id="conv-1",
            status=SubAgentStatus.RUNNING,
            started_at=datetime.now(UTC) - timedelta(seconds=120),
        )
        tracker.get_state_by_execution_id = Mock(return_value=state)
        tracker.fail = Mock()

        await executor._sweep_orphans()

        on_event.assert_called_once()
        event_dict = on_event.call_args[0][0]
        assert event_dict["type"] == "subagent_killed"
        assert event_dict["data"]["kill_reason"] == "orphan_sweep"

    async def test_sweep_calls_tracker_fail_for_timed_out(self) -> None:
        """_sweep_orphans() calls tracker.fail() with timeout error message."""
        tracker = Mock(spec=StateTracker)
        on_event = AsyncMock()
        executor = BackgroundExecutor(
            state_tracker=tracker,
            on_event=on_event,
            timeout_seconds=30,
        )

        running_task = Mock(spec=asyncio.Task)
        running_task.done.return_value = False
        executor._tasks["exec-1"] = running_task

        state = SubAgentState(
            execution_id="exec-1",
            subagent_id="sa-3",
            subagent_name="tester",
            conversation_id="conv-1",
            status=SubAgentStatus.RUNNING,
            started_at=datetime.now(UTC) - timedelta(seconds=60),
        )
        tracker.get_state_by_execution_id = Mock(return_value=state)
        tracker.fail = Mock()

        await executor._sweep_orphans()

        tracker.fail.assert_called_once_with(
            "exec-1",
            "conv-1",
            error="Timed out after 30s (orphan sweep)",
        )

    async def test_sweep_skips_tasks_with_no_state(self) -> None:
        """_sweep_orphans() skips tasks that have no state in the tracker."""
        tracker = Mock(spec=StateTracker)
        executor = BackgroundExecutor(state_tracker=tracker, timeout_seconds=60)

        running_task = Mock(spec=asyncio.Task)
        running_task.done.return_value = False
        executor._tasks["exec-unknown"] = running_task

        tracker.get_state_by_execution_id = Mock(return_value=None)

        await executor._sweep_orphans()

        running_task.cancel.assert_not_called()
        assert "exec-unknown" in executor._tasks

    async def test_sweep_skips_tasks_with_no_started_at(self) -> None:
        """_sweep_orphans() skips tasks where started_at is None."""
        tracker = Mock(spec=StateTracker)
        executor = BackgroundExecutor(state_tracker=tracker, timeout_seconds=60)

        running_task = Mock(spec=asyncio.Task)
        running_task.done.return_value = False
        executor._tasks["exec-pending"] = running_task

        state = SubAgentState(
            execution_id="exec-pending",
            subagent_id="sa-4",
            subagent_name="planner",
            conversation_id="conv-1",
            status=SubAgentStatus.PENDING,
            started_at=None,
        )
        tracker.get_state_by_execution_id = Mock(return_value=state)

        await executor._sweep_orphans()

        running_task.cancel.assert_not_called()
        assert "exec-pending" in executor._tasks

    async def test_sweep_does_not_cancel_within_timeout(self) -> None:
        """Tasks within the timeout window are NOT cancelled."""
        tracker = Mock(spec=StateTracker)
        on_event = AsyncMock()
        executor = BackgroundExecutor(
            state_tracker=tracker,
            on_event=on_event,
            timeout_seconds=300,
        )

        running_task = Mock(spec=asyncio.Task)
        running_task.done.return_value = False
        executor._tasks["exec-ok"] = running_task

        state = SubAgentState(
            execution_id="exec-ok",
            subagent_id="sa-5",
            subagent_name="coder",
            conversation_id="conv-1",
            status=SubAgentStatus.RUNNING,
            started_at=datetime.now(UTC) - timedelta(seconds=10),
        )
        tracker.get_state_by_execution_id = Mock(return_value=state)

        await executor._sweep_orphans()

        running_task.cancel.assert_not_called()
        on_event.assert_not_called()
        assert "exec-ok" in executor._tasks

    async def test_custom_timeout_is_respected(self) -> None:
        """Custom timeout_seconds value is used for orphan detection."""
        tracker = Mock(spec=StateTracker)
        on_event = AsyncMock()
        executor = BackgroundExecutor(
            state_tracker=tracker,
            on_event=on_event,
            timeout_seconds=10,
        )

        running_task = Mock(spec=asyncio.Task)
        running_task.done.return_value = False
        executor._tasks["exec-custom"] = running_task

        # 15 seconds elapsed — exceeds custom 10s timeout
        state = SubAgentState(
            execution_id="exec-custom",
            subagent_id="sa-6",
            subagent_name="reviewer",
            conversation_id="conv-1",
            status=SubAgentStatus.RUNNING,
            started_at=datetime.now(UTC) - timedelta(seconds=15),
        )
        tracker.get_state_by_execution_id = Mock(return_value=state)
        tracker.fail = Mock()

        await executor._sweep_orphans()

        running_task.cancel.assert_called_once()


# =============================================================================
# Test Group 3: StateTracker
# =============================================================================


@pytest.mark.unit
class TestStateTrackerCRUD:
    """Tests for StateTracker basic create/read/update operations."""

    def test_register_creates_pending_state(self) -> None:
        """register() creates a state with PENDING status."""
        tracker = StateTracker()
        state = tracker.register("exec-1", "sa-1", "coder", "conv-1")
        assert state.status == SubAgentStatus.PENDING
        assert state.execution_id == "exec-1"
        assert state.subagent_name == "coder"

    def test_start_transitions_to_running(self) -> None:
        """start() sets status to RUNNING and records started_at."""
        tracker = StateTracker()
        tracker.register("exec-1", "sa-1", "coder", "conv-1")
        state = tracker.start("exec-1", "conv-1")
        assert state is not None
        assert state.status == SubAgentStatus.RUNNING
        assert state.started_at is not None

    def test_complete_transitions_to_completed(self) -> None:
        """complete() sets status to COMPLETED with progress=100."""
        tracker = StateTracker()
        tracker.register("exec-1", "sa-1", "coder", "conv-1")
        tracker.start("exec-1", "conv-1")
        state = tracker.complete("exec-1", "conv-1", summary="done", tokens_used=500)
        assert state is not None
        assert state.status == SubAgentStatus.COMPLETED
        assert state.progress == 100
        assert state.result_summary == "done"
        assert state.tokens_used == 500

    def test_fail_transitions_to_failed(self) -> None:
        """fail() sets status to FAILED with error message."""
        tracker = StateTracker()
        tracker.register("exec-1", "sa-1", "coder", "conv-1")
        state = tracker.fail("exec-1", "conv-1", error="timeout")
        assert state is not None
        assert state.status == SubAgentStatus.FAILED
        assert state.error == "timeout"
        assert state.completed_at is not None

    def test_cancel_transitions_to_cancelled(self) -> None:
        """cancel() sets status to CANCELLED."""
        tracker = StateTracker()
        tracker.register("exec-1", "sa-1", "coder", "conv-1")
        state = tracker.cancel("exec-1", "conv-1")
        assert state is not None
        assert state.status == SubAgentStatus.CANCELLED


@pytest.mark.unit
class TestStateTrackerQueries:
    """Tests for StateTracker query methods."""

    def test_get_state_by_execution_id_finds_state(self) -> None:
        """get_state_by_execution_id() finds state across conversations."""
        tracker = StateTracker()
        tracker.register("exec-1", "sa-1", "coder", "conv-1")
        tracker.register("exec-2", "sa-2", "planner", "conv-2")
        state = tracker.get_state_by_execution_id("exec-2")
        assert state is not None
        assert state.subagent_name == "planner"
        assert state.conversation_id == "conv-2"

    def test_get_state_by_execution_id_returns_none_for_unknown(self) -> None:
        """get_state_by_execution_id() returns None for unknown ID."""
        tracker = StateTracker()
        assert tracker.get_state_by_execution_id("nonexistent") is None

    def test_get_active_returns_pending_and_running(self) -> None:
        """get_active() returns only PENDING and RUNNING states."""
        tracker = StateTracker()
        tracker.register("exec-1", "sa-1", "a", "conv-1")
        tracker.register("exec-2", "sa-2", "b", "conv-1")
        tracker.register("exec-3", "sa-3", "c", "conv-1")
        tracker.start("exec-2", "conv-1")
        tracker.complete("exec-3", "conv-1")

        active = tracker.get_active("conv-1")
        ids = {s.execution_id for s in active}
        assert ids == {"exec-1", "exec-2"}

    def test_get_all_returns_all_states(self) -> None:
        """get_all() returns all tracked states for a conversation."""
        tracker = StateTracker()
        tracker.register("exec-1", "sa-1", "a", "conv-1")
        tracker.register("exec-2", "sa-2", "b", "conv-1")
        tracker.complete("exec-2", "conv-1")
        assert len(tracker.get_all("conv-1")) == 2

    def test_clear_removes_all_for_conversation(self) -> None:
        """clear() removes all states for a conversation."""
        tracker = StateTracker()
        tracker.register("exec-1", "sa-1", "a", "conv-1")
        tracker.register("exec-2", "sa-2", "b", "conv-1")
        tracker.clear("conv-1")
        assert tracker.get_all("conv-1") == []

    def test_clear_does_not_affect_other_conversations(self) -> None:
        """clear() only removes the targeted conversation's states."""
        tracker = StateTracker()
        tracker.register("exec-1", "sa-1", "a", "conv-1")
        tracker.register("exec-2", "sa-2", "b", "conv-2")
        tracker.clear("conv-1")
        assert len(tracker.get_all("conv-2")) == 1


@pytest.mark.unit
class TestStateTrackerEviction:
    """Tests for StateTracker eviction logic."""

    def test_eviction_when_exceeding_max_tracked(self) -> None:
        """Registering > MAX_TRACKED states evicts oldest completed."""
        tracker = StateTracker()
        # Fill to MAX_TRACKED with completed states
        for i in range(StateTracker.MAX_TRACKED):
            eid = f"exec-{i}"
            tracker.register(eid, f"sa-{i}", f"name-{i}", "conv-1")
            tracker.complete(eid, "conv-1")

        # Register one more to trigger eviction
        tracker.register("exec-new", "sa-new", "new-name", "conv-1")
        all_states = tracker.get_all("conv-1")
        assert len(all_states) <= StateTracker.MAX_TRACKED

    def test_active_states_not_evicted(self) -> None:
        """Active (PENDING/RUNNING) states are NOT evicted even when over limit."""
        tracker = StateTracker()
        # Create many completed states
        for i in range(StateTracker.MAX_TRACKED + 5):
            eid = f"exec-{i}"
            tracker.register(eid, f"sa-{i}", f"name-{i}", "conv-1")
            tracker.complete(eid, "conv-1")

        # Register an active state
        tracker.register("exec-active", "sa-active", "active-name", "conv-1")
        state = tracker.get_state("exec-active", "conv-1")
        assert state is not None
        assert state.status == SubAgentStatus.PENDING


@pytest.mark.unit
class TestStateTrackerUpdateProgress:
    """Tests for StateTracker.update_progress() clamping."""

    def test_progress_clamped_to_zero(self) -> None:
        """Negative progress is clamped to 0."""
        tracker = StateTracker()
        tracker.register("exec-1", "sa-1", "coder", "conv-1")
        state = tracker.update_progress("exec-1", "conv-1", -10)
        assert state is not None
        assert state.progress == 0

    def test_progress_clamped_to_hundred(self) -> None:
        """Progress > 100 is clamped to 100."""
        tracker = StateTracker()
        tracker.register("exec-1", "sa-1", "coder", "conv-1")
        state = tracker.update_progress("exec-1", "conv-1", 200)
        assert state is not None
        assert state.progress == 100

    def test_progress_within_range(self) -> None:
        """Progress within 0-100 is stored as-is."""
        tracker = StateTracker()
        tracker.register("exec-1", "sa-1", "coder", "conv-1")
        state = tracker.update_progress("exec-1", "conv-1", 42)
        assert state is not None
        assert state.progress == 42


@pytest.mark.unit
class TestStateTrackerThreadSafety:
    """Tests for StateTracker thread safety under concurrent access."""

    def test_concurrent_register_from_multiple_threads(self) -> None:
        """Concurrent register calls from multiple threads don't corrupt state."""
        tracker = StateTracker()
        threads: list[threading.Thread] = []
        for i in range(20):
            t = threading.Thread(
                target=tracker.register,
                args=(f"exec-{i}", f"sa-{i}", f"name-{i}", "conv-1"),
            )
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        all_states = tracker.get_all("conv-1")
        assert len(all_states) == 20

    def test_concurrent_start_complete_from_multiple_threads(self) -> None:
        """Concurrent start/complete calls don't corrupt state."""
        tracker = StateTracker()
        # Pre-register all
        for i in range(20):
            tracker.register(f"exec-{i}", f"sa-{i}", f"name-{i}", "conv-1")

        def start_and_complete(idx: int) -> None:
            tracker.start(f"exec-{idx}", "conv-1")
            tracker.complete(f"exec-{idx}", "conv-1")

        threads: list[threading.Thread] = [
            threading.Thread(target=start_and_complete, args=(i,)) for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        all_states = tracker.get_all("conv-1")
        assert len(all_states) == 20
        completed = [s for s in all_states if s.status == SubAgentStatus.COMPLETED]
        assert len(completed) == 20

    def test_concurrent_register_across_conversations(self) -> None:
        """Concurrent registers to different conversations are isolated."""
        tracker = StateTracker()
        threads: list[threading.Thread] = []
        for i in range(10):
            for conv in ("conv-A", "conv-B"):
                t = threading.Thread(
                    target=tracker.register,
                    args=(f"exec-{conv}-{i}", f"sa-{i}", f"name-{i}", conv),
                )
                threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(tracker.get_all("conv-A")) == 10
        assert len(tracker.get_all("conv-B")) == 10


@pytest.mark.unit
class TestStateTrackerSerialization:
    """Tests for SubAgentState.to_dict() / from_dict() round-trip."""

    def test_round_trip_serialization(self) -> None:
        """to_dict() -> from_dict() produces equivalent state."""
        original = SubAgentState(
            execution_id="exec-1",
            subagent_id="sa-1",
            subagent_name="coder",
            conversation_id="conv-1",
            status=SubAgentStatus.RUNNING,
            task_description="Build a feature",
            started_at=datetime.now(UTC),
            progress=50,
            tokens_used=1000,
            tool_calls_count=5,
        )
        data = original.to_dict()
        restored = SubAgentState.from_dict(data)

        assert restored.execution_id == original.execution_id
        assert restored.subagent_id == original.subagent_id
        assert restored.subagent_name == original.subagent_name
        assert restored.conversation_id == original.conversation_id
        assert restored.status == original.status
        assert restored.task_description == original.task_description
        assert restored.progress == original.progress
        assert restored.tokens_used == original.tokens_used
        assert restored.tool_calls_count == original.tool_calls_count

    def test_round_trip_with_completed_state(self) -> None:
        """Round-trip works for a completed state with all fields set."""
        original = SubAgentState(
            execution_id="exec-2",
            subagent_id="sa-2",
            subagent_name="tester",
            conversation_id="conv-2",
            status=SubAgentStatus.COMPLETED,
            task_description="Run tests",
            started_at=datetime.now(UTC) - timedelta(seconds=60),
            completed_at=datetime.now(UTC),
            progress=100,
            result_summary="All 42 tests passed",
            tokens_used=2000,
            tool_calls_count=10,
        )
        data = original.to_dict()
        restored = SubAgentState.from_dict(data)
        assert restored.status == SubAgentStatus.COMPLETED
        assert restored.result_summary == "All 42 tests passed"
        assert restored.completed_at is not None

    def test_to_dict_truncates_result_summary(self) -> None:
        """to_dict() truncates result_summary to 500 chars."""
        state = SubAgentState(
            execution_id="exec-1",
            subagent_id="sa-1",
            subagent_name="coder",
            conversation_id="conv-1",
            result_summary="x" * 1000,
        )
        data = state.to_dict()
        assert len(data["result_summary"]) == 500


@pytest.mark.unit
class TestStateTrackerRedisWriteThrough:
    """Tests for StateTracker Redis write-through behaviour."""

    def test_register_calls_persist_when_redis_set(self) -> None:
        """register() calls _fire_and_forget_persist when redis_client is set."""
        redis_mock = AsyncMock()
        tracker = StateTracker(redis_client=redis_mock)
        with patch.object(tracker, "_fire_and_forget_persist") as persist_mock:
            tracker.register("exec-1", "sa-1", "coder", "conv-1")
            persist_mock.assert_called_once()

    def test_register_does_not_persist_when_no_redis(self) -> None:
        """register() does NOT call _persist_to_redis when redis_client is None."""
        tracker = StateTracker(redis_client=None)
        with patch.object(tracker, "_persist_to_redis") as persist_mock:
            tracker.register("exec-1", "sa-1", "coder", "conv-1")
            persist_mock.assert_not_called()

    async def test_persist_to_redis_writes_correct_key(self) -> None:
        """_persist_to_redis() writes key subagent:state:{conv}:{exec}."""
        redis_mock = AsyncMock()
        tracker = StateTracker(redis_client=redis_mock)
        state = SubAgentState(
            execution_id="exec-1",
            subagent_id="sa-1",
            subagent_name="coder",
            conversation_id="conv-1",
        )
        await tracker._persist_to_redis(state)
        redis_mock.setex.assert_called_once()
        call_args = redis_mock.setex.call_args
        assert call_args[0][0] == "subagent:state:conv-1:exec-1"
        assert call_args[0][1] == 3600

    async def test_persist_to_redis_writes_valid_json(self) -> None:
        """_persist_to_redis() writes valid JSON payload."""
        redis_mock = AsyncMock()
        tracker = StateTracker(redis_client=redis_mock)
        state = SubAgentState(
            execution_id="exec-1",
            subagent_id="sa-1",
            subagent_name="coder",
            conversation_id="conv-1",
        )
        await tracker._persist_to_redis(state)
        payload = redis_mock.setex.call_args[0][2]
        data = json.loads(payload)
        assert data["execution_id"] == "exec-1"

    async def test_persist_to_redis_handles_error_gracefully(self) -> None:
        """_persist_to_redis() logs but does not raise on Redis error."""
        redis_mock = AsyncMock()
        redis_mock.setex.side_effect = ConnectionError("Redis down")
        tracker = StateTracker(redis_client=redis_mock)
        state = SubAgentState(
            execution_id="exec-1",
            subagent_id="sa-1",
            subagent_name="coder",
            conversation_id="conv-1",
        )
        # Should not raise
        await tracker._persist_to_redis(state)

    async def test_persist_to_redis_skips_when_no_client(self) -> None:
        """_persist_to_redis() is a no-op when redis_client is None."""
        tracker = StateTracker(redis_client=None)
        state = SubAgentState(
            execution_id="exec-1",
            subagent_id="sa-1",
            subagent_name="coder",
            conversation_id="conv-1",
        )
        # Should not raise
        await tracker._persist_to_redis(state)


@pytest.mark.unit
class TestStateTrackerRedisRecovery:
    """Tests for StateTracker.recover_from_redis()."""

    async def test_recover_from_redis_returns_empty_without_client(self) -> None:
        """recover_from_redis() returns empty list when no redis client."""
        tracker = StateTracker(redis_client=None)
        result = await tracker.recover_from_redis("conv-1")
        assert result == []

    async def test_recover_from_redis_deserializes_states(self) -> None:
        """recover_from_redis() deserializes states from Redis."""
        redis_mock = AsyncMock()
        tracker = StateTracker(redis_client=redis_mock)

        state_data = SubAgentState(
            execution_id="exec-recovered",
            subagent_id="sa-recovered",
            subagent_name="coder",
            conversation_id="conv-1",
            status=SubAgentStatus.RUNNING,
            task_description="Build a thing",
        )
        raw_json = json.dumps(state_data.to_dict())

        # Mock scan to return one key, then stop
        redis_mock.scan.return_value = (0, ["subagent:state:conv-1:exec-recovered"])
        redis_mock.get.return_value = raw_json

        recovered = await tracker.recover_from_redis("conv-1")
        assert len(recovered) == 1
        assert recovered[0].execution_id == "exec-recovered"
        assert recovered[0].subagent_name == "coder"

    async def test_recover_from_redis_handles_error_gracefully(self) -> None:
        """recover_from_redis() returns empty list on Redis error."""
        redis_mock = AsyncMock()
        redis_mock.scan.side_effect = ConnectionError("Redis down")
        tracker = StateTracker(redis_client=redis_mock)

        result = await tracker.recover_from_redis("conv-1")
        assert result == []
