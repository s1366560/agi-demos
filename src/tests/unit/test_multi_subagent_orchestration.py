"""Tests for Phase 7.1: Multi-SubAgent orchestration in stream().

Tests that ReActAgent correctly routes to parallel/chain/single SubAgent
execution based on TaskDecomposer results.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.subagent_result import SubAgentResult
from src.infrastructure.agent.subagent.task_decomposer import (
    DecompositionResult,
    SubTask,
)


def _make_subagent(name: str = "test-agent") -> SubAgent:
    return SubAgent.create(
        tenant_id="tenant-1",
        name=name,
        display_name=name.title(),
        system_prompt=f"You are {name}.",
        trigger_description=f"Trigger for {name}",
        trigger_keywords=[name],
    )


def _make_react_agent(**kwargs):
    from src.infrastructure.agent.core.react_agent import ReActAgent

    defaults = {
        "model": "test-model",
        "tools": {"test_tool": MagicMock()},
        "enable_subagent_as_tool": False,  # Test legacy pre-routing behavior
    }
    defaults.update(kwargs)
    return ReActAgent(**defaults)


def _make_result(name: str = "agent", success: bool = True) -> SubAgentResult:
    return SubAgentResult(
        subagent_id=f"id-{name}",
        subagent_name=name,
        summary=f"Result from {name}",
        success=success,
        final_content=f"Content from {name}",
        tokens_used=100,
        tool_calls_count=2,
        execution_time_ms=500,
    )


# === Initialization Tests ===


@pytest.mark.unit
class TestTaskDecomposerInit:
    """Test TaskDecomposer initialization in ReActAgent."""

    def test_no_decomposer_without_llm_client(self):
        agent = _make_react_agent(subagents=[_make_subagent()])
        assert agent._task_decomposer is None

    def test_no_decomposer_without_subagents(self):
        llm = MagicMock()
        agent = _make_react_agent(llm_client=llm)
        assert agent._task_decomposer is None

    def test_decomposer_created_with_llm_and_subagents(self):
        llm = MagicMock()
        sa = _make_subagent("researcher")
        agent = _make_react_agent(llm_client=llm, subagents=[sa])
        assert agent._task_decomposer is not None

    def test_decomposer_has_agent_names(self):
        llm = MagicMock()
        agents = [_make_subagent("researcher"), _make_subagent("coder")]
        agent = _make_react_agent(llm_client=llm, subagents=agents)
        assert agent._task_decomposer._agent_names == ["researcher", "coder"]

    def test_result_aggregator_always_created(self):
        agent = _make_react_agent()
        assert agent._result_aggregator is not None


# === Topological Sort Tests ===


@pytest.mark.unit
class TestTopologicalSort:
    """Test _topological_sort_subtasks."""

    def test_no_dependencies(self):
        from src.infrastructure.agent.core.react_agent import ReActAgent

        tasks = [
            SubTask(id="t1", description="Task 1"),
            SubTask(id="t2", description="Task 2"),
        ]
        result = ReActAgent._topological_sort_subtasks(tasks)
        assert len(result) == 2
        ids = [r.id for r in result]
        assert "t1" in ids and "t2" in ids

    def test_linear_chain(self):
        from src.infrastructure.agent.core.react_agent import ReActAgent

        tasks = [
            SubTask(id="t1", description="Task 1"),
            SubTask(id="t2", description="Task 2", dependencies=("t1",)),
            SubTask(id="t3", description="Task 3", dependencies=("t2",)),
        ]
        result = ReActAgent._topological_sort_subtasks(tasks)
        ids = [r.id for r in result]
        assert ids == ["t1", "t2", "t3"]

    def test_diamond_deps(self):
        from src.infrastructure.agent.core.react_agent import ReActAgent

        tasks = [
            SubTask(id="t1", description="Root"),
            SubTask(id="t2", description="Left", dependencies=("t1",)),
            SubTask(id="t3", description="Right", dependencies=("t1",)),
            SubTask(id="t4", description="Merge", dependencies=("t2", "t3")),
        ]
        result = ReActAgent._topological_sort_subtasks(tasks)
        ids = [r.id for r in result]
        assert ids.index("t1") < ids.index("t2")
        assert ids.index("t1") < ids.index("t3")
        assert ids.index("t2") < ids.index("t4")
        assert ids.index("t3") < ids.index("t4")


# === Stream Orchestration Tests ===


@pytest.mark.unit
class TestStreamOrchestration:
    """Test stream() routes to correct orchestration path."""

    async def _collect_events(self, agent, **kwargs):
        events = []
        async for event in agent.stream(**kwargs):
            events.append(event)
        return events

    async def test_single_subagent_no_decomposer(self):
        """Without decomposer, single SubAgent path is used."""
        sa = _make_subagent("researcher")
        agent = _make_react_agent(subagents=[sa])

        # Mock the match to return the subagent
        with (
            patch.object(agent, "_match_subagent_async") as mock_match,
            patch.object(agent, "_execute_subagent") as mock_exec,
        ):
            from src.infrastructure.agent.core.subagent_router import SubAgentMatch

            mock_match.return_value = SubAgentMatch(
                subagent=sa, confidence=0.9, match_reason="keyword"
            )

            async def mock_events(*a, **kw):
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "complete", "data": {"content": "done"}, "timestamp": "t"}

            mock_exec.return_value = mock_events()

            events = await self._collect_events(
                agent,
                conversation_id="c1",
                user_message="research AI",
                project_id="p1",
                user_id="u1",
                tenant_id="t1",
            )

        # Should have routed event + execute events
        types = [e["type"] for e in events]
        assert "subagent_routed" in types
        mock_exec.assert_called_once()

    async def test_decomposition_triggers_parallel(self):
        """When decomposer returns independent tasks, parallel path is used."""
        llm = MagicMock()
        agents = [_make_subagent("researcher"), _make_subagent("coder")]
        agent = _make_react_agent(llm_client=llm, subagents=agents)

        decomposition = DecompositionResult(
            subtasks=(
                SubTask(id="t1", description="Research", target_subagent="researcher"),
                SubTask(id="t2", description="Code", target_subagent="coder"),
            ),
            reasoning="Independent tasks",
            is_decomposed=True,
        )

        with (
            patch.object(agent, "_match_subagent_async") as mock_match,
            patch.object(agent._task_decomposer, "decompose", return_value=decomposition),
            patch.object(agent, "_execute_parallel") as mock_parallel,
        ):
            from src.infrastructure.agent.core.subagent_router import SubAgentMatch

            mock_match.return_value = SubAgentMatch(
                subagent=agents[0], confidence=0.9, match_reason="keyword"
            )

            async def mock_events(*a, **kw):
                yield {"type": "parallel_started", "data": {}, "timestamp": "t"}
                yield {"type": "complete", "data": {"content": "done"}, "timestamp": "t"}

            mock_parallel.return_value = mock_events()

            await self._collect_events(
                agent,
                conversation_id="c1",
                user_message="research and code",
                project_id="p1",
                user_id="u1",
                tenant_id="t1",
            )

        mock_parallel.assert_called_once()
        # Verify subtasks were passed
        call_kwargs = mock_parallel.call_args[1]
        assert len(call_kwargs["subtasks"]) == 2

    async def test_decomposition_triggers_chain(self):
        """When decomposer returns tasks with linear deps, chain path is used."""
        llm = MagicMock()
        agents = [_make_subagent("researcher"), _make_subagent("writer")]
        agent = _make_react_agent(llm_client=llm, subagents=agents)

        decomposition = DecompositionResult(
            subtasks=(
                SubTask(id="t1", description="Research first", target_subagent="researcher"),
                SubTask(
                    id="t2",
                    description="Write report",
                    target_subagent="writer",
                    dependencies=("t1",),
                ),
            ),
            reasoning="Sequential pipeline",
            is_decomposed=True,
        )

        with (
            patch.object(agent, "_match_subagent_async") as mock_match,
            patch.object(agent._task_decomposer, "decompose", return_value=decomposition),
            patch.object(agent, "_execute_chain") as mock_chain,
        ):
            from src.infrastructure.agent.core.subagent_router import SubAgentMatch

            mock_match.return_value = SubAgentMatch(
                subagent=agents[0], confidence=0.9, match_reason="keyword"
            )

            async def mock_events(*a, **kw):
                yield {"type": "chain_started", "data": {}, "timestamp": "t"}
                yield {"type": "complete", "data": {"content": "done"}, "timestamp": "t"}

            mock_chain.return_value = mock_events()

            await self._collect_events(
                agent,
                conversation_id="c1",
                user_message="research then write",
                project_id="p1",
                user_id="u1",
                tenant_id="t1",
            )

        mock_chain.assert_called_once()

    async def test_decomposition_single_task_falls_to_single(self):
        """When decomposer returns 1 task, single SubAgent path is used."""
        llm = MagicMock()
        sa = _make_subagent("researcher")
        agents = [sa, _make_subagent("coder")]
        agent = _make_react_agent(llm_client=llm, subagents=agents)

        decomposition = DecompositionResult(
            subtasks=(SubTask(id="t1", description="Simple research"),),
            reasoning="Simple task",
            is_decomposed=False,
        )

        with (
            patch.object(agent, "_match_subagent_async") as mock_match,
            patch.object(agent._task_decomposer, "decompose", return_value=decomposition),
            patch.object(agent, "_execute_subagent") as mock_single,
        ):
            from src.infrastructure.agent.core.subagent_router import SubAgentMatch

            mock_match.return_value = SubAgentMatch(
                subagent=sa, confidence=0.9, match_reason="keyword"
            )

            async def mock_events(*a, **kw):
                yield {"type": "complete", "data": {"content": "done"}, "timestamp": "t"}

            mock_single.return_value = mock_events()

            await self._collect_events(
                agent,
                conversation_id="c1",
                user_message="research AI",
                project_id="p1",
                user_id="u1",
                tenant_id="t1",
            )

        mock_single.assert_called_once()

    async def test_decomposition_failure_falls_to_single(self):
        """When decomposer fails, single SubAgent path is used."""
        llm = MagicMock()
        sa = _make_subagent("researcher")
        agents = [sa, _make_subagent("coder")]
        agent = _make_react_agent(llm_client=llm, subagents=agents)

        with (
            patch.object(agent, "_match_subagent_async") as mock_match,
            patch.object(
                agent._task_decomposer,
                "decompose",
                side_effect=RuntimeError("LLM down"),
            ),
            patch.object(agent, "_execute_subagent") as mock_single,
        ):
            from src.infrastructure.agent.core.subagent_router import SubAgentMatch

            mock_match.return_value = SubAgentMatch(
                subagent=sa, confidence=0.9, match_reason="keyword"
            )

            async def mock_events(*a, **kw):
                yield {"type": "complete", "data": {"content": "done"}, "timestamp": "t"}

            mock_single.return_value = mock_events()

            await self._collect_events(
                agent,
                conversation_id="c1",
                user_message="research AI",
                project_id="p1",
                user_id="u1",
                tenant_id="t1",
            )

        mock_single.assert_called_once()

    async def test_only_one_subagent_skips_decomposition(self):
        """With only 1 SubAgent, decomposition is skipped."""
        llm = MagicMock()
        sa = _make_subagent("researcher")
        agent = _make_react_agent(llm_client=llm, subagents=[sa])

        with (
            patch.object(agent, "_match_subagent_async") as mock_match,
            patch.object(agent, "_execute_subagent") as mock_single,
        ):
            from src.infrastructure.agent.core.subagent_router import SubAgentMatch

            mock_match.return_value = SubAgentMatch(
                subagent=sa, confidence=0.9, match_reason="keyword"
            )

            async def mock_events(*a, **kw):
                yield {"type": "complete", "data": {"content": "done"}, "timestamp": "t"}

            mock_single.return_value = mock_events()

            await self._collect_events(
                agent,
                conversation_id="c1",
                user_message="research AI",
                project_id="p1",
                user_id="u1",
                tenant_id="t1",
            )

        # Should go directly to single SubAgent, no decomposition
        mock_single.assert_called_once()
        # _task_decomposer should NOT have been set since only 1 subagent
        # (but it was created since llm_client and subagents were both present)
        # The guard in stream() checks len(self.subagents) > 1

    async def test_forced_subagent_skips_decomposition_and_strips_instruction(self):
        """Forced delegation must bypass decomposition and keep only user task text."""
        llm = MagicMock()
        researcher = _make_subagent("researcher")
        writer = _make_subagent("writer")
        agent = _make_react_agent(llm_client=llm, subagents=[researcher, writer])

        with (
            patch.object(agent._task_decomposer, "decompose") as mock_decompose,
            patch.object(agent, "_execute_subagent") as mock_exec,
        ):
            async def mock_events(*a, **kw):
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "complete", "data": {"content": "done"}, "timestamp": "t"}

            mock_exec.return_value = mock_events()

            events = await self._collect_events(
                agent,
                conversation_id="c1",
                user_message='[System Instruction: Delegate this task strictly to SubAgent "researcher"] write summary',
                project_id="p1",
                user_id="u1",
                tenant_id="t1",
            )

        mock_decompose.assert_not_called()
        mock_exec.assert_called_once()
        assert mock_exec.call_args.kwargs["subagent"] == researcher
        assert mock_exec.call_args.kwargs["user_message"] == "write summary"
        assert any(event["type"] == "subagent_routed" for event in events)


# === Sessionized Runtime Tests ===


@pytest.mark.unit
class TestSessionizedRuntime:
    """Test detached session runtime behavior."""

    async def _wait_session_finish(self, agent, run_id: str) -> None:
        for _ in range(50):
            if run_id not in agent._subagent_session_tasks:
                return
            await asyncio.sleep(0.01)

    async def test_launch_session_marks_failed_when_subagent_result_failed(self):
        sa = _make_subagent("researcher")
        agent = _make_react_agent(subagents=[sa], enable_subagent_as_tool=True)

        run = agent._subagent_run_registry.create_run(
            conversation_id="c1",
            subagent_name=sa.name,
            task="Investigate issue",
            run_id="run-1",
        )
        agent._subagent_run_registry.mark_running("c1", run.run_id)

        async def _mock_execute_subagent(*args, **kwargs):
            yield {
                "type": "complete",
                "data": {
                    "content": "failed result",
                    "subagent_result": {
                        "success": False,
                        "summary": "failed summary",
                        "error": "subagent failed",
                        "execution_time_ms": 12,
                        "tokens_used": 5,
                    },
                },
                "timestamp": "t",
            }

        with patch.object(agent, "_execute_subagent", side_effect=_mock_execute_subagent):
            await agent._launch_subagent_session(
                run_id=run.run_id,
                subagent=sa,
                user_message="Investigate issue",
                conversation_id="c1",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
            )
            await self._wait_session_finish(agent, run.run_id)

        final = agent._subagent_run_registry.get_run("c1", run.run_id)
        assert final is not None
        assert final.status.value == "failed"
        assert final.error == "subagent failed"
        assert final.metadata.get("announce_status") == "delivered"
        announce_payload = final.metadata.get("announce_payload")
        assert isinstance(announce_payload, dict)
        assert announce_payload["status"] == "failed"
        assert announce_payload["outcome"] == "error"
        assert announce_payload["result"] == "failed summary"
        assert announce_payload["notes"] == "subagent failed"

    async def test_launch_session_marks_completed_on_success(self):
        sa = _make_subagent("researcher")
        agent = _make_react_agent(subagents=[sa], enable_subagent_as_tool=True)

        run = agent._subagent_run_registry.create_run(
            conversation_id="c1",
            subagent_name=sa.name,
            task="Do work",
            run_id="run-2",
        )
        agent._subagent_run_registry.mark_running("c1", run.run_id)

        async def _mock_execute_subagent(*args, **kwargs):
            yield {
                "type": "complete",
                "data": {
                    "content": "all good",
                    "subagent_result": {
                        "success": True,
                        "summary": "done",
                        "execution_time_ms": 10,
                        "tokens_used": 7,
                    },
                },
                "timestamp": "t",
            }

        with patch.object(agent, "_execute_subagent", side_effect=_mock_execute_subagent):
            await agent._launch_subagent_session(
                run_id=run.run_id,
                subagent=sa,
                user_message="Do work",
                conversation_id="c1",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
            )
            await self._wait_session_finish(agent, run.run_id)

        final = agent._subagent_run_registry.get_run("c1", run.run_id)
        assert final is not None
        assert final.status.value == "completed"
        assert final.summary == "done"
        assert final.metadata.get("announce_status") == "delivered"
        announce_payload = final.metadata.get("announce_payload")
        assert isinstance(announce_payload, dict)
        assert announce_payload["status"] == "completed"
        assert announce_payload["outcome"] == "success"
        assert announce_payload["result"] == "done"
        assert announce_payload["tokens_used"] == 7

    async def test_launch_session_marks_timed_out_when_timeout_exceeded(self):
        sa = _make_subagent("researcher")
        agent = _make_react_agent(subagents=[sa], enable_subagent_as_tool=True)

        run = agent._subagent_run_registry.create_run(
            conversation_id="c1",
            subagent_name=sa.name,
            task="Long running task",
            run_id="run-timeout",
            metadata={"run_timeout_seconds": 0.2},
        )
        agent._subagent_run_registry.mark_running("c1", run.run_id)

        async def _mock_execute_subagent(*args, **kwargs):
            await asyncio.sleep(0.6)
            yield {
                "type": "complete",
                "data": {
                    "content": "should not complete",
                    "subagent_result": {
                        "success": True,
                        "summary": "late completion",
                        "execution_time_ms": 1200,
                        "tokens_used": 7,
                    },
                },
                "timestamp": "t",
            }

        with patch.object(agent, "_execute_subagent", side_effect=_mock_execute_subagent):
            await agent._launch_subagent_session(
                run_id=run.run_id,
                subagent=sa,
                user_message="Long running task",
                conversation_id="c1",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
            )
            await self._wait_session_finish(agent, run.run_id)

        final = agent._subagent_run_registry.get_run("c1", run.run_id)
        assert final is not None
        assert final.status.value == "timed_out"
        assert "timeout_seconds" in final.metadata
        assert final.metadata.get("announce_status") == "delivered"
        announce_payload = final.metadata.get("announce_payload")
        assert isinstance(announce_payload, dict)
        assert announce_payload["status"] == "timed_out"
        assert announce_payload["outcome"] == "timeout"
        assert announce_payload["notes"]

    async def test_launch_session_retries_completion_announce_metadata(self):
        sa = _make_subagent("researcher")
        agent = _make_react_agent(subagents=[sa], enable_subagent_as_tool=True)

        run = agent._subagent_run_registry.create_run(
            conversation_id="c1",
            subagent_name=sa.name,
            task="Do work",
            run_id="run-announce-retry",
        )
        agent._subagent_run_registry.mark_running("c1", run.run_id)

        async def _mock_execute_subagent(*args, **kwargs):
            yield {
                "type": "complete",
                "data": {
                    "content": "all good",
                    "subagent_result": {
                        "success": True,
                        "summary": "done",
                        "execution_time_ms": 10,
                        "tokens_used": 7,
                    },
                },
                "timestamp": "t",
            }

        original_attach = agent._subagent_run_registry.attach_metadata
        announce_attach_calls = {"count": 0}

        def _flaky_attach(*args, **kwargs):
            metadata = kwargs.get("metadata")
            if metadata is None and len(args) >= 3:
                metadata = args[2]
            if isinstance(metadata, dict) and "announce_payload" in metadata:
                announce_attach_calls["count"] += 1
                if announce_attach_calls["count"] == 1:
                    return None
            return original_attach(*args, **kwargs)

        with (
            patch.object(agent, "_execute_subagent", side_effect=_mock_execute_subagent),
            patch.object(agent._subagent_run_registry, "attach_metadata", side_effect=_flaky_attach),
        ):
            await agent._launch_subagent_session(
                run_id=run.run_id,
                subagent=sa,
                user_message="Do work",
                conversation_id="c1",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
            )
            await self._wait_session_finish(agent, run.run_id)

        final = agent._subagent_run_registry.get_run("c1", run.run_id)
        assert final is not None
        assert final.metadata.get("announce_status") == "delivered"
        assert final.metadata.get("announce_attempt_count") == 2
        announce_events = final.metadata.get("announce_events")
        assert isinstance(announce_events, list)
        announce_types = [event.get("type") for event in announce_events]
        assert "completion_retry" in announce_types
        assert "completion_delivered" in announce_types

    async def test_launch_session_respects_subagent_lane_concurrency(self):
        sa = _make_subagent("researcher")
        agent = _make_react_agent(
            subagents=[sa],
            enable_subagent_as_tool=True,
            max_subagent_lane_concurrency=1,
        )

        run1 = agent._subagent_run_registry.create_run(
            conversation_id="c1",
            subagent_name=sa.name,
            task="Task one",
            run_id="lane-run-1",
        )
        run2 = agent._subagent_run_registry.create_run(
            conversation_id="c1",
            subagent_name=sa.name,
            task="Task two",
            run_id="lane-run-2",
        )
        agent._subagent_run_registry.mark_running("c1", run1.run_id)
        agent._subagent_run_registry.mark_running("c1", run2.run_id)

        active_sessions = 0
        max_parallel = 0

        async def _mock_execute_subagent(*args, **kwargs):
            nonlocal active_sessions, max_parallel
            active_sessions += 1
            max_parallel = max(max_parallel, active_sessions)
            try:
                await asyncio.sleep(0.05)
                yield {
                    "type": "complete",
                    "data": {
                        "content": "ok",
                        "subagent_result": {
                            "success": True,
                            "summary": "ok",
                            "execution_time_ms": 10,
                            "tokens_used": 1,
                        },
                    },
                    "timestamp": "t",
                }
            finally:
                active_sessions -= 1

        with patch.object(agent, "_execute_subagent", side_effect=_mock_execute_subagent):
            await agent._launch_subagent_session(
                run_id=run1.run_id,
                subagent=sa,
                user_message="Task one",
                conversation_id="c1",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
            )
            await agent._launch_subagent_session(
                run_id=run2.run_id,
                subagent=sa,
                user_message="Task two",
                conversation_id="c1",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
            )
            await self._wait_session_finish(agent, run1.run_id)
            await self._wait_session_finish(agent, run2.run_id)

        final1 = agent._subagent_run_registry.get_run("c1", run1.run_id)
        final2 = agent._subagent_run_registry.get_run("c1", run2.run_id)
        assert final1 is not None and final1.status.value == "completed"
        assert final2 is not None and final2.status.value == "completed"
        assert max_parallel == 1
        assert "lane_wait_ms" in final2.metadata

    async def test_launch_session_emits_lifecycle_hooks(self):
        sa = _make_subagent("researcher")
        hook_events: list[dict] = []

        async def _hook(event: dict) -> None:
            hook_events.append(event)

        agent = _make_react_agent(
            subagents=[sa],
            enable_subagent_as_tool=True,
            subagent_lifecycle_hook=_hook,
        )

        run = agent._subagent_run_registry.create_run(
            conversation_id="c1",
            subagent_name=sa.name,
            task="Hooked task",
            run_id="run-hook",
        )
        agent._subagent_run_registry.mark_running("c1", run.run_id)

        async def _mock_execute_subagent(*args, **kwargs):
            yield {
                "type": "complete",
                "data": {
                    "content": "ok",
                    "subagent_result": {
                        "success": True,
                        "summary": "done",
                        "execution_time_ms": 10,
                        "tokens_used": 1,
                    },
                },
                "timestamp": "t",
            }

        with patch.object(agent, "_execute_subagent", side_effect=_mock_execute_subagent):
            await agent._launch_subagent_session(
                run_id=run.run_id,
                subagent=sa,
                user_message="Hooked task",
                conversation_id="c1",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
                spawn_mode="session",
                thread_requested=True,
            )
            await self._wait_session_finish(agent, run.run_id)

        event_types = [event["type"] for event in hook_events]
        assert event_types[0] == "subagent_spawning"
        assert "subagent_spawned" in event_types
        assert event_types[-1] == "subagent_ended"
        ended_event = hook_events[-1]
        assert ended_event["run_id"] == run.run_id
        assert ended_event["status"] == "completed"

    async def test_launch_session_ignores_lifecycle_hook_failures(self):
        sa = _make_subagent("researcher")

        async def _failing_hook(event: dict) -> None:
            raise RuntimeError("hook down")

        agent = _make_react_agent(
            subagents=[sa],
            enable_subagent_as_tool=True,
            subagent_lifecycle_hook=_failing_hook,
        )

        run = agent._subagent_run_registry.create_run(
            conversation_id="c1",
            subagent_name=sa.name,
            task="Task",
            run_id="run-hook-fail",
        )
        agent._subagent_run_registry.mark_running("c1", run.run_id)

        async def _mock_execute_subagent(*args, **kwargs):
            yield {
                "type": "complete",
                "data": {
                    "content": "ok",
                    "subagent_result": {
                        "success": True,
                        "summary": "done",
                        "execution_time_ms": 10,
                        "tokens_used": 1,
                    },
                },
                "timestamp": "t",
            }

        with patch.object(agent, "_execute_subagent", side_effect=_mock_execute_subagent):
            await agent._launch_subagent_session(
                run_id=run.run_id,
                subagent=sa,
                user_message="Task",
                conversation_id="c1",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
            )
            await self._wait_session_finish(agent, run.run_id)

        final = agent._subagent_run_registry.get_run("c1", run.run_id)
        assert final is not None
        assert final.status.value == "completed"


@pytest.mark.unit
class TestNestedSessionToolInjection:
    """Test nested subagent tool injection behavior by delegation depth."""

    async def test_execute_subagent_injects_nested_session_tools_at_depth_one(self):
        researcher = _make_subagent("researcher")
        coder = _make_subagent("coder")
        agent = _make_react_agent(
            subagents=[researcher, coder],
            enable_subagent_as_tool=True,
            max_subagent_delegation_depth=2,
        )
        captured_tool_names: list[str] = []

        class FakeSubAgentProcess:
            def __init__(self, *args, **kwargs) -> None:
                nonlocal captured_tool_names
                tools = kwargs["tools"]
                captured_tool_names = [tool.name for tool in tools]
                self.result = _make_result(kwargs["subagent"].name)

            async def execute(self):
                if False:
                    yield {}

        with patch("src.infrastructure.agent.subagent.process.SubAgentProcess", FakeSubAgentProcess):
            events = []
            async for event in agent._execute_subagent(
                subagent=researcher,
                user_message="delegate and monitor",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
                conversation_id="c1",
                delegation_depth=1,
            ):
                events.append(event)

        assert "delegate_to_subagent" in captured_tool_names
        assert "subagents" in captured_tool_names
        assert "sessions_list" in captured_tool_names
        assert "sessions_history" in captured_tool_names
        assert "sessions_wait" in captured_tool_names
        assert "sessions_timeline" in captured_tool_names
        assert "sessions_overview" in captured_tool_names
        assert events[-1]["type"] == "complete"

    async def test_execute_subagent_skips_nested_tools_at_depth_limit(self):
        researcher = _make_subagent("researcher")
        coder = _make_subagent("coder")
        agent = _make_react_agent(
            subagents=[researcher, coder],
            enable_subagent_as_tool=True,
            max_subagent_delegation_depth=2,
        )
        captured_tool_names: list[str] = []

        class FakeSubAgentProcess:
            def __init__(self, *args, **kwargs) -> None:
                nonlocal captured_tool_names
                tools = kwargs["tools"]
                captured_tool_names = [tool.name for tool in tools]
                self.result = SimpleNamespace(
                    final_content="ok",
                    to_event_data=lambda: {"summary": "ok", "success": True},
                )

            async def execute(self):
                if False:
                    yield {}

        with patch("src.infrastructure.agent.subagent.process.SubAgentProcess", FakeSubAgentProcess):
            events = []
            async for event in agent._execute_subagent(
                subagent=researcher,
                user_message="depth limited",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
                conversation_id="c1",
                delegation_depth=2,
            ):
                events.append(event)

        assert "delegate_to_subagent" not in captured_tool_names
        assert "subagents" not in captured_tool_names
        assert "sessions_list" not in captured_tool_names
        assert events[-1]["type"] == "complete"


# === _execute_parallel Tests ===


@pytest.mark.unit
class TestExecuteParallel:
    """Test _execute_parallel method."""

    async def test_parallel_emits_lifecycle_events(self):
        """Parallel execution emits started and completed events."""
        agents = [_make_subagent("researcher"), _make_subagent("coder")]
        agent = _make_react_agent(subagents=agents)

        subtasks = [
            SubTask(id="t1", description="Research", target_subagent="researcher"),
            SubTask(id="t2", description="Code", target_subagent="coder"),
        ]

        with patch(
            "src.infrastructure.agent.subagent.parallel_scheduler.ParallelScheduler"
        ) as MockScheduler:

            async def mock_execute(*a, **kw):
                yield {
                    "type": "subtask_started",
                    "data": {"task_id": "t1"},
                    "timestamp": "t",
                }
                yield {
                    "type": "subtask_completed",
                    "data": {"task_id": "t1", "result": _make_result("researcher")},
                    "timestamp": "t",
                }

            MockScheduler.return_value.execute = mock_execute

            events = []
            async for event in agent._execute_parallel(
                subtasks=subtasks,
                user_message="Do both",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
            ):
                events.append(event)

        types = [e["type"] for e in events]
        assert types[0] == "parallel_started"
        assert "parallel_completed" in types
        assert "complete" in types
        # Check parallel_started has task_count
        assert events[0]["data"]["task_count"] == 2


# === _execute_chain Tests ===


@pytest.mark.unit
class TestExecuteChain:
    """Test _execute_chain method."""

    async def test_chain_emits_lifecycle_events(self):
        """Chain execution delegates to SubAgentChain."""
        agents = [_make_subagent("researcher"), _make_subagent("writer")]
        agent = _make_react_agent(subagents=agents)

        subtasks = [
            SubTask(id="t1", description="Research", target_subagent="researcher"),
            SubTask(
                id="t2",
                description="Write",
                target_subagent="writer",
                dependencies=("t1",),
            ),
        ]

        with patch(
            "src.infrastructure.agent.subagent.chain.SubAgentChain"
        ) as MockChain:
            mock_chain_instance = MockChain.return_value

            from src.infrastructure.agent.subagent.chain import ChainResult

            mock_chain_instance.result = ChainResult(
                steps_completed=2,
                total_steps=2,
                final_summary="Chain done",
                execution_time_ms=1000,
            )

            async def mock_execute(*a, **kw):
                yield {"type": "chain_started", "data": {}, "timestamp": "t"}
                yield {"type": "chain_step_completed", "data": {}, "timestamp": "t"}

            mock_chain_instance.execute = mock_execute

            events = []
            async for event in agent._execute_chain(
                subtasks=subtasks,
                user_message="Research then write",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
            ):
                events.append(event)

        types = [e["type"] for e in events]
        assert "chain_started" in types
        assert "complete" in types
        # Final complete should have chain content
        complete_event = next(e for e in events if e["type"] == "complete")
        assert complete_event["data"]["orchestration_mode"] == "chain"


# === _execute_background Tests ===


@pytest.mark.unit
class TestExecuteBackground:
    """Test _execute_background method."""

    async def test_background_emits_launch_event(self):
        """Background launch emits confirmation event."""
        sa = _make_subagent("researcher")
        agent = _make_react_agent(subagents=[sa])

        with patch.object(
            agent._background_executor, "launch", return_value="bg-abc123"
        ):
            events = []
            async for event in agent._execute_background(
                subagent=sa,
                user_message="Long research task",
                conversation_id="c1",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
            ):
                events.append(event)

        types = [e["type"] for e in events]
        assert "background_launched" in types
        assert "complete" in types

        launch_event = next(e for e in events if e["type"] == "background_launched")
        assert launch_event["data"]["execution_id"] == "bg-abc123"
        assert launch_event["data"]["subagent_name"] == "Researcher"

        complete_event = next(e for e in events if e["type"] == "complete")
        assert complete_event["data"]["orchestration_mode"] == "background"
