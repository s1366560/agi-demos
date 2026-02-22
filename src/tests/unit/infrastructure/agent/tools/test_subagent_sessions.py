"""Tests for session-oriented SubAgent tools."""

import json

import pytest

from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.tools.subagent_sessions import (
    SessionsHistoryTool,
    SessionsListTool,
    SessionsSendTool,
    SessionsSpawnTool,
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

    async def test_sessions_list_and_history(self):
        registry = SubAgentRunRegistry()
        run1 = registry.create_run("conv-1", "researcher", "task-1")
        registry.mark_running("conv-1", run1.run_id)
        run2 = registry.create_run("conv-1", "coder", "task-2")
        registry.mark_running("conv-1", run2.run_id)
        registry.mark_completed("conv-1", run2.run_id, summary="done")

        list_tool = SessionsListTool(registry, "conv-1")
        active_data = json.loads(await list_tool.execute(status="active"))
        assert active_data["count"] == 1
        assert active_data["runs"][0]["run_id"] == run1.run_id

        history_tool = SessionsHistoryTool(registry, "conv-1")
        history_data = json.loads(await history_tool.execute(limit=10))
        assert history_data["count"] == 2

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

        async def _spawn(subagent_name: str, task: str, run_id: str) -> str:
            nonlocal attempts
            attempts += 1
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
