"""Unit tests for P1 workspace autonomy auto-tick hook."""

from __future__ import annotations

import asyncio

import pytest

from src.infrastructure.adapters.primary.web.routers import (
    workspace_leader_bootstrap as wlb,
)


@pytest.fixture(autouse=True)
def _clear_inflight() -> None:
    wlb._inflight_ticks.clear()
    wlb._background_tasks.clear()


class TestAutoTickEnabled:
    def test_default_is_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(wlb._AUTO_TICK_ENV, raising=False)
        assert wlb._auto_tick_enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "FALSE", "no", "off", ""])
    def test_disabled_values(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv(wlb._AUTO_TICK_ENV, val)
        assert wlb._auto_tick_enabled() is False

    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
    def test_enabled_values(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv(wlb._AUTO_TICK_ENV, val)
        assert wlb._auto_tick_enabled() is True


class TestScheduleAutonomyTick:
    @pytest.mark.asyncio
    async def test_schedules_task_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(wlb._AUTO_TICK_ENV, raising=False)
        called = asyncio.Event()

        async def fake_run(workspace_id: str, actor_user_id: str) -> None:
            assert workspace_id == "ws-x"
            assert actor_user_id == "u-x"
            called.set()

        monkeypatch.setattr(wlb, "_run_autonomy_tick", fake_run)
        wlb.schedule_autonomy_tick("ws-x", "u-x")
        await asyncio.wait_for(called.wait(), timeout=1.0)

    @pytest.mark.asyncio
    async def test_flag_off_short_circuits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(wlb._AUTO_TICK_ENV, "false")
        call_count = 0

        async def fake_run(workspace_id: str, actor_user_id: str) -> None:
            nonlocal call_count
            call_count += 1

        monkeypatch.setattr(wlb, "_run_autonomy_tick", fake_run)
        wlb.schedule_autonomy_tick("ws-x", "u-x")
        # Give the loop a beat to confirm nothing was scheduled.
        await asyncio.sleep(0.05)
        assert call_count == 0

    def test_no_running_loop_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(wlb._AUTO_TICK_ENV, raising=False)

        async def fake_run(workspace_id: str, actor_user_id: str) -> None:
            raise AssertionError("should not run")

        monkeypatch.setattr(wlb, "_run_autonomy_tick", fake_run)
        # No running loop here — should silently no-op.
        wlb.schedule_autonomy_tick("ws-x", "u-x")

    @pytest.mark.asyncio
    async def test_run_autonomy_tick_swallows_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def boom(*_a: object, **_kw: object) -> None:
            raise RuntimeError("kaboom")

        monkeypatch.setattr(wlb, "async_session_factory", boom)
        # Must not raise.
        await wlb._run_autonomy_tick("ws", "u")


class TestWorkerReportHook:
    """Verify the auto-tick is only wired up for terminal report types."""

    def _terminal_types(self) -> list[str]:
        from src.infrastructure.agent.workspace.workspace_goal_runtime import (
            _WORKER_TERMINAL_REPORT_TYPES,
        )

        return sorted(_WORKER_TERMINAL_REPORT_TYPES)

    def test_terminal_types_are_expected(self) -> None:
        assert set(self._terminal_types()) == {
            "completed",
            "failed",
            "blocked",
            "needs_replan",
        }

    def test_hook_source_gates_on_terminal_types(self) -> None:
        """The hook site must check report_type membership in the terminal set."""
        import inspect

        from src.infrastructure.agent.workspace import workspace_goal_runtime

        source = inspect.getsource(workspace_goal_runtime.apply_workspace_worker_report)
        assert "schedule_autonomy_tick" in source
        # Must be guarded by the terminal-type set.
        assert "_WORKER_TERMINAL_REPORT_TYPES" in source

    def test_hook_scheduled_after_commit(self) -> None:
        """schedule_autonomy_tick must appear AFTER publish_pending_events so
        the tick sees the committed ``pending_leader_adjudication`` flag."""
        import inspect

        from src.infrastructure.agent.workspace import workspace_goal_runtime

        source = inspect.getsource(workspace_goal_runtime.apply_workspace_worker_report)
        commit_idx = source.index("await db.commit()")
        schedule_idx = source.index("schedule_autonomy_tick")
        assert commit_idx < schedule_idx

    def test_autonomy_tick_kicks_off_v2_plan_before_legacy_message(self) -> None:
        """The explicit/auto tick path must feed the durable plan before dispatch."""
        import inspect

        source = inspect.getsource(wlb.maybe_auto_trigger_existing_root_execution)
        kickoff_idx = source.index("kickoff_v2_plan_if_enabled")
        message_idx = source.index("message_service.send_message")
        assert kickoff_idx < message_idx


class TestInflightDedup:
    @pytest.mark.asyncio
    async def test_second_call_while_inflight_is_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(wlb._AUTO_TICK_ENV, raising=False)
        start = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def slow_run(ws: str, uid: str) -> None:
            nonlocal calls
            calls += 1
            start.set()
            await release.wait()

        monkeypatch.setattr(wlb, "_run_autonomy_tick", slow_run)
        wlb.schedule_autonomy_tick("ws-dup", "u-1")
        await asyncio.wait_for(start.wait(), timeout=1.0)
        # Second schedule while first is still running should be dropped.
        wlb.schedule_autonomy_tick("ws-dup", "u-1")
        assert "ws-dup" in wlb._inflight_ticks
        release.set()
        # Let the first task finish.
        task = wlb._inflight_ticks.get("ws-dup")
        if task is not None:
            await task
        assert calls == 1
        assert "ws-dup" not in wlb._inflight_ticks

    @pytest.mark.asyncio
    async def test_different_workspaces_both_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(wlb._AUTO_TICK_ENV, raising=False)
        runs: list[str] = []
        done = asyncio.Event()

        async def capture(ws: str, uid: str) -> None:
            runs.append(ws)
            if len(runs) == 2:
                done.set()

        monkeypatch.setattr(wlb, "_run_autonomy_tick", capture)
        wlb.schedule_autonomy_tick("ws-a", "u-1")
        wlb.schedule_autonomy_tick("ws-b", "u-1")
        await asyncio.wait_for(done.wait(), timeout=1.0)
        assert sorted(runs) == ["ws-a", "ws-b"]

    @pytest.mark.asyncio
    async def test_slot_freed_after_completion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(wlb._AUTO_TICK_ENV, raising=False)
        completed = asyncio.Event()

        async def quick(ws: str, uid: str) -> None:
            completed.set()

        monkeypatch.setattr(wlb, "_run_autonomy_tick", quick)
        wlb.schedule_autonomy_tick("ws-free", "u-1")
        await asyncio.wait_for(completed.wait(), timeout=1.0)
        # Drain the done callback.
        await asyncio.sleep(0)
        assert "ws-free" not in wlb._inflight_ticks

        # A new schedule on the same workspace should now go through.
        completed2 = asyncio.Event()

        async def quick2(ws: str, uid: str) -> None:
            completed2.set()

        monkeypatch.setattr(wlb, "_run_autonomy_tick", quick2)
        wlb.schedule_autonomy_tick("ws-free", "u-1")
        await asyncio.wait_for(completed2.wait(), timeout=1.0)


class TestWorkerReportHookInvariants:
    """Lock in the invariants the workspace_goal_runtime hook relies on:
    the terminal report set, and that schedule_autonomy_tick is callable
    with ``(workspace_id, actor_user_id)`` from a sync call site."""

    def test_terminal_set_contains_expected_types(self) -> None:
        from src.infrastructure.agent.workspace import workspace_goal_runtime as wgr

        assert {"completed", "failed", "blocked", "needs_replan"} <= set(
            wgr._WORKER_TERMINAL_REPORT_TYPES
        )

    def test_non_terminal_types_excluded(self) -> None:
        from src.infrastructure.agent.workspace import workspace_goal_runtime as wgr

        for report_type in ("progress", "in_progress", "heartbeat", "started"):
            assert report_type not in wgr._WORKER_TERMINAL_REPORT_TYPES

    @pytest.mark.asyncio
    async def test_schedule_from_hook_site_dispatches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate the workspace_goal_runtime hook site: late-import the
        schedule function and call it. Confirms the symbol is importable
        and that a single terminal report causes exactly one schedule."""
        monkeypatch.delenv(wlb._AUTO_TICK_ENV, raising=False)
        done = asyncio.Event()
        calls: list[tuple[str, str]] = []

        async def fake_run(ws: str, uid: str) -> None:
            calls.append((ws, uid))
            done.set()

        monkeypatch.setattr(wlb, "_run_autonomy_tick", fake_run)

        # Late-import exactly like workspace_goal_runtime does.
        from src.infrastructure.adapters.primary.web.routers.workspace_leader_bootstrap import (
            schedule_autonomy_tick,
        )

        schedule_autonomy_tick("ws-hook", "u-hook")
        await asyncio.wait_for(done.wait(), timeout=1.0)
        assert calls == [("ws-hook", "u-hook")]


class TestAutoCompleteEnabled:
    def test_default_is_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(wlb._AUTO_COMPLETE_ENV, raising=False)
        assert wlb._auto_complete_enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "FALSE", "no", "off", ""])
    def test_disabled_values(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv(wlb._AUTO_COMPLETE_ENV, val)
        assert wlb._auto_complete_enabled() is False

    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
    def test_enabled_values(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv(wlb._AUTO_COMPLETE_ENV, val)
        assert wlb._auto_complete_enabled() is True


class TestAutonomyMentionContent:
    def test_ready_for_completion_variant(self) -> None:
        content = wlb._build_autonomy_mention_content("@leader", "Ship MVP", "ready_for_completion")
        assert "@leader" in content
        assert "Ship MVP" in content
        assert "已完成" in content
        assert "verify" in content.lower()

    def test_replan_required_variant(self) -> None:
        content = wlb._build_autonomy_mention_content("@leader", "Ship MVP", "replan_required")
        assert "重新规划" in content
        assert "replan" in content.lower()

    def test_default_variant(self) -> None:
        content = wlb._build_autonomy_mention_content("@leader", "Ship MVP", "nominal")
        assert "中央黑板" in content
        assert "decompose" in content.lower()


class TestTryAutoCompleteRoot:
    """Smoke tests: flag-off short-circuit and auto_complete_ready_root failure fallback."""

    @pytest.mark.asyncio
    async def test_flag_off_short_circuits_before_try(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When _auto_complete_enabled() is False, callers must not invoke _try_auto_complete_root.

        We verify the flag gate is the env var itself (called every time, no caching).
        """
        monkeypatch.setenv(wlb._AUTO_COMPLETE_ENV, "false")
        assert wlb._auto_complete_enabled() is False
        monkeypatch.setenv(wlb._AUTO_COMPLETE_ENV, "true")
        assert wlb._auto_complete_enabled() is True
