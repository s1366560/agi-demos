"""Unit tests for GoalEvaluator goal-completion evaluation."""

import json
import logging
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.processor import ToolDefinition
from src.infrastructure.agent.processor.goal_evaluator import (
    GOAL_COMPLETION_JUDGE_TOOL_V2,
    GoalEvaluator,
    GoalJudgmentAuditV2,
    TaskStateUnavailableError,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_CONTRACT,
    WORKSPACE_SESSION_ROLE_KEY,
)
from src.infrastructure.workspace_core.legacy_runtime import (
    LegacyWorkspaceRuntimeRetiredError,
)


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


def goal_judgment_response(*, achieved: bool, rationale: str) -> dict[str, Any]:
    """Build one provider-neutral structured goal judgment tool call."""
    return {
        "tool_calls": [
            {
                "type": "function",
                "function": {
                    "name": GOAL_COMPLETION_JUDGE_TOOL_V2,
                    "arguments": json.dumps(
                        {
                            "goal_achieved": achieved,
                            "rationale": rationale,
                        }
                    ),
                },
            }
        ]
    }


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
    async def test_pending_task_goal_can_reconcile_with_llm_completion_evidence(self) -> None:
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(
            return_value=goal_judgment_response(
                achieved=True,
                rationale="The final report and verification evidence satisfy the request.",
            )
        )
        evaluator = GoalEvaluator(
            llm_client=llm_client,
            tools={
                "todoread": create_todoread_tool(
                    [
                        {"id": "task-real-1", "status": "completed", "content": "Run tests"},
                        {"id": "task-real-2", "status": "in_progress", "content": "Write report"},
                    ]
                )
            },
        )

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[
                {"role": "user", "content": "深度测试文件系统所有工具，生成测试报告与优化建议"},
                {
                    "role": "assistant",
                    "content": "测试已全部完成，报告已保存，12 个工具 36 个用例通过 35 个。",
                },
            ],
        )

        assert result.achieved is True
        assert result.source == "llm_task_reconciliation"
        assert "final report" in result.reason

    @pytest.mark.asyncio
    async def test_pending_task_goal_preserves_task_result_when_llm_rejects_completion(
        self,
    ) -> None:
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(
            return_value=goal_judgment_response(
                achieved=False,
                rationale="The report is not present in the conversation.",
            )
        )
        evaluator = GoalEvaluator(
            llm_client=llm_client,
            tools={
                "todoread": create_todoread_tool(
                    [{"id": "task-real-1", "status": "pending", "content": "Write report"}]
                )
            },
        )

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "finish task"}],
        )

        assert result.achieved is False
        assert result.source == "tasks"
        assert result.reason == "1 task(s) still in progress"
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
        """Workspace root goal reads are retired to Avernet Core and fail closed."""
        evaluator = GoalEvaluator(
            llm_client=None,
            tools={},
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )

        with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="retired"):
            await evaluator.evaluate_goal_completion(
                session_id="session-1",
                messages=[{"role": "user", "content": "finish task"}],
            )

    async def test_workspace_contract_role_skips_root_goal_task_lookup(self) -> None:
        evaluator = GoalEvaluator(
            llm_client=None,
            tools={},
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "",
                WORKSPACE_SESSION_ROLE_KEY: WORKSPACE_ROLE_CONTRACT,
            },
        )

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "verify node"}],
        )

        assert result.achieved is False
        assert result.should_stop is False
        assert result.source == "agent_judge"

    @pytest.mark.asyncio
    async def test_workspace_authority_empty_root_goal_marker_fails_closed(self) -> None:
        evaluator = GoalEvaluator(
            llm_client=None,
            tools={},
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "",
            },
        )

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "finish task"}],
        )

        assert result.achieved is False
        assert result.should_stop is True
        assert result.source == "workspace_tasks"
        assert result.reason == "Workspace task authority markers are incomplete"

    @pytest.mark.asyncio
    async def test_workspace_authority_requires_goal_evidence(self) -> None:
        """Goal evidence reads are retired to Avernet Core and fail closed."""
        evaluator = GoalEvaluator(
            llm_client=None,
            tools={},
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )

        with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="retired"):
            await evaluator.evaluate_goal_completion(
                session_id="session-1",
                messages=[{"role": "user", "content": "finish task"}],
            )

    async def test_workspace_authority_blocks_on_replan_required(self) -> None:
        """Replan gating reads are retired to Avernet Core and fail closed."""
        evaluator = GoalEvaluator(
            llm_client=None,
            tools={},
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )

        with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="retired"):
            await evaluator.evaluate_goal_completion(
                session_id="session-1",
                messages=[{"role": "user", "content": "finish task"}],
            )

    async def test_workspace_authority_ready_for_completion_keeps_loop_open(self) -> None:
        """Completion gating reads are retired to Avernet Core and fail closed."""
        evaluator = GoalEvaluator(
            llm_client=None,
            tools={},
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )

        with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="retired"):
            await evaluator.evaluate_goal_completion(
                session_id="session-1",
                messages=[{"role": "user", "content": "finish task"}],
            )

    async def test_no_tasks_uses_llm_self_check_true(self, evaluator_with_tasks):
        evaluator = evaluator_with_tasks([])
        evaluator._llm_client = AsyncMock()
        evaluator._llm_client.generate = AsyncMock(
            return_value=goal_judgment_response(achieved=True, rationale="all done")
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

        call = evaluator._llm_client.generate.await_args.kwargs
        assert call["tool_choice"] == {
            "type": "function",
            "function": {"name": GOAL_COMPLETION_JUDGE_TOOL_V2},
        }
        assert call["tools"][0]["function"]["name"] == GOAL_COMPLETION_JUDGE_TOOL_V2

    async def test_nested_provider_goal_judgment_tool_call_is_accepted(
        self,
        evaluator_with_tasks,
    ) -> None:
        evaluator = evaluator_with_tasks([])
        evaluator._llm_client = AsyncMock()
        evaluator._llm_client.generate = AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": GOAL_COMPLETION_JUDGE_TOOL_V2,
                                        "arguments": json.dumps(
                                            {
                                                "goal_achieved": True,
                                                "rationale": "All requested checks passed.",
                                            }
                                        ),
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        )

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "finish and verify"}],
        )

        assert result.achieved is True
        assert result.reason == "All requested checks passed."
        assert result.source == "llm_self_check"

    async def test_malformed_goal_judgment_arguments_fail_closed(
        self,
        evaluator_with_tasks,
    ) -> None:
        audits: list[GoalJudgmentAuditV2] = []
        evaluator = evaluator_with_tasks([])
        evaluator._llm_client = AsyncMock()
        evaluator._audit_sink = audits.append
        evaluator._llm_client.generate = AsyncMock(
            return_value={
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": GOAL_COMPLETION_JUDGE_TOOL_V2,
                            "arguments": "{malformed-json",
                        },
                    }
                ]
            }
        )

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "finish and verify"}],
        )

        assert result.achieved is False
        assert result.reason == "Goal completion judge unavailable or invalid"
        assert result.source == "agent_judge"
        assert audits == []

    @pytest.mark.parametrize(
        "tool_calls",
        [
            [
                {
                    "type": "custom",
                    "function": {
                        "name": GOAL_COMPLETION_JUDGE_TOOL_V2,
                        "arguments": json.dumps(
                            {"goal_achieved": True, "rationale": "Invalid call type."}
                        ),
                    },
                }
            ],
            [
                {
                    "type": "function",
                    "function": {
                        "name": GOAL_COMPLETION_JUDGE_TOOL_V2,
                        "arguments": json.dumps(
                            {"goal_achieved": True, "rationale": "First judgment."}
                        ),
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": GOAL_COMPLETION_JUDGE_TOOL_V2,
                        "arguments": json.dumps(
                            {"goal_achieved": True, "rationale": "Second judgment."}
                        ),
                    },
                },
            ],
            [
                {
                    "type": "function",
                    "function": {
                        "name": GOAL_COMPLETION_JUDGE_TOOL_V2,
                        "arguments": json.dumps(
                            {
                                "goal_achieved": True,
                                "rationale": "Unexpected fields are not contractual.",
                                "confidence": 1.0,
                            }
                        ),
                    },
                }
            ],
        ],
        ids=("wrong-call-type", "multiple-calls", "extra-arguments"),
    )
    async def test_noncanonical_goal_judgment_tool_calls_fail_closed(
        self,
        evaluator_with_tasks,
        tool_calls: list[dict[str, Any]],
    ) -> None:
        evaluator = evaluator_with_tasks([])
        evaluator._llm_client = AsyncMock()
        evaluator._llm_client.generate = AsyncMock(return_value={"tool_calls": tool_calls})

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "finish and verify"}],
        )

        assert result.achieved is False
        assert result.reason == "Goal completion judge unavailable or invalid"
        assert result.source == "agent_judge"

    async def test_default_goal_judgment_audit_redacts_sensitive_values(
        self,
        evaluator_with_tasks,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        evaluator = evaluator_with_tasks([])
        evaluator._llm_client = AsyncMock()
        evaluator._llm_client.generate = AsyncMock(
            return_value=goal_judgment_response(
                achieved=False,
                rationale="Provider rejected Bearer private-token-value.",
            )
        )

        with caplog.at_level(logging.INFO, logger="agent_decision_audit"):
            result = await evaluator.evaluate_goal_completion(
                session_id="session-1",
                messages=[
                    {
                        "role": "user",
                        "content": "Retry https://example.test?api_key=private-query-value",
                    }
                ],
            )

        assert result.achieved is False
        audit_record = next(
            record for record in caplog.records if record.name == "agent_decision_audit"
        )
        redacted_fields = " ".join(
            str(getattr(audit_record, field)) for field in ("input", "output", "rationale")
        )
        assert "private-query-value" not in redacted_fields
        assert "private-token-value" not in redacted_fields
        assert "<redacted>" in redacted_fields

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
        assert result.source == "agent_judge"
        assert result.reason == "Goal completion judge unavailable or invalid"

    @pytest.mark.asyncio
    async def test_no_tasks_plain_text_self_check_cannot_issue_verdict(self, evaluator_with_tasks):
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
        assert result.source == "agent_judge"

    @pytest.mark.asyncio
    async def test_structured_goal_judgment_records_complete_audit_fields(self) -> None:
        audits: list[GoalJudgmentAuditV2] = []
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(
            return_value=goal_judgment_response(
                achieved=False,
                rationale="The requested verification evidence is still missing.",
            )
        )
        evaluator = GoalEvaluator(
            llm_client=llm_client,
            tools={},
            runtime_context={"selected_agent_id": "builtin:sisyphus"},
            audit_sink=audits.append,
        )

        result = await evaluator.evaluate_goal_completion(
            session_id="session-1",
            messages=[{"role": "user", "content": "finish the implementation"}],
        )

        assert result.achieved is False
        assert len(audits) == 1
        audit = audits[0]
        assert audit.agent_id == "builtin:sisyphus"
        assert audit.tool_name == GOAL_COMPLETION_JUDGE_TOOL_V2
        assert audit.input_json["context_summary"]
        assert audit.output_json == {
            "goal_achieved": False,
            "rationale": "The requested verification evidence is still missing.",
        }
        assert audit.rationale == "The requested verification evidence is still missing."
        assert audit.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_workspace_authority_rejects_terminal_children_without_attempt_evidence(
        self,
    ) -> None:
        """Terminal-child evidence reads are retired to Avernet Core and fail closed."""
        evaluator = GoalEvaluator(
            llm_client=None,
            tools={},
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )

        with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="retired"):
            await evaluator.evaluate_goal_completion(
                session_id="session-1",
                messages=[{"role": "user", "content": "finish task"}],
            )
