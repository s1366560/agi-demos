"""Tests for the generation-pinned ``reflect_friction`` agent tool."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.model.flow.reflection_verdict import ReflectionAction, ReflectionVerdict
from src.infrastructure.agent.tools import reflection_tool as tool_module
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.reflection_tool import reflect_friction_tool
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


def _ctx(project_id: str = "p1", **overrides: object) -> ToolContext:
    defaults: dict[str, object] = {
        "session_id": "sess-1",
        "message_id": "msg-1",
        "call_id": "call-1",
        "agent_name": "planner",
        "conversation_id": "conv-1",
        "project_id": project_id,
        "tenant_id": "t1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)  # type: ignore[arg-type]


class TestReflectFrictionTool:
    async def test_missing_project_id_is_error(self) -> None:
        result = await reflect_friction_tool.execute(_ctx(project_id=""))

        assert result.is_error
        assert "project_id" in result.output

    async def test_missing_pinned_runtime_is_structured_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _missing():
            raise RuntimeV2Error("generation_not_pinned", "plugin generation is not pinned")

        monkeypatch.setattr(tool_module, "current_reflection_runtime_v2", _missing)

        result = await reflect_friction_tool.execute(_ctx())

        assert result.is_error
        assert json.loads(result.output)["code"] == "generation_not_pinned"

    async def test_create_verdict_round_trip_uses_v2_runtime(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        verdict = ReflectionVerdict(
            action=ReflectionAction.CREATE,
            playbook_id=None,
            rationale="frequent dev-to-todo bounce",
            proposed_playbook={"name": "Tighten backlog gate"},
        )
        reflect_project = AsyncMock(return_value=[verdict])
        monkeypatch.setattr(
            tool_module,
            "current_reflection_runtime_v2",
            lambda: SimpleNamespace(reflect_project=reflect_project),
        )

        result = await reflect_friction_tool.execute(_ctx())

        assert not result.is_error
        reflect_project.assert_awaited_once_with(
            project_id="p1",
            tenant_id="t1",
            source="tool",
            run_id="call-1",
        )
        body = json.loads(result.output)
        assert body["applied_count"] == 1
        assert body["verdicts"][0]["action"] == "create"
        assert body["verdicts"][0]["proposed_name"] == "Tighten backlog gate"

    async def test_runtime_exception_is_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        reflect_project = AsyncMock(side_effect=RuntimeError("llm timeout"))
        monkeypatch.setattr(
            tool_module,
            "current_reflection_runtime_v2",
            lambda: SimpleNamespace(reflect_project=reflect_project),
        )

        result = await reflect_friction_tool.execute(_ctx())

        assert result.is_error
        body = json.loads(result.output)
        assert body["code"] == "reflection_failed"
        assert "llm timeout" in body["error"]
