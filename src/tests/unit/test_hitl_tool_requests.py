"""Tests for clarification/decision tool scoping, sanitization, and request identity."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.infrastructure.agent.tools.clarification import (
    make_clarification_tool,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.decision import make_decision_tool
from src.infrastructure.agent.tools.result import ToolResult


@pytest.fixture
def tool_ctx() -> ToolContext:
    return ToolContext(
        session_id="sess-1",
        message_id="msg-1",
        call_id="call-1",
        agent_name="test-agent",
        conversation_id="conv-1",
        tenant_id="tenant-ctx",
        project_id="project-ctx",
    )


@pytest.mark.unit
class TestHitlToolRequests:
    async def test_clarification_tool_scopes_handler_and_sanitizes_payload(
        self,
        tool_ctx: ToolContext,
    ) -> None:
        base_handler = object()
        scoped_handler = SimpleNamespace(
            tenant_id="tenant-ctx",
            project_id="project-ctx",
            request_clarification=AsyncMock(return_value="<b>Approved</b>\x01"),
        )
        bound_tool = make_clarification_tool(hitl_handler=base_handler)

        with patch(
            "src.infrastructure.agent.tools.clarification._scope_hitl_handler",
            return_value=scoped_handler,
        ) as scope_mock:
            result = await bound_tool.execute(
                tool_ctx,
                question=" <b>Need input?</b>\x01 ",
                context="<script>alert(1)</script>\x02",
            )

        assert isinstance(result, ToolResult)
        assert result.is_error is False
        scope_mock.assert_called_once_with(
            base_handler,
            tenant_id="tenant-ctx",
            project_id="project-ctx",
            conversation_id="conv-1",
            message_id="msg-1",
        )
        scoped_handler.request_clarification.assert_awaited_once()
        request_kwargs = scoped_handler.request_clarification.await_args.kwargs
        assert request_kwargs["question"] == "&lt;b&gt;Need input?&lt;/b&gt;"
        assert request_kwargs["context"] == {"info": "&lt;script&gt;alert(1)&lt;/script&gt;"}
        assert result.output == "&lt;b&gt;Approved&lt;/b&gt;"
        assert result.metadata == {
            "question": "&lt;b&gt;Need input?&lt;/b&gt;",
            "answer": "&lt;b&gt;Approved&lt;/b&gt;",
        }

    async def test_clarification_request_id_changes_with_context(
        self,
        tool_ctx: ToolContext,
    ) -> None:
        base_handler = object()
        scoped_handler = SimpleNamespace(
            tenant_id="tenant-ctx",
            project_id="project-ctx",
            request_clarification=AsyncMock(return_value="ok"),
        )
        bound_tool = make_clarification_tool(hitl_handler=base_handler)

        with patch(
            "src.infrastructure.agent.tools.clarification._scope_hitl_handler",
            return_value=scoped_handler,
        ):
            await bound_tool.execute(tool_ctx, question="Need input?", context="ctx-one")
            first_request_id = scoped_handler.request_clarification.await_args.kwargs["request_id"]
            await bound_tool.execute(tool_ctx, question="Need input?", context="ctx-two")
            second_request_id = scoped_handler.request_clarification.await_args.kwargs["request_id"]

        assert first_request_id != second_request_id

    async def test_decision_tool_scopes_handler_and_sanitizes_payload(
        self,
        tool_ctx: ToolContext,
    ) -> None:
        base_handler = object()
        scoped_handler = SimpleNamespace(
            tenant_id="tenant-ctx",
            project_id="project-ctx",
            request_decision=AsyncMock(return_value=["<b>Option A</b>\x01", "Option B"]),
        )
        bound_tool = make_decision_tool(hitl_handler=base_handler)

        with patch(
            "src.infrastructure.agent.tools.decision._scope_hitl_handler",
            return_value=scoped_handler,
        ) as scope_mock:
            result = await bound_tool.execute(
                tool_ctx,
                question=" <b>Choose</b>\x01 ",
                options=["<i>Option A</i>\x02", "Option B"],
                context="<script>ctx</script>\x03",
                recommendation="<i>Option A</i>\x02",
                selection_mode="multiple",
                max_selections=2,
            )

        assert isinstance(result, ToolResult)
        assert result.is_error is False
        scope_mock.assert_called_once_with(
            base_handler,
            tenant_id="tenant-ctx",
            project_id="project-ctx",
            conversation_id="conv-1",
            message_id="msg-1",
        )
        request_kwargs = scoped_handler.request_decision.await_args.kwargs
        assert request_kwargs["question"] == "&lt;b&gt;Choose&lt;/b&gt;"
        assert request_kwargs["options"] == [
            {"id": "0", "label": "&lt;i&gt;Option A&lt;/i&gt;", "recommended": True},
            {"id": "1", "label": "Option B"},
        ]
        assert request_kwargs["context"] == {"info": "&lt;script&gt;ctx&lt;/script&gt;"}
        assert result.output == "&lt;b&gt;Option A&lt;/b&gt;, Option B"
        assert result.metadata == {
            "question": "&lt;b&gt;Choose&lt;/b&gt;",
            "options": ["&lt;i&gt;Option A&lt;/i&gt;", "Option B"],
            "decision": ["&lt;b&gt;Option A&lt;/b&gt;", "Option B"],
        }

    async def test_decision_request_id_changes_with_max_selections(
        self,
        tool_ctx: ToolContext,
    ) -> None:
        base_handler = object()
        scoped_handler = SimpleNamespace(
            tenant_id="tenant-ctx",
            project_id="project-ctx",
            request_decision=AsyncMock(return_value="done"),
        )
        bound_tool = make_decision_tool(hitl_handler=base_handler)

        with patch(
            "src.infrastructure.agent.tools.decision._scope_hitl_handler",
            return_value=scoped_handler,
        ):
            await bound_tool.execute(
                tool_ctx,
                question="Choose",
                options=["A", "B"],
                selection_mode="multiple",
                max_selections=1,
            )
            first_request_id = scoped_handler.request_decision.await_args.kwargs["request_id"]
            await bound_tool.execute(
                tool_ctx,
                question="Choose",
                options=["A", "B"],
                selection_mode="multiple",
                max_selections=2,
            )
            second_request_id = scoped_handler.request_decision.await_args.kwargs["request_id"]

        assert first_request_id != second_request_id

    async def test_decision_tool_allows_empty_options_as_freeform_decision(
        self,
        tool_ctx: ToolContext,
    ) -> None:
        base_handler = object()
        scoped_handler = SimpleNamespace(
            tenant_id="tenant-ctx",
            project_id="project-ctx",
            request_decision=AsyncMock(return_value="free-form answer"),
        )
        bound_tool = make_decision_tool(hitl_handler=base_handler)

        with patch(
            "src.infrastructure.agent.tools.decision._scope_hitl_handler",
            return_value=scoped_handler,
        ):
            result = await bound_tool.execute(
                tool_ctx,
                question="How should we proceed?",
                options=[],
            )

        assert isinstance(result, ToolResult)
        assert result.is_error is False
        request_kwargs = scoped_handler.request_decision.await_args.kwargs
        assert request_kwargs["options"] == []
        assert request_kwargs["allow_custom"] is True
        assert result.output == "free-form answer"

    async def test_decision_tool_rejects_invalid_selection_mode(
        self,
        tool_ctx: ToolContext,
    ) -> None:
        bound_tool = make_decision_tool(hitl_handler=object())

        result = await bound_tool.execute(
            tool_ctx,
            question="Choose",
            options=["A", "B"],
            selection_mode="many",
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "selection_mode" in result.output

    async def test_decision_tool_rejects_invalid_max_selections(
        self,
        tool_ctx: ToolContext,
    ) -> None:
        bound_tool = make_decision_tool(hitl_handler=object())

        result = await bound_tool.execute(
            tool_ctx,
            question="Choose",
            options=["A", "B"],
            selection_mode="single",
            max_selections=1,
        )

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "max_selections" in result.output
