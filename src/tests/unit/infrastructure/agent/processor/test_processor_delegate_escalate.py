"""Unit tests for SessionProcessor delegate/escalate detection."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.events.agent_events import AgentActEvent, AgentStatusEvent
from src.infrastructure.agent.processor.processor import (
    ProcessorResult,
    SessionProcessor,
)

_RE = SessionProcessor._DELEGATE_ESCALATE_RE


@pytest.mark.unit
class TestDelegateEscalateRegex:
    def test_delegate_basic(self) -> None:
        m = _RE.search("delegate:CodeReviewer")
        assert m is not None
        assert m.group(1).lower() == "delegate"
        assert m.group(2) == "CodeReviewer"

    def test_escalate_basic(self) -> None:
        m = _RE.search("escalate:SecurityAgent")
        assert m is not None
        assert m.group(1).lower() == "escalate"
        assert m.group(2) == "SecurityAgent"

    def test_case_insensitive(self) -> None:
        for variant in ["Delegate:Agent1", "DELEGATE:Agent1", "dElEgAtE:Agent1"]:
            m = _RE.search(variant)
            assert m is not None, f"Failed for {variant}"
            assert m.group(1).lower() == "delegate"

    def test_space_around_colon(self) -> None:
        m = _RE.search("delegate : myAgent")
        assert m is not None
        assert m.group(2) == "myAgent"

    def test_agent_name_with_hyphen(self) -> None:
        m = _RE.search("delegate:code-reviewer")
        assert m is not None
        assert m.group(2) == "code-reviewer"

    def test_agent_name_with_underscore(self) -> None:
        m = _RE.search("escalate:security_auditor")
        assert m is not None
        assert m.group(2) == "security_auditor"

    def test_agent_name_with_digits(self) -> None:
        m = _RE.search("delegate:Agent42")
        assert m is not None
        assert m.group(2) == "Agent42"

    def test_embedded_in_sentence(self) -> None:
        text = "I need to delegate:Planner for this complex task."
        m = _RE.search(text)
        assert m is not None
        assert m.group(2) == "Planner"

    def test_no_match_plain_text(self) -> None:
        m = _RE.search("I will handle this myself. No delegation needed.")
        assert m is None

    def test_no_match_partial_keyword(self) -> None:
        m = _RE.search("delegating to someone")
        assert m is None

    def test_no_match_missing_agent_name(self) -> None:
        m = _RE.search("delegate: ")
        assert m is None

    def test_multiple_matches_first_wins(self) -> None:
        text = "delegate:Agent1 then escalate:Agent2"
        m = _RE.search(text)
        assert m is not None
        assert m.group(2) == "Agent1"


def _make_processor() -> SessionProcessor:
    return object.__new__(SessionProcessor)


@pytest.mark.unit
class TestDetectDelegateOrEscalate:
    def test_delegate_returns_tuple(self) -> None:
        proc = _make_processor()
        result = proc._detect_delegate_or_escalate("delegate:MyAgent remaining task")
        assert result is not None
        action, agent_name, remaining = result
        assert action == "delegate"
        assert agent_name == "MyAgent"
        assert remaining == "remaining task"

    def test_escalate_returns_tuple(self) -> None:
        proc = _make_processor()
        result = proc._detect_delegate_or_escalate("escalate:SecurityBot check for vulns")
        assert result is not None
        action, agent_name, remaining = result
        assert action == "escalate"
        assert agent_name == "SecurityBot"
        assert remaining == "check for vulns"

    def test_remaining_text_stripped(self) -> None:
        proc = _make_processor()
        result = proc._detect_delegate_or_escalate("delegate:Agent   lots of spaces  ")
        assert result is not None
        _, _, remaining = result
        assert remaining == "lots of spaces"

    def test_no_remaining_text(self) -> None:
        proc = _make_processor()
        result = proc._detect_delegate_or_escalate("delegate:Agent")
        assert result is not None
        _, _, remaining = result
        assert remaining == ""

    def test_no_match_returns_none(self) -> None:
        proc = _make_processor()
        result = proc._detect_delegate_or_escalate("just a normal response with no pattern")
        assert result is None

    def test_empty_string_returns_none(self) -> None:
        proc = _make_processor()
        result = proc._detect_delegate_or_escalate("")
        assert result is None

    def test_case_insensitive_action(self) -> None:
        proc = _make_processor()
        result = proc._detect_delegate_or_escalate("ESCALATE:BigBoss do the thing")
        assert result is not None
        action, agent_name, _ = result
        assert action == "escalate"
        assert agent_name == "BigBoss"

    def test_hyphenated_agent_name(self) -> None:
        proc = _make_processor()
        result = proc._detect_delegate_or_escalate("delegate:code-review-agent review code")
        assert result is not None
        _, agent_name, _ = result
        assert agent_name == "code-review-agent"


@pytest.mark.unit
class TestEvaluateNoToolResultDelegation:
    @staticmethod
    def _build_processor_for_eval(
        full_text: str,
        goal_achieved: bool = False,
        goal_should_stop: bool = False,
    ) -> SessionProcessor:
        proc: Any = object.__new__(SessionProcessor)

        mock_msg = MagicMock()
        mock_msg.get_full_text.return_value = full_text
        proc._current_message = mock_msg

        goal_result = MagicMock()
        goal_result.achieved = goal_achieved
        goal_result.should_stop = goal_should_stop
        goal_result.source = "tasks"
        goal_result.reason = "test reason"
        goal_result.pending_tasks = 0

        mock_evaluator = AsyncMock()
        mock_evaluator.evaluate_goal_completion = AsyncMock(return_value=goal_result)
        proc._goal_evaluator = mock_evaluator

        proc._no_progress_steps = 0
        proc._last_process_result = ProcessorResult.CONTINUE

        mock_config = MagicMock()
        mock_config.max_no_progress_steps = 5
        proc.config = mock_config

        return proc

    @pytest.mark.asyncio
    async def test_delegate_yields_act_event(self) -> None:
        proc = self._build_processor_for_eval(
            "I think delegate:Planner should handle the architecture task"
        )

        events: list[Any] = []
        async for ev in proc._evaluate_no_tool_result("session-1", []):
            events.append(ev)

        act_events = [e for e in events if isinstance(e, AgentActEvent)]
        assert len(act_events) == 1
        act = act_events[0]
        assert act.tool_name == "delegate_to_subagent"
        assert act.tool_input is not None
        assert act.tool_input["subagent_name"] == "Planner"
        assert "escalate" not in act.tool_input

    @pytest.mark.asyncio
    async def test_escalate_yields_act_event_with_flag(self) -> None:
        proc = self._build_processor_for_eval("escalate:SecurityExpert check for SQL injection")

        events: list[Any] = []
        async for ev in proc._evaluate_no_tool_result("session-1", []):
            events.append(ev)

        act_events = [e for e in events if isinstance(e, AgentActEvent)]
        assert len(act_events) == 1
        act = act_events[0]
        assert act.tool_name == "delegate_to_subagent"
        assert act.tool_input is not None
        assert act.tool_input["subagent_name"] == "SecurityExpert"
        assert act.tool_input.get("escalate") is True

    @pytest.mark.asyncio
    async def test_delegate_resets_no_progress_and_continues(self) -> None:
        proc = self._build_processor_for_eval("delegate:Agent do work")
        proc._no_progress_steps = 3

        events: list[Any] = []
        async for ev in proc._evaluate_no_tool_result("session-1", []):
            events.append(ev)

        assert proc._no_progress_steps == 0
        assert proc._last_process_result == ProcessorResult.CONTINUE

    @pytest.mark.asyncio
    async def test_delegate_task_uses_remaining_text(self) -> None:
        proc = self._build_processor_for_eval("delegate:Architect design the new module layout")

        events: list[Any] = []
        async for ev in proc._evaluate_no_tool_result("session-1", []):
            events.append(ev)

        act_events = [e for e in events if isinstance(e, AgentActEvent)]
        assert len(act_events) == 1
        assert act_events[0].tool_input is not None
        assert act_events[0].tool_input["task"] == "design the new module layout"

    @pytest.mark.asyncio
    async def test_delegate_no_remaining_uses_full_text(self) -> None:
        proc = self._build_processor_for_eval("delegate:QuickHelper")

        events: list[Any] = []
        async for ev in proc._evaluate_no_tool_result("session-1", []):
            events.append(ev)

        act_events = [e for e in events if isinstance(e, AgentActEvent)]
        assert len(act_events) == 1
        assert act_events[0].tool_input is not None
        assert act_events[0].tool_input["task"] == "delegate:QuickHelper"

    @pytest.mark.asyncio
    async def test_goal_achieved_takes_priority_over_delegate(self) -> None:
        proc = self._build_processor_for_eval(
            "delegate:SomeAgent do work",
            goal_achieved=True,
        )

        events: list[Any] = []
        async for ev in proc._evaluate_no_tool_result("session-1", []):
            events.append(ev)

        act_events = [e for e in events if isinstance(e, AgentActEvent)]
        assert len(act_events) == 0
        status_events = [e for e in events if isinstance(e, AgentStatusEvent)]
        assert any("goal_achieved" in e.status for e in status_events)

    @pytest.mark.asyncio
    async def test_no_delegate_pattern_falls_through(self) -> None:
        proc = self._build_processor_for_eval("Just a normal response, no delegation.")
        proc._is_conversational_response = MagicMock(return_value=True)  # type: ignore[method-assign]

        events: list[Any] = []
        async for ev in proc._evaluate_no_tool_result("session-1", []):
            events.append(ev)

        act_events = [e for e in events if isinstance(e, AgentActEvent)]
        assert len(act_events) == 0
        status_events = [e for e in events if isinstance(e, AgentStatusEvent)]
        assert any("conversational_response" in e.status for e in status_events)
