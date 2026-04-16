"""Unit tests for GoalEvaluator goal-completion evaluation."""

import json
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus
from src.infrastructure.agent.processor import ToolDefinition
from src.infrastructure.agent.processor.goal_evaluator import (
    GoalEvaluator,
    TaskStateUnavailableError,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.result import ToolResult


def create_todoread_tool(tasks: list[dict[str, Any]]) -> ToolDefinition:
    """Create a todoread ToolDefinition returning fixed tasks."""

    async def execute(**kwargs: Any) -> str:
        return json.dumps(
            {
                "session_id": kwargs.get("session_id", "session-test"),
                "total_count": len(tasks),
                "todos": tasks,
            }
        )

    return ToolDefinition(
        name="todoread",
        description="Read todos",
        parameters={"type": "object", "properties": {}},
        execute=execute,
    )


def create_todoread_toolinfo_tool(tasks: list[dict[str, Any]]) -> ToolDefinition:
    """Create ToolInfo-backed todoread ToolDefinition for compatibility tests."""

    async def toolinfo_execute(ctx: ToolContext, *, status: str | None = None) -> ToolResult:
        assert status is None
        assert ctx.session_id == "session-1"
        assert ctx.conversation_id == "session-1"
        return ToolResult(
            output=json.dumps(
                {
                    "session_id": ctx.session_id,
                    "conversation_id": ctx.conversation_id,
                    "total_count": len(tasks),
                    "todos": tasks,
                }
            )
        )

    tool_info = ToolInfo(
        name="todoread",
        description="Read todos",
        parameters={"type": "object", "properties": {}},
        execute=toolinfo_execute,
    )

    return ToolDefinition(
        name="todoread",
        description="Read todos",
        parameters={"type": "object", "properties": {}},
        execute=AsyncMock(return_value="wrapper_should_not_be_called"),
        _tool_instance=tool_info,
    )


@pytest.mark.unit
class TestProcessorGoalCompletion:
    """Goal-completion behavior for GoalEvaluator."""

    @pytest.fixture
    def evaluator_with_tasks(self):
        """Factory: build a GoalEvaluator with a todoread tool returning *tasks*."""

        def _factory(tasks: list[dict[str, Any]]) -> GoalEvaluator:
            tool = create_todoread_tool(tasks)
            tools = {"todoread": tool}
            return GoalEvaluator(llm_client=None, tools=tools)

        return _factory

    @pytest.mark.asyncio
    async def test_task_goal_pending_returns_not_complete(self, evaluator_with_tasks):
        evaluator = evaluator_with_tasks(
            [
                {"id": "t1", "status": "completed"},
                {"id": "t2", "status": "in_progress"},
            ]
        )

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "finish task"}],
        )

        assert result.achieved is False
        assert result.should_stop is False
        assert result.source == "tasks"
        assert result.pending_tasks == 1

    @pytest.mark.asyncio
    async def test_task_goal_all_terminal_success_returns_complete(self, evaluator_with_tasks):
        evaluator = evaluator_with_tasks(
            [
                {"id": "t1", "status": "completed"},
                {"id": "t2", "status": "cancelled"},
            ]
        )

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "finish task"}],
        )

        assert result.achieved is True
        assert result.source == "tasks"

    @pytest.mark.asyncio
    async def test_goal_completion_fails_closed_when_task_state_is_unverifiable(self) -> None:
        async def execute(**kwargs: Any) -> str:
            return '{"todos":[42]}'

        tool = ToolDefinition(
            name="todoread",
            description="Read todos",
            parameters={"type": "object", "properties": {}},
            execute=execute,
        )
        evaluator = GoalEvaluator(llm_client=AsyncMock(), tools={"todoread": tool})
        evaluator._llm_client.generate = AsyncMock(  # type: ignore[union-attr]
            return_value={"content": '{"goal_achieved": true, "reason": "all done"}'}
        )

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "finish task"}],
        )

        assert result.achieved is False
        assert result.should_stop is True
        assert result.source == "tasks"
        assert result.reason == "Unable to verify task completion state"

    @pytest.mark.asyncio
    async def test_task_goal_failed_returns_stop(self, evaluator_with_tasks):
        evaluator = evaluator_with_tasks(
            [
                {"id": "t1", "status": "failed"},
                {"id": "t2", "status": "completed"},
            ]
        )

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "finish task"}],
        )

        assert result.achieved is False
        assert result.should_stop is True
        assert result.source == "tasks"

    @pytest.mark.asyncio
    async def test_task_goal_reads_toolinfo_todoread_with_tool_context(self) -> None:
        tool = create_todoread_toolinfo_tool(
            [
                {"id": "t1", "status": "completed"},
                {"id": "t2", "status": "in_progress"},
            ]
        )
        evaluator = GoalEvaluator(llm_client=None, tools={"todoread": tool})

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "finish task"}],
        )

        assert result.achieved is False
        assert result.source == "tasks"
        assert result.pending_tasks == 1
        cast(AsyncMock, tool.execute).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_task_goal_supports_toolresult_payload(self) -> None:
        async def execute(**kwargs: Any) -> ToolResult:
            return ToolResult(
                output=json.dumps(
                    {
                        "session_id": kwargs.get("session_id", "session-test"),
                        "total_count": 1,
                        "todos": [{"id": "t1", "status": "completed"}],
                    }
                )
            )

        tool = ToolDefinition(
            name="todoread",
            description="Read todos",
            parameters={"type": "object", "properties": {}},
            execute=execute,
        )
        evaluator = GoalEvaluator(llm_client=None, tools={"todoread": tool})

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "finish task"}],
        )

        assert result.achieved is True
        assert result.source == "tasks"

    @pytest.mark.asyncio
    async def test_task_completion_gate_returns_none_without_tasks(self, evaluator_with_tasks):
        evaluator = evaluator_with_tasks([])

        result = await evaluator.evaluate_task_completion_gate(session_id="session-1")

        assert result is None

    @pytest.mark.asyncio
    async def test_task_completion_gate_uses_persisted_tasks(self, evaluator_with_tasks):
        evaluator = evaluator_with_tasks(
            [
                {"id": "t1", "status": "completed"},
                {"id": "t2", "status": "pending"},
            ]
        )

        result = await evaluator.evaluate_task_completion_gate(session_id="session-1")

        assert result is not None
        assert result.achieved is False
        assert result.source == "tasks"
        assert result.pending_tasks == 1

    @pytest.mark.asyncio
    async def test_task_completion_gate_fails_closed_when_task_state_unavailable(self) -> None:
        async def execute(**kwargs: Any) -> str:
            raise TaskStateUnavailableError("boom")

        tool = ToolDefinition(
            name="todoread",
            description="Read todos",
            parameters={"type": "object", "properties": {}},
            execute=execute,
        )
        evaluator = GoalEvaluator(llm_client=None, tools={"todoread": tool})

        result = await evaluator.evaluate_task_completion_gate(session_id="session-1")

        assert result is not None
        assert result.achieved is False
        assert result.should_stop is True
        assert result.source == "tasks"
        assert result.reason == "Unable to verify task completion state"

    @pytest.mark.asyncio
    async def test_task_completion_gate_fails_closed_when_payload_omits_todos(self) -> None:
        async def execute(**kwargs: Any) -> str:
            return "{}"

        tool = ToolDefinition(
            name="todoread",
            description="Read todos",
            parameters={"type": "object", "properties": {}},
            execute=execute,
        )
        evaluator = GoalEvaluator(llm_client=None, tools={"todoread": tool})

        result = await evaluator.evaluate_task_completion_gate(session_id="session-1")

        assert result is not None
        assert result.achieved is False
        assert result.should_stop is True
        assert result.source == "tasks"
        assert result.reason == "Unable to verify task completion state"

    @pytest.mark.asyncio
    async def test_task_completion_gate_fails_closed_on_parseable_error_payload(self) -> None:
        async def execute(**kwargs: Any) -> ToolResult:
            return ToolResult(
                output='{"error":"Task storage not configured","todos":[]}',
                is_error=True,
            )

        tool = ToolDefinition(
            name="todoread",
            description="Read todos",
            parameters={"type": "object", "properties": {}},
            execute=execute,
        )
        evaluator = GoalEvaluator(llm_client=None, tools={"todoread": tool})

        result = await evaluator.evaluate_task_completion_gate(session_id="session-1")

        assert result is not None
        assert result.achieved is False
        assert result.should_stop is True
        assert result.source == "tasks"
        assert result.reason == "Unable to verify task completion state"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            '{"todos":[{"status":"completed"}]}',
            '{"todos":[42]}',
            '{"todos":[{"id":"t1","status":"completed"},42]}',
            '{"todos":[{"id":null,"status":"completed"}]}',
            '{"todos":[{"id":"t1","status":null}]}',
        ],
    )
    async def test_task_completion_gate_fails_closed_on_malformed_todo_entries(
        self, payload: str
    ) -> None:
        async def execute(**kwargs: Any) -> str:
            return payload

        tool = ToolDefinition(
            name="todoread",
            description="Read todos",
            parameters={"type": "object", "properties": {}},
            execute=execute,
        )
        evaluator = GoalEvaluator(llm_client=None, tools={"todoread": tool})

        result = await evaluator.evaluate_task_completion_gate(session_id="session-1")

        assert result is not None
        assert result.achieved is False
        assert result.should_stop is True
        assert result.source == "tasks"
        assert result.reason == "Unable to verify task completion state"

    @pytest.mark.asyncio
    async def test_workspace_authority_uses_root_goal_task_instead_of_todoread(self) -> None:
        task = WorkspaceTask(
            id="root-1",
            workspace_id="ws-1",
            title="Root goal",
            created_by="user-1",
            status=WorkspaceTaskStatus.IN_PROGRESS,
            metadata={"task_role": "goal_root"},
        )

        evaluator = GoalEvaluator(
            llm_client=None,
            tools={"todoread": create_todoread_tool([{"id": "t1", "status": "completed"}])},
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )
        session = AsyncMock()

        class _Repo:
            def __init__(self, db: Any) -> None:
                del db

            async def find_by_id(self, task_id: str) -> WorkspaceTask | None:
                assert task_id == "root-1"
                return task

        with (
            patch(
                "src.infrastructure.agent.processor.goal_evaluator.async_session_factory"
            ) as session_factory,
            patch(
                "src.infrastructure.agent.processor.goal_evaluator.SqlWorkspaceTaskRepository",
                _Repo,
            ),
        ):
            session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await evaluator.evaluate_goal_completion(
                session_id="session-1",
                messages=[{"role": "user", "content": "finish task"}],
            )

        assert result.achieved is False
        assert result.source == "workspace_tasks"
        assert result.reason == "Workspace root goal task is not complete"

    @pytest.mark.asyncio
    async def test_workspace_authority_requires_goal_evidence(self) -> None:
        task = WorkspaceTask(
            id="root-1",
            workspace_id="ws-1",
            title="Root goal",
            created_by="user-1",
            status=WorkspaceTaskStatus.DONE,
            metadata={"task_role": "goal_root"},
        )

        evaluator = GoalEvaluator(
            llm_client=None,
            tools={},
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )
        session = AsyncMock()

        class _Repo:
            def __init__(self, db: Any) -> None:
                del db

            async def find_by_id(self, task_id: str) -> WorkspaceTask | None:
                assert task_id == "root-1"
                return task

        with (
            patch(
                "src.infrastructure.agent.processor.goal_evaluator.async_session_factory"
            ) as session_factory,
            patch(
                "src.infrastructure.agent.processor.goal_evaluator.SqlWorkspaceTaskRepository",
                _Repo,
            ),
        ):
            session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await evaluator.evaluate_goal_completion(
                session_id="session-1",
                messages=[{"role": "user", "content": "finish task"}],
            )

        assert result.achieved is False
        assert result.should_stop is True
        assert result.source == "workspace_tasks"

    @pytest.mark.asyncio
    async def test_workspace_authority_blocks_on_replan_required(self) -> None:
        task = WorkspaceTask(
            id="root-1",
            workspace_id="ws-1",
            title="Root goal",
            created_by="user-1",
            status=WorkspaceTaskStatus.IN_PROGRESS,
            metadata={
                "task_role": "goal_root",
                "remediation_status": "replan_required",
                "remediation_summary": "1 child task blocked; root goal requires replan or intervention",
            },
        )

        evaluator = GoalEvaluator(
            llm_client=None,
            tools={},
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )
        session = AsyncMock()

        class _Repo:
            def __init__(self, db: Any) -> None:
                del db

            async def find_by_id(self, task_id: str) -> WorkspaceTask | None:
                assert task_id == "root-1"
                return task

        with (
            patch(
                "src.infrastructure.agent.processor.goal_evaluator.async_session_factory"
            ) as session_factory,
            patch(
                "src.infrastructure.agent.processor.goal_evaluator.SqlWorkspaceTaskRepository",
                _Repo,
            ),
        ):
            session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await evaluator.evaluate_goal_completion(
                session_id="session-1",
                messages=[{"role": "user", "content": "finish task"}],
            )

        assert result.achieved is False
        assert result.should_stop is True
        assert result.source == "workspace_tasks"
        assert "requires replan" in result.reason

    @pytest.mark.asyncio
    async def test_workspace_authority_ready_for_completion_keeps_loop_open(self) -> None:
        task = WorkspaceTask(
            id="root-1",
            workspace_id="ws-1",
            title="Root goal",
            created_by="user-1",
            status=WorkspaceTaskStatus.IN_PROGRESS,
            metadata={
                "task_role": "goal_root",
                "remediation_status": "ready_for_completion",
                "remediation_summary": "All child tasks are done; root goal should now validate completion evidence",
            },
        )

        evaluator = GoalEvaluator(
            llm_client=None,
            tools={},
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )
        session = AsyncMock()

        class _Repo:
            def __init__(self, db: Any) -> None:
                del db

            async def find_by_id(self, task_id: str) -> WorkspaceTask | None:
                assert task_id == "root-1"
                return task

        with (
            patch(
                "src.infrastructure.agent.processor.goal_evaluator.async_session_factory"
            ) as session_factory,
            patch(
                "src.infrastructure.agent.processor.goal_evaluator.SqlWorkspaceTaskRepository",
                _Repo,
            ),
        ):
            session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
            session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await evaluator.evaluate_goal_completion(
                session_id="session-1",
                messages=[{"role": "user", "content": "finish task"}],
            )

        assert result.achieved is False
        assert result.should_stop is False
        assert result.source == "workspace_tasks"
        assert "validate completion evidence" in result.reason

    @pytest.mark.asyncio
    async def test_no_tasks_uses_llm_self_check_true(self, evaluator_with_tasks):
        evaluator = evaluator_with_tasks([])
        evaluator._llm_client = AsyncMock()
        evaluator._llm_client.generate = AsyncMock(
            return_value={"content": '{"goal_achieved": true, "reason": "all done"}'}
        )

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[
                {"role": "user", "content": "please finish"},
                {"role": "assistant", "content": "working"},
            ],
        )

        assert result.achieved is True
        assert result.source == "llm_self_check"

    @pytest.mark.asyncio
    async def test_no_tasks_invalid_self_check_defaults_not_complete(self, evaluator_with_tasks):
        evaluator = evaluator_with_tasks([])
        evaluator._llm_client = AsyncMock()
        evaluator._llm_client.generate = AsyncMock(return_value={"content": "not json"})

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[
                {"role": "user", "content": "please finish"},
                {"role": "assistant", "content": "still working"},
            ],
        )

        assert result.achieved is False
        assert result.source == "assistant_text"

    @pytest.mark.asyncio
    async def test_no_tasks_plain_text_self_check_is_parsed(self, evaluator_with_tasks):
        evaluator = evaluator_with_tasks([])
        evaluator._llm_client = AsyncMock()
        evaluator._llm_client.generate = AsyncMock(
            return_value={
                "content": "goal_achieved: false\nreason: still implementing remaining items"
            }
        )

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[
                {"role": "user", "content": "please finish"},
                {"role": "assistant", "content": "working"},
            ],
        )

        assert result.achieved is False
        assert result.source == "llm_self_check"
        assert "remaining" in result.reason.lower()

    def test_extract_goal_json_handles_braces_in_string(self):
        evaluator = GoalEvaluator(llm_client=None, tools={})
        parsed = evaluator._extract_goal_json(
            'prefix {"goal_achieved": true, "reason": "keep } brace"} suffix'
        )
        assert parsed is not None
        assert parsed.get("goal_achieved") is True

    def test_extract_goal_from_plain_text_prefers_explicit_negative(self):
        evaluator = GoalEvaluator(llm_client=None, tools={})
        parsed = evaluator._extract_goal_from_plain_text(
            "goal not achieved yet; some sub-goal achieved already"
        )
        assert parsed is not None
        assert parsed.get("goal_achieved") is False

    def test_extract_goal_from_plain_text_reason_is_line_bounded(self):
        evaluator = GoalEvaluator(llm_client=None, tools={})
        parsed = evaluator._extract_goal_from_plain_text(
            "goal_achieved: true\nreason: done line one\nextra line"
        )
        assert parsed is not None
        assert parsed.get("goal_achieved") is True
        assert parsed.get("reason") == "done line one"
