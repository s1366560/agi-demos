from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.delegate_subagent import make_nested_delegate_tool_defs
from src.infrastructure.agent.tools.subagent_sessions import make_nested_session_tool_defs


@pytest.mark.unit
class TestNestedDelegateToolDefinitions:
    @pytest.mark.asyncio
    async def test_execute_without_ctx_uses_injected_runtime_context(self) -> None:
        callback = AsyncMock(return_value="done")
        tool = make_nested_delegate_tool_defs(
            subagent_names=["worker"],
            subagent_descriptions={"worker": "Does bounded work"},
            execute_callback=callback,
            run_registry=SubAgentRunRegistry(),
            conversation_id="conv-1",
            delegation_depth=0,
            max_active_runs=4,
        )[0]
        runtime_ctx = ToolContext(
            session_id="sess-1",
            message_id="msg-1",
            call_id="call-1",
            agent_name="leader",
            conversation_id="conv-1",
            runtime_context={
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
            },
        )
        tool._tool_instance.set_runtime_context(runtime_ctx)

        result = await tool.execute(subagent_name="worker", task="Implement the task")

        assert result.is_error is True
        assert "workspace_task_id" in result.output
        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_execute_without_ctx_falls_back_to_stub_context(self) -> None:
        callback = AsyncMock(return_value="delegated")
        tool = make_nested_delegate_tool_defs(
            subagent_names=["worker"],
            subagent_descriptions={"worker": "Does bounded work"},
            execute_callback=callback,
            run_registry=SubAgentRunRegistry(),
            conversation_id="conv-1",
            delegation_depth=0,
            max_active_runs=4,
        )[0]

        result = await tool.execute(subagent_name="worker", task="Implement the task")

        assert result.output == "delegated"
        callback.assert_awaited_once()


@pytest.mark.unit
class TestNestedSessionToolDefinitions:
    @pytest.mark.asyncio
    async def test_sessions_list_execute_without_ctx_uses_stub_context(self) -> None:
        async def cancel_callback(_run_id: str) -> bool:
            return True

        list_tool = make_nested_session_tool_defs(
            run_registry=SubAgentRunRegistry(),
            conversation_id="conv-1",
            requester_session_key="parent-1",
            visibility_default="tree",
            observability_stats_provider=None,
            subagent_names=["worker"],
            subagent_descriptions={"worker": "Does bounded work"},
            cancel_callback=cancel_callback,
            restart_callback=None,
            max_active_runs=4,
            max_active_runs_per_lineage=4,
            max_children_per_requester=4,
            delegation_depth=0,
            max_delegation_depth=2,
        )[0]

        result = await list_tool.execute(status="active")

        assert result.is_error is False
        assert '"conversation_id": "conv-1"' in result.output
        assert '"count": 0' in result.output
