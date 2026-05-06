"""Tests for the ``reflect_friction`` agent tool."""

from __future__ import annotations

import json

import pytest

from src.application.services.reflection_service import ReflectionService
from src.domain.model.flow.friction_signal import FrictionKind, FrictionSignal
from src.domain.model.flow.reflection_verdict import (
    ReflectionAction,
    ReflectionVerdict,
)
from src.domain.ports.services.reflector_port import ReflectorPort
from src.infrastructure.adapters.secondary.in_memory.friction_loop import (
    InMemoryFrictionLedger,
    InMemoryPlaybookRepository,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.reflection_tool import (
    configure_reflection_tool,
    reflect_friction_tool,
)


class _CreateReflector(ReflectorPort):
    async def reflect(self, *, project_id, signals, existing_playbooks):  # type: ignore[override]
        del project_id, existing_playbooks
        if not signals:
            return []
        return [
            ReflectionVerdict(
                action=ReflectionAction.CREATE,
                playbook_id=None,
                rationale="frequent dev->todo bounce",
                proposed_playbook={
                    "name": "Tighten backlog gate",
                    "trigger": {"description": "dev->todo bounce"},
                    "steps": [{"order": 1, "instruction": "Add ACs before promotion"}],
                },
            )
        ]


def _ctx(project_id: str = "p1", **overrides) -> ToolContext:
    defaults: dict = {
        "session_id": "sess-1",
        "message_id": "msg-1",
        "call_id": "call-1",
        "agent_name": "planner",
        "conversation_id": "conv-1",
        "project_id": project_id,
        "tenant_id": "t1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


async def _service_with_signal(project_id: str) -> ReflectionService:
    ledger = InMemoryFrictionLedger()
    await ledger.append(
        FrictionSignal(
            project_id=project_id,
            task_id="t1",
            kind=FrictionKind.BOUNCE,
            source_lane="dev",
            target_lane="todo",
        )
    )
    return ReflectionService(
        ledger=ledger,
        playbooks=InMemoryPlaybookRepository(),
        reflector=_CreateReflector(),
    )


@pytest.fixture(autouse=True)
def _reset_provider():
    configure_reflection_tool(lambda _pid: _service_with_signal(_pid))  # type: ignore[arg-type]
    yield
    # Reset to a clearly-broken provider so leakage is loud.
    configure_reflection_tool(None)  # type: ignore[arg-type]


class TestReflectFrictionTool:
    async def test_missing_project_id_is_error(self) -> None:
        result = await reflect_friction_tool.execute(_ctx(project_id=""))
        assert result.is_error
        assert "project_id" in result.output

    async def test_missing_provider_is_error(self) -> None:
        configure_reflection_tool(None)  # type: ignore[arg-type]
        result = await reflect_friction_tool.execute(_ctx())
        assert result.is_error
        assert "configured" in result.output

    async def test_provider_returning_none_is_unavailable(self) -> None:
        async def _none(_pid: str):
            return None

        configure_reflection_tool(_none)
        result = await reflect_friction_tool.execute(_ctx())
        assert not result.is_error
        body = json.loads(result.output)
        assert body["status"] == "unavailable"
        assert body["verdicts"] == []

    async def test_create_verdict_round_trip(self) -> None:
        result = await reflect_friction_tool.execute(_ctx())
        assert not result.is_error
        body = json.loads(result.output)
        assert body["project_id"] == "p1"
        assert body["applied_count"] == 1
        verdict = body["verdicts"][0]
        assert verdict["action"] == "create"
        assert verdict["proposed_name"] == "Tighten backlog gate"

    async def test_provider_exception_is_error(self) -> None:
        async def _bad(_pid: str):
            raise RuntimeError("db down")

        configure_reflection_tool(_bad)
        result = await reflect_friction_tool.execute(_ctx())
        assert result.is_error
        assert "db down" in result.output

    async def test_reflect_exception_is_error(self) -> None:
        class _BadService:
            async def reflect_window(self, _pid: str):
                raise RuntimeError("llm timeout")

        async def _provider(_pid: str):
            return _BadService()

        configure_reflection_tool(_provider)  # type: ignore[arg-type]
        result = await reflect_friction_tool.execute(_ctx())
        assert result.is_error
        assert "llm timeout" in result.output
