"""Tests for session-oriented SubAgent tools."""

import asyncio
import json

import pytest

from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.tools.subagent_sessions import (
    SessionsAckTool,
    SessionsHistoryTool,
    SessionsListTool,
    SessionsOverviewTool,
    SessionsSendTool,
    SessionsSpawnTool,
    SessionsTimelineTool,
    SessionsWaitTool,
    SubAgentsControlTool,
)


@pytest.mark.unit
class TestSubAgentSessionTools:
    """Session tools tests."""

    async def test_sessions_spawn_creates_running_run_and_events(self):
        spawned: list[tuple[str, str, str]] = []

        async def _spawn(subagent_name: str, task: str, run_id: str) -> str:
            spawned.append((subagent_name, task, run_id))
            return run_id

        registry = SubAgentRunRegistry()
        tool = SessionsSpawnTool(
            subagent_names=["researcher", "coder"],
            subagent_descriptions={"researcher": "Research", "coder": "Code"},
            spawn_callback=_spawn,
            run_registry=registry,
            conversation_id="conv-1",
            max_active_runs=2,
        )

        result = await tool.execute(subagent_name="researcher", task="Find papers")
        assert "Spawned SubAgent session" in result
        assert len(spawned) == 1
        events = tool.consume_pending_events()
        assert events[0]["type"] == "subagent_run_started"
        assert events[1]["type"] == "subagent_session_spawned"

    async def test_sessions_spawn_session_mode_requires_thread(self):
        async def _spawn(subagent_name: str, task: str, run_id: str) -> str:
            return run_id

        registry = SubAgentRunRegistry()
        tool = SessionsSpawnTool(
            subagent_names=["researcher", "coder"],
            subagent_descriptions={"researcher": "Research", "coder": "Code"},
            spawn_callback=_spawn,
            run_registry=registry,
            conversation_id="conv-1",
        )
        result = await tool.execute(
            subagent_name="researcher",
            task="Find papers",
            mode="session",
            thread=False,
        )
        assert "mode='session' requires thread=true" in result

    async def test_sessions_spawn_forwards_spawn_options(self):
        spawned: list[tuple[str, str, str, dict[str, object]]] = []

        async def _spawn(
            subagent_name: str,
            task: str,
            run_id: str,
            **kwargs: object,
        ) -> str:
            spawned.append((subagent_name, task, run_id, dict(kwargs)))
            return run_id

        registry = SubAgentRunRegistry()
        tool = SessionsSpawnTool(
            subagent_names=["researcher", "coder"],
            subagent_descriptions={"researcher": "Research", "coder": "Code"},
            spawn_callback=_spawn,
            run_registry=registry,
            conversation_id="conv-1",
            max_active_runs=3,
        )

        result = await tool.execute(
            subagent_name="researcher",
            task="Find papers",
            mode="session",
            thread=True,
            cleanup="keep",
            agent_id="coder",
            model="gpt-5-mini",
            thinking="high",
        )
        assert "Spawned persistent SubAgent session" in result
        assert len(spawned) == 1
        spawned_name, _, run_id, spawn_options = spawned[0]
        assert spawned_name == "coder"
        assert spawn_options["spawn_mode"] == "session"
        assert spawn_options["thread_requested"] is True
        assert spawn_options["cleanup"] == "keep"
        assert spawn_options["agent_id"] == "coder"
        assert spawn_options["model"] == "gpt-5-mini"
        assert spawn_options["thinking"] == "high"

        run = registry.get_run("conv-1", run_id)
        assert run is not None
        assert run.subagent_name == "coder"
        assert run.metadata["requested_subagent_name"] == "researcher"
        assert run.metadata["spawn_mode"] == "session"
        assert run.metadata["cleanup"] == "keep"
        assert run.metadata["model"] == "gpt-5-mini"
        assert run.metadata["thinking"] == "high"

    async def test_sessions_spawn_session_mode_rejects_delete_cleanup(self):
        async def _spawn(subagent_name: str, task: str, run_id: str) -> str:
            return run_id

        registry = SubAgentRunRegistry()
        tool = SessionsSpawnTool(
            subagent_names=["researcher"],
            subagent_descriptions={"researcher": "Research"},
            spawn_callback=_spawn,
            run_registry=registry,
            conversation_id="conv-1",
        )

        result = await tool.execute(
            subagent_name="researcher",
            task="Find papers",
            mode="session",
            thread=True,
            cleanup="delete",
        )
        assert "mode='session' requires cleanup='keep'" in result

    async def test_sessions_spawn_legacy_callback_ignores_spawn_options(self):
        observed: list[tuple[str, str, str]] = []

        async def _spawn(subagent_name: str, task: str, run_id: str) -> str:
            observed.append((subagent_name, task, run_id))
            return run_id

        registry = SubAgentRunRegistry()
        tool = SessionsSpawnTool(
            subagent_names=["researcher"],
            subagent_descriptions={"researcher": "Research"},
            spawn_callback=_spawn,
            run_registry=registry,
            conversation_id="conv-1",
        )

        result = await tool.execute(
            subagent_name="researcher",
            task="Find papers",
            mode="run",
            model="gpt-5-mini",
            thinking="low",
        )
        assert "Spawned SubAgent session" in result
        assert len(observed) == 1

    async def test_sessions_spawn_respects_active_limit(self):
        async def _spawn(subagent_name: str, task: str, run_id: str) -> str:
            return run_id

        registry = SubAgentRunRegistry()
        existing = registry.create_run("conv-1", "researcher", "existing")
        registry.mark_running("conv-1", existing.run_id)

        tool = SessionsSpawnTool(
            subagent_names=["researcher"],
            subagent_descriptions={"researcher": "Research"},
            spawn_callback=_spawn,
            run_registry=registry,
            conversation_id="conv-1",
            max_active_runs=1,
        )
        result = await tool.execute(subagent_name="researcher", task="Find papers")
        assert "active SubAgent sessions limit reached" in result

    async def test_sessions_spawn_retries_before_success(self):
        attempts = 0

        async def _spawn(subagent_name: str, task: str, run_id: str) -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise RuntimeError("temporary failure")
            return run_id

        registry = SubAgentRunRegistry()
        tool = SessionsSpawnTool(
            subagent_names=["researcher"],
            subagent_descriptions={"researcher": "Research"},
            spawn_callback=_spawn,
            run_registry=registry,
            conversation_id="conv-1",
            max_spawn_retries=2,
            retry_delay_ms=1,
        )
        result = await tool.execute(subagent_name="researcher", task="Find papers")
        assert "Spawned SubAgent session" in result
        assert attempts == 2
        events = tool.consume_pending_events()
        event_types = [event["type"] for event in events]
        assert "subagent_announce_retry" in event_types
        assert event_types[-1] == "subagent_session_spawned"
        stored_run = registry.list_runs("conv-1")[0]
        announce_events = stored_run.metadata.get("announce_events")
        assert [event["type"] for event in announce_events] == ["retry"]

    async def test_sessions_spawn_giveup_after_retries(self):
        async def _spawn(subagent_name: str, task: str, run_id: str) -> str:
            raise RuntimeError("always failing")

        registry = SubAgentRunRegistry()
        tool = SessionsSpawnTool(
            subagent_names=["researcher"],
            subagent_descriptions={"researcher": "Research"},
            spawn_callback=_spawn,
            run_registry=registry,
            conversation_id="conv-1",
            max_spawn_retries=1,
            retry_delay_ms=1,
        )
        result = await tool.execute(subagent_name="researcher", task="Find papers")
        assert "failed to spawn session" in result
        events = tool.consume_pending_events()
        event_types = [event["type"] for event in events]
        assert "subagent_announce_retry" in event_types
        assert "subagent_announce_giveup" in event_types
        assert event_types[-1] == "subagent_run_failed"
        stored_run = registry.list_runs("conv-1")[0]
        announce_events = stored_run.metadata.get("announce_events")
        assert [event["type"] for event in announce_events] == ["retry", "giveup"]

    async def test_sessions_spawn_announce_history_has_drop_policy(self):
        async def _spawn(subagent_name: str, task: str, run_id: str) -> str:
            raise RuntimeError("always failing")

        registry = SubAgentRunRegistry()
        tool = SessionsSpawnTool(
            subagent_names=["researcher"],
            subagent_descriptions={"researcher": "Research"},
            spawn_callback=_spawn,
            run_registry=registry,
            conversation_id="conv-1",
            max_spawn_retries=22,
            retry_delay_ms=1,
        )
        await tool.execute(subagent_name="researcher", task="Find papers")

        stored_run = registry.list_runs("conv-1")[0]
        announce_events = stored_run.metadata.get("announce_events")
        assert isinstance(announce_events, list)
        assert len(announce_events) == 20
        assert stored_run.metadata.get("announce_events_dropped", 0) > 0

    async def test_sessions_list_and_history(self):
        registry = SubAgentRunRegistry()
        run1 = registry.create_run(
            "conv-1",
            "researcher",
            "task-1",
            requester_session_key="req-main",
        )
        registry.mark_running("conv-1", run1.run_id)
        run2 = registry.create_run(
            "conv-1",
            "coder",
            "task-2",
            requester_session_key="req-main",
        )
        registry.mark_running("conv-1", run2.run_id)
        registry.mark_completed("conv-1", run2.run_id, summary="done")
        run3 = registry.create_run(
            "conv-1",
            "writer",
            "task-3",
            requester_session_key="req-other",
        )
        registry.mark_running("conv-1", run3.run_id)
        registry.mark_completed("conv-1", run3.run_id, summary="done")

        list_tool = SessionsListTool(registry, "conv-1", requester_session_key="req-main")
        active_data = json.loads(await list_tool.execute(status="active"))
        assert active_data["count"] == 1
        assert active_data["runs"][0]["run_id"] == run1.run_id

        history_tool = SessionsHistoryTool(registry, "conv-1", requester_session_key="req-main")
        history_data = json.loads(await history_tool.execute(limit=10))
        assert history_data["count"] == 2

        all_data = json.loads(await history_tool.execute(visibility="all", limit=10))
        assert all_data["count"] == 3

    async def test_sessions_list_rejects_invalid_visibility(self):
        registry = SubAgentRunRegistry()
        list_tool = SessionsListTool(registry, "conv-1", requester_session_key="req-main")
        result = await list_tool.execute(status="active", visibility="invalid")
        assert "invalid visibility" in result

    async def test_sessions_wait_returns_terminal_run(self):
        registry = SubAgentRunRegistry()
        run = registry.create_run("conv-1", "researcher", "task")
        registry.mark_running("conv-1", run.run_id)
        wait_tool = SessionsWaitTool(registry, "conv-1")

        async def _complete() -> None:
            await asyncio.sleep(0.02)
            registry.mark_completed("conv-1", run.run_id, summary="done")

        task = asyncio.create_task(_complete())
        try:
            payload = json.loads(
                await wait_tool.execute(run_id=run.run_id, timeout_seconds=1, poll_interval_ms=10)
            )
        finally:
            await task

        assert payload["is_terminal"] is True
        assert payload["run"]["status"] == "completed"
        assert payload["announce"]["status"] is None
        assert payload["announce"]["payload"] is None

    async def test_sessions_wait_surfaces_announce_payload(self):
        registry = SubAgentRunRegistry()
        run = registry.create_run(
            "conv-1",
            "researcher",
            "task",
            metadata={
                "announce_status": "delivered",
                "announce_attempt_count": 2,
                "announce_payload": {"status": "completed", "result": "done"},
            },
        )
        registry.mark_running("conv-1", run.run_id)
        registry.mark_completed("conv-1", run.run_id, summary="done")
        wait_tool = SessionsWaitTool(registry, "conv-1")

        payload = json.loads(
            await wait_tool.execute(run_id=run.run_id, timeout_seconds=0.1, poll_interval_ms=10)
        )
        assert payload["announce"]["status"] == "delivered"
        assert payload["announce"]["attempt_count"] == 2
        assert payload["announce"]["payload"]["result"] == "done"

    async def test_sessions_wait_times_out_for_running_run(self):
        registry = SubAgentRunRegistry()
        run = registry.create_run("conv-1", "researcher", "task")
        registry.mark_running("conv-1", run.run_id)
        wait_tool = SessionsWaitTool(registry, "conv-1")

        payload = json.loads(
            await wait_tool.execute(run_id=run.run_id, timeout_seconds=0.03, poll_interval_ms=10)
        )
        assert payload["is_terminal"] is False
        assert payload["timed_out"] is True
        assert payload["run"]["status"] == "running"

    async def test_sessions_ack_records_terminal_ack(self):
        registry = SubAgentRunRegistry()
        run = registry.create_run("conv-1", "researcher", "task")
        registry.mark_running("conv-1", run.run_id)
        registry.mark_completed("conv-1", run.run_id, summary="done")
        ack_tool = SessionsAckTool(
            registry,
            "conv-1",
            requester_session_key="req-main",
        )

        payload = json.loads(await ack_tool.execute(run_id=run.run_id, note="accepted"))
        assert payload["acknowledged"] is True
        assert payload["status"] == "completed"
        assert payload["ack_count"] == 1

        updated = registry.get_run("conv-1", run.run_id)
        assert updated is not None
        assert updated.metadata.get("last_ack_by") == "req-main"
        assert isinstance(updated.metadata.get("ack_events"), list)
        assert updated.metadata["ack_events"][0]["type"] == "ack"
        assert updated.metadata["ack_events"][0]["note"] == "accepted"

    async def test_sessions_ack_rejects_non_terminal_run(self):
        registry = SubAgentRunRegistry()
        run = registry.create_run("conv-1", "researcher", "task")
        registry.mark_running("conv-1", run.run_id)
        ack_tool = SessionsAckTool(registry, "conv-1")

        result = await ack_tool.execute(run_id=run.run_id)
        assert "is not terminal" in result

    async def test_sessions_timeline_replays_lifecycle_with_descendants(self):
        registry = SubAgentRunRegistry()
        parent = registry.create_run("conv-1", "researcher", "task")
        registry.mark_running("conv-1", parent.run_id)
        registry.attach_metadata(
            "conv-1",
            parent.run_id,
            {
                "announce_events": [
                    {
                        "type": "retry",
                        "timestamp": parent.created_at.isoformat(),
                        "attempt": 1,
                    }
                ],
                "ack_events": [
                    {
                        "type": "ack",
                        "timestamp": parent.created_at.isoformat(),
                        "requester_session_key": "req-main",
                    }
                ],
            },
        )
        child = registry.create_run(
            "conv-1",
            "coder",
            "child-task",
            parent_run_id=parent.run_id,
            lineage_root_run_id=parent.run_id,
        )
        registry.mark_running("conv-1", child.run_id)
        registry.mark_completed("conv-1", child.run_id, summary="done")
        registry.mark_completed("conv-1", parent.run_id, summary="done")

        tool = SessionsTimelineTool(registry, "conv-1")
        payload = json.loads(await tool.execute(run_id=parent.run_id, include_descendants=True))

        assert payload["run_count"] == 2
        event_types = [event["type"] for event in payload["events"]]
        assert "run_created" in event_types
        assert "run_started" in event_types
        assert "run_completed" in event_types
        assert "announce_retry" in event_types
        assert "run_acknowledged" in event_types
        run_ids = {event["run_id"] for event in payload["events"]}
        assert run_ids == {parent.run_id, child.run_id}

    async def test_sessions_timeline_excludes_descendants_by_default(self):
        registry = SubAgentRunRegistry()
        parent = registry.create_run("conv-1", "researcher", "task")
        registry.mark_running("conv-1", parent.run_id)
        child = registry.create_run(
            "conv-1",
            "coder",
            "child-task",
            parent_run_id=parent.run_id,
            lineage_root_run_id=parent.run_id,
        )
        registry.mark_running("conv-1", child.run_id)

        tool = SessionsTimelineTool(registry, "conv-1")
        payload = json.loads(await tool.execute(run_id=parent.run_id))
        run_ids = {event["run_id"] for event in payload["events"]}
        assert run_ids == {parent.run_id}

    async def test_sessions_overview_aggregates_metrics_and_hotspots(self):
        registry = SubAgentRunRegistry()
        failed = registry.create_run(
            "conv-1",
            "researcher",
            "task-1",
            requester_session_key="req-main",
            metadata={
                "lane_wait_ms": 30,
                "announce_events": [{"type": "retry"}],
                "announce_events_dropped": 1,
            },
        )
        registry.mark_running("conv-1", failed.run_id)
        registry.mark_failed("conv-1", failed.run_id, error="tool crashed")

        timed_out = registry.create_run(
            "conv-1",
            "researcher",
            "task-2",
            requester_session_key="req-main",
            metadata={
                "lane_wait_ms": 10,
                "announce_events": [{"type": "giveup"}, {"type": "completion_delivered"}],
            },
        )
        registry.mark_running("conv-1", timed_out.run_id)
        registry.mark_timed_out("conv-1", timed_out.run_id, reason="tool crashed")

        running = registry.create_run(
            "conv-1",
            "coder",
            "task-3",
            requester_session_key="req-main",
        )
        registry.mark_running("conv-1", running.run_id)

        completed = registry.create_run(
            "conv-1",
            "writer",
            "task-4",
            requester_session_key="req-main",
        )
        registry.mark_running("conv-1", completed.run_id)
        registry.mark_completed("conv-1", completed.run_id, summary="done")

        tool = SessionsOverviewTool(
            registry,
            "conv-1",
            requester_session_key="req-main",
            observability_stats_provider=lambda: {"hook_failures": 2},
        )
        payload = json.loads(await tool.execute())

        assert payload["total_runs"] == 4
        assert payload["active_runs"] == 1
        assert payload["status_counts"]["failed"] == 1
        assert payload["status_counts"]["timed_out"] == 1
        assert payload["status_counts"]["running"] == 1
        assert payload["status_counts"]["completed"] == 1
        assert payload["announce_summary"]["retry_count"] == 1
        assert payload["announce_summary"]["giveup_count"] == 1
        assert payload["announce_summary"]["delivered_count"] == 1
        assert payload["announce_summary"]["dropped_count"] == 1
        assert payload["announce_summary"]["backlog_count"] == 3
        assert payload["archive_lag_ms"]["retention_seconds"] == registry.terminal_retention_seconds
        assert payload["archive_lag_ms"]["stale_count"] == 0
        assert payload["hook_failures"] == 2
        assert payload["lane_wait_ms"]["sample_count"] == 2
        assert payload["lane_wait_ms"]["avg"] == 20
        assert payload["lane_wait_ms"]["max"] == 30
        assert payload["error_hotspots"][0] == {"error": "tool crashed", "count": 2}

    async def test_sessions_overview_respects_visibility(self):
        registry = SubAgentRunRegistry()
        own = registry.create_run(
            "conv-1",
            "researcher",
            "task-own",
            requester_session_key="req-main",
        )
        registry.mark_running("conv-1", own.run_id)
        other = registry.create_run(
            "conv-1",
            "coder",
            "task-other",
            requester_session_key="req-other",
        )
        registry.mark_running("conv-1", other.run_id)

        tool = SessionsOverviewTool(registry, "conv-1", requester_session_key="req-main")
        self_payload = json.loads(await tool.execute(visibility="self"))
        all_payload = json.loads(await tool.execute(visibility="all"))
        assert self_payload["total_runs"] == 1
        assert all_payload["total_runs"] == 2

        error = await tool.execute(visibility="invalid")
        assert "invalid visibility" in error

    async def test_sessions_send_creates_child_run(self):
        spawned: list[tuple[str, str, str]] = []

        async def _spawn(subagent_name: str, task: str, run_id: str) -> str:
            spawned.append((subagent_name, task, run_id))
            return run_id

        registry = SubAgentRunRegistry()
        parent = registry.create_run("conv-1", "researcher", "initial")
        registry.mark_running("conv-1", parent.run_id)
        registry.mark_completed("conv-1", parent.run_id, summary="done")

        tool = SessionsSendTool(
            run_registry=registry,
            conversation_id="conv-1",
            spawn_callback=_spawn,
            max_active_runs=3,
        )
        result = await tool.execute(run_id=parent.run_id, task="follow-up")
        assert "Follow-up dispatched as run" in result
        assert len(spawned) == 1
        events = tool.consume_pending_events()
        assert events[0]["type"] == "subagent_run_started"
        assert events[1]["type"] == "subagent_session_message_sent"

    async def test_sessions_send_retries_before_success(self):
        attempts = 0
        observed_run_ids: list[str] = []

        async def _spawn(subagent_name: str, task: str, run_id: str) -> str:
            nonlocal attempts
            attempts += 1
            observed_run_ids.append(run_id)
            if attempts < 2:
                raise RuntimeError("temporary send error")
            return run_id

        registry = SubAgentRunRegistry()
        parent = registry.create_run("conv-1", "researcher", "initial")
        registry.mark_running("conv-1", parent.run_id)
        registry.mark_completed("conv-1", parent.run_id, summary="done")

        tool = SessionsSendTool(
            run_registry=registry,
            conversation_id="conv-1",
            spawn_callback=_spawn,
            max_active_runs=3,
            max_spawn_retries=2,
            retry_delay_ms=1,
        )
        result = await tool.execute(run_id=parent.run_id, task="follow-up")
        assert "Follow-up dispatched as run" in result
        assert attempts == 2
        events = tool.consume_pending_events()
        event_types = [event["type"] for event in events]
        assert "subagent_announce_retry" in event_types
        assert event_types[-1] == "subagent_session_message_sent"
        child_run = registry.get_run("conv-1", observed_run_ids[-1])
        assert child_run is not None
        announce_events = child_run.metadata.get("announce_events")
        assert [event["type"] for event in announce_events] == ["retry"]

    async def test_sessions_send_inherits_spawn_options(self):
        captured: list[dict[str, object]] = []

        async def _spawn(
            subagent_name: str,
            task: str,
            run_id: str,
            **kwargs: object,
        ) -> str:
            captured.append(dict(kwargs))
            return run_id

        registry = SubAgentRunRegistry()
        parent = registry.create_run(
            "conv-1",
            "researcher",
            "initial",
            metadata={
                "spawn_mode": "session",
                "thread_requested": True,
                "cleanup": "keep",
                "agent_id": "researcher",
                "model": "gpt-5-mini",
                "thinking": "medium",
            },
        )
        registry.mark_running("conv-1", parent.run_id)
        registry.mark_completed("conv-1", parent.run_id, summary="done")

        tool = SessionsSendTool(
            run_registry=registry,
            conversation_id="conv-1",
            spawn_callback=_spawn,
        )
        result = await tool.execute(run_id=parent.run_id, task="follow-up")
        assert "Follow-up dispatched as run" in result
        assert len(captured) == 1
        assert captured[0]["spawn_mode"] == "session"
        assert captured[0]["thread_requested"] is True
        assert captured[0]["cleanup"] == "keep"
        assert captured[0]["model"] == "gpt-5-mini"
        assert captured[0]["thinking"] == "medium"

    async def test_subagents_control_list_steer_kill(self):
        cancelled: list[str] = []

        async def _cancel(run_id: str) -> bool:
            cancelled.append(run_id)
            return True

        registry = SubAgentRunRegistry()
        run = registry.create_run("conv-1", "researcher", "work")
        registry.mark_running("conv-1", run.run_id)

        tool = SubAgentsControlTool(
            run_registry=registry,
            conversation_id="conv-1",
            subagent_names=["researcher", "coder"],
            subagent_descriptions={"researcher": "Research", "coder": "Code"},
            cancel_callback=_cancel,
        )

        list_data = json.loads(await tool.execute(action="list"))
        assert list_data["active_run_count"] == 1

        steer_result = await tool.execute(
            action="steer",
            run_id=run.run_id,
            instruction="Focus on summaries",
        )
        assert "Steering instruction attached" in steer_result

        kill_result = await tool.execute(action="kill", run_id=run.run_id)
        assert "Cancelled 1 run(s)" in kill_result
        assert cancelled == [run.run_id]

    async def test_subagents_control_info_supports_target_tokens(self):
        async def _cancel(run_id: str) -> bool:
            return True

        registry = SubAgentRunRegistry()
        root = registry.create_run(
            "conv-1",
            "researcher",
            "root-work",
            metadata={"label": "team-a"},
        )
        registry.mark_running("conv-1", root.run_id)
        child = registry.create_run(
            "conv-1",
            "coder",
            "child-work",
            parent_run_id=root.run_id,
            lineage_root_run_id=root.run_id,
        )
        registry.mark_running("conv-1", child.run_id)
        other = registry.create_run(
            "conv-1",
            "writer",
            "other-work",
            metadata={"label": "team-b"},
        )
        registry.mark_running("conv-1", other.run_id)

        tool = SubAgentsControlTool(
            run_registry=registry,
            conversation_id="conv-1",
            subagent_names=["researcher", "coder", "writer"],
            subagent_descriptions={
                "researcher": "Research",
                "coder": "Code",
                "writer": "Write",
            },
            cancel_callback=_cancel,
        )

        list_data = json.loads(await tool.execute(action="list"))
        assert list_data["active_run_count"] == 3
        assert len(list_data["active_runs"]) == 3

        index_target = list_data["active_runs"][0]["target"]
        expected_run_id = list_data["active_runs"][0]["run_id"]
        info_by_index = json.loads(
            await tool.execute(action="info", target=index_target, include_descendants=False)
        )
        assert info_by_index["run_count"] == 1
        assert info_by_index["runs"][0]["run_id"] == expected_run_id

        info_by_label = json.loads(await tool.execute(action="info", target="label:team-a"))
        run_ids = {run["run_id"] for run in info_by_label["runs"]}
        assert run_ids == {root.run_id, child.run_id}

    async def test_subagents_control_kill_with_target_all(self):
        cancelled: list[str] = []

        async def _cancel(run_id: str) -> bool:
            cancelled.append(run_id)
            return True

        registry = SubAgentRunRegistry()
        first = registry.create_run("conv-1", "researcher", "work-1")
        second = registry.create_run("conv-1", "coder", "work-2")
        registry.mark_running("conv-1", first.run_id)
        registry.mark_running("conv-1", second.run_id)

        tool = SubAgentsControlTool(
            run_registry=registry,
            conversation_id="conv-1",
            subagent_names=["researcher", "coder"],
            subagent_descriptions={"researcher": "Research", "coder": "Code"},
            cancel_callback=_cancel,
        )

        result = await tool.execute(action="kill", target="all")
        assert result == "Cancelled 2 run(s) for target all"
        assert set(cancelled) == {first.run_id, second.run_id}

    async def test_subagents_kill_cascades_descendants(self):
        cancelled: list[str] = []

        async def _cancel(run_id: str) -> bool:
            cancelled.append(run_id)
            return True

        registry = SubAgentRunRegistry()
        parent = registry.create_run("conv-1", "researcher", "work")
        registry.mark_running("conv-1", parent.run_id)
        child = registry.create_run(
            "conv-1",
            "coder",
            "child-work",
            parent_run_id=parent.run_id,
            lineage_root_run_id=parent.run_id,
        )
        registry.mark_running("conv-1", child.run_id)

        tool = SubAgentsControlTool(
            run_registry=registry,
            conversation_id="conv-1",
            subagent_names=["researcher", "coder"],
            subagent_descriptions={"researcher": "Research", "coder": "Code"},
            cancel_callback=_cancel,
        )
        result = await tool.execute(action="kill", run_id=parent.run_id)
        assert "Cancelled 2 run(s)" in result
        assert set(cancelled) == {parent.run_id, child.run_id}

    async def test_subagents_steer_restarts_run(self):
        cancelled: list[str] = []
        restarted: list[tuple[str, str, str]] = []

        async def _cancel(run_id: str) -> bool:
            cancelled.append(run_id)
            return True

        async def _restart(subagent_name: str, task: str, run_id: str) -> str:
            restarted.append((subagent_name, task, run_id))
            return run_id

        registry = SubAgentRunRegistry()
        run = registry.create_run("conv-1", "researcher", "work")
        registry.mark_running("conv-1", run.run_id)

        tool = SubAgentsControlTool(
            run_registry=registry,
            conversation_id="conv-1",
            subagent_names=["researcher"],
            subagent_descriptions={"researcher": "Research"},
            cancel_callback=_cancel,
            restart_callback=_restart,
            steer_rate_limit_ms=1,
        )
        result = await tool.execute(
            action="steer",
            run_id=run.run_id,
            instruction="Focus on edge cases",
        )
        assert "restarted as" in result
        assert cancelled == [run.run_id]
        assert len(restarted) == 1
        old_run = registry.get_run("conv-1", run.run_id)
        assert old_run is not None
        assert old_run.status.value == "cancelled"
        replacement_runs = [
            candidate
            for candidate in registry.list_runs("conv-1")
            if candidate.metadata.get("steered_from_run_id") == run.run_id
        ]
        assert len(replacement_runs) == 1

    async def test_subagents_control_log_replays_target_timeline(self):
        async def _cancel(run_id: str) -> bool:
            return True

        registry = SubAgentRunRegistry()
        root = registry.create_run("conv-1", "researcher", "work")
        registry.mark_running("conv-1", root.run_id)
        child = registry.create_run(
            "conv-1",
            "coder",
            "child",
            parent_run_id=root.run_id,
            lineage_root_run_id=root.run_id,
        )
        registry.mark_running("conv-1", child.run_id)
        registry.mark_completed("conv-1", child.run_id, summary="done")

        tool = SubAgentsControlTool(
            run_registry=registry,
            conversation_id="conv-1",
            subagent_names=["researcher", "coder"],
            subagent_descriptions={"researcher": "Research", "coder": "Code"},
            cancel_callback=_cancel,
        )
        payload = json.loads(
            await tool.execute(action="log", target=root.run_id, include_descendants=True)
        )
        assert payload["root_run_id"] == root.run_id
        assert payload["run_count"] == 2
        event_types = [event["type"] for event in payload["events"]]
        assert "run_created" in event_types
        assert "run_started" in event_types

    async def test_subagents_control_send_dispatches_follow_up(self):
        spawned: list[tuple[str, str, str]] = []

        async def _cancel(run_id: str) -> bool:
            return True

        async def _spawn(subagent_name: str, task: str, run_id: str) -> str:
            spawned.append((subagent_name, task, run_id))
            return run_id

        registry = SubAgentRunRegistry()
        parent = registry.create_run("conv-1", "researcher", "initial")
        registry.mark_running("conv-1", parent.run_id)
        registry.mark_completed("conv-1", parent.run_id, summary="done")

        tool = SubAgentsControlTool(
            run_registry=registry,
            conversation_id="conv-1",
            subagent_names=["researcher"],
            subagent_descriptions={"researcher": "Research"},
            cancel_callback=_cancel,
            restart_callback=_spawn,
        )
        result = await tool.execute(action="send", target=parent.run_id, task="follow-up")
        assert "Follow-up dispatched as run" in result
        assert len(spawned) == 1
        events = tool.consume_pending_events()
        event_types = [event["type"] for event in events]
        assert "subagent_run_started" in event_types
        assert "subagent_session_message_sent" in event_types

    async def test_subagents_control_blocks_mutations_at_depth_limit(self):
        async def _cancel(run_id: str) -> bool:
            return True

        registry = SubAgentRunRegistry()
        run = registry.create_run("conv-1", "researcher", "work")
        registry.mark_running("conv-1", run.run_id)

        tool = SubAgentsControlTool(
            run_registry=registry,
            conversation_id="conv-1",
            subagent_names=["researcher"],
            subagent_descriptions={"researcher": "Research"},
            cancel_callback=_cancel,
            delegation_depth=1,
            max_delegation_depth=1,
        )

        kill_error = await tool.execute(action="kill", run_id=run.run_id)
        send_error = await tool.execute(action="send", target=run.run_id, task="follow-up")
        assert "disabled at current delegation depth" in kill_error
        assert "disabled at current delegation depth" in send_error
