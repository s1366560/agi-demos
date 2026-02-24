"""Unit tests for HITL tool handler answered events."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.events.agent_events import (
    AgentClarificationAnsweredEvent,
    AgentDecisionAnsweredEvent,
    AgentEnvVarProvidedEvent,
)
from src.infrastructure.agent.core.message import ToolPart, ToolState
from src.infrastructure.agent.processor.hitl_tool_handler import (
    handle_clarification_tool,
    handle_decision_tool,
    handle_env_var_tool,
)


def _make_tool_part(call_id: str, tool_name: str) -> ToolPart:
    return ToolPart(
        call_id=call_id,
        tool=tool_name,
        status=ToolState.RUNNING,
        input={},
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clarification_answered_event_uses_original_request_id() -> None:
    coordinator = MagicMock()
    coordinator.prepare_request = AsyncMock(return_value="clar-req-1")
    coordinator.wait_for_response = AsyncMock(return_value="PostgreSQL")
    tool_part = _make_tool_part("call-clar", "ask_clarification")

    events = [
        event
        async for event in handle_clarification_tool(
            coordinator=coordinator,
            call_id="call-clar",
            tool_name="ask_clarification",
            arguments={
                "question": "Which DB?",
                "clarification_type": "approach",
                "options": [{"id": "pg", "label": "PostgreSQL"}],
            },
            tool_part=tool_part,
        )
    ]

    answered_event = next(e for e in events if isinstance(e, AgentClarificationAnsweredEvent))
    assert answered_event.request_id == "clar-req-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_decision_answered_event_uses_original_request_id() -> None:
    coordinator = MagicMock()
    coordinator.prepare_request = AsyncMock(return_value="dec-req-1")
    coordinator.wait_for_response = AsyncMock(return_value="option_a")
    tool_part = _make_tool_part("call-dec", "request_decision")

    events = [
        event
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id="call-dec",
            tool_name="request_decision",
            arguments={
                "question": "Choose option",
                "decision_type": "method",
                "options": [{"id": "a", "label": "Option A"}],
            },
            tool_part=tool_part,
        )
    ]

    answered_event = next(e for e in events if isinstance(e, AgentDecisionAnsweredEvent))
    assert answered_event.request_id == "dec-req-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_env_var_provided_event_uses_original_request_id() -> None:
    coordinator = MagicMock()
    coordinator.prepare_request = AsyncMock(return_value="env-req-1")
    coordinator.wait_for_response = AsyncMock(return_value={"API_KEY": "secret"})
    tool_part = _make_tool_part("call-env", "request_env_var")

    events = [
        event
        async for event in handle_env_var_tool(
            coordinator=coordinator,
            call_id="call-env",
            tool_name="request_env_var",
            arguments={
                "tool_name": "web_search",
                "fields": [{"name": "API_KEY", "description": "Key"}],
            },
            tool_part=tool_part,
        )
    ]

    provided_event = next(e for e in events if isinstance(e, AgentEnvVarProvidedEvent))
    assert provided_event.request_id == "env-req-1"
