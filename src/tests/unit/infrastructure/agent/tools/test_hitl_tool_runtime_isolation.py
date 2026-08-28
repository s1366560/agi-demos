"""Generation-local runtime coverage for clarification and decision tools."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.state import agent_worker_state
from src.infrastructure.agent.tools.clarification import (
    make_clarification_tool,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.decision import make_decision_tool


def _context(name: str) -> ToolContext:
    return ToolContext(
        session_id=f"session-{name}",
        message_id=f"message-{name}",
        call_id=f"call-{name}",
        agent_name=f"agent-{name}",
        conversation_id=f"conversation-{name}",
        tenant_id=f"tenant-{name}",
        project_id=f"project-{name}",
    )


@pytest.mark.unit
async def test_bound_hitl_tools_use_captured_handlers() -> None:
    clarification_handler = SimpleNamespace(
        request_clarification=AsyncMock(return_value="bound clarification"),
    )
    decision_handler = SimpleNamespace(
        request_decision=AsyncMock(return_value="bound decision"),
    )
    clarification = make_clarification_tool(hitl_handler=clarification_handler)
    decision = make_decision_tool(hitl_handler=decision_handler)

    clarification_result = await clarification.execute(
        _context("a"),
        question="Clarify?",
    )
    decision_result = await decision.execute(
        _context("b"),
        question="Choose?",
        options=["A", "B"],
    )

    assert clarification_result.output == "bound clarification"
    assert decision_result.output == "bound decision"


@pytest.mark.unit
async def test_clarification_handler_isolated_between_concurrent_generations() -> None:
    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def _first_request(**_kwargs: object) -> str:
        first_entered.set()
        await release_first.wait()
        return "generation-a"

    async def _second_request(**_kwargs: object) -> str:
        await first_entered.wait()
        release_first.set()
        return "generation-b"

    first = make_clarification_tool(
        hitl_handler=SimpleNamespace(request_clarification=_first_request),
    )
    second = make_clarification_tool(
        hitl_handler=SimpleNamespace(request_clarification=_second_request),
    )

    first_task = asyncio.create_task(first.execute(_context("a"), question="Shared?"))
    await first_entered.wait()
    second_result = await second.execute(_context("b"), question="Shared?")
    first_result = await first_task

    assert first_result.output == "generation-a"
    assert second_result.output == "generation-b"


@pytest.mark.unit
async def test_worker_builds_hitl_tools_from_bound_factories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clarification_marker = object()
    decision_marker = object()
    captured: list[tuple[str, object]] = []

    def _make_clarification_tool(*, hitl_handler: object) -> object:
        captured.append(("clarification", hitl_handler))
        return clarification_marker

    def _make_decision_tool(*, hitl_handler: object) -> object:
        captured.append(("decision", hitl_handler))
        return decision_marker

    monkeypatch.setattr(
        "src.infrastructure.agent.tools.clarification.make_clarification_tool",
        _make_clarification_tool,
        raising=False,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.tools.decision.make_decision_tool",
        _make_decision_tool,
        raising=False,
    )

    tools = await agent_worker_state._get_or_create_builtin_tools(
        "project-a",
        redis_client=None,
    )
    agent_worker_state._add_hitl_tools(tools, project_id="project-a")

    assert tools["ask_clarification"] is clarification_marker
    assert tools["request_decision"] is decision_marker
    assert captured == [
        ("clarification", None),
        ("decision", None),
        ("clarification", None),
        ("decision", None),
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("module_name", "seam_name"),
    [
        ("clarification", "configure_clarification"),
        ("clarification", "_clarification_hitl_handler"),
        ("decision", "configure_decision"),
        ("decision", "_decision_hitl_handler"),
    ],
)
def test_hitl_tool_modules_have_no_legacy_runtime_seams(
    module_name: str,
    seam_name: str,
) -> None:
    from src.infrastructure.agent.tools import (
        clarification as clarification_module,
        decision as decision_module,
    )

    module = clarification_module if module_name == "clarification" else decision_module
    assert not hasattr(module, seam_name)
