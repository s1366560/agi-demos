"""Unit tests for SessionProcessor delegate/escalate detection."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.events.agent_events import AgentActEvent, AgentCompleteEvent, AgentStatusEvent
from src.infrastructure.agent.core.llm_stream import StreamEventType
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    ProcessorResult,
    SessionProcessor,
)
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_TOOL_MODE_KEY,
    WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY,
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
        proc._response_instructions = []
        proc._tool_reminder_issued_for_streak = False
        proc.tools = {"read": MagicMock()}
        proc._is_conversational_response = MagicMock(return_value=False)  # type: ignore[method-assign]

        mock_config = MagicMock()
        mock_config.max_no_progress_steps = 5
        mock_config.runtime_context = {}
        proc.config = mock_config
        proc._saw_task_events = False

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
        assert proc._pending_completion_status == "goal_achieved:tasks"
        assert proc._last_process_result == ProcessorResult.COMPLETE

    @pytest.mark.asyncio
    async def test_no_delegate_pattern_falls_through(self) -> None:
        proc = self._build_processor_for_eval("Just a normal response, no delegation.")
        proc._is_conversational_response = MagicMock(return_value=True)  # type: ignore[method-assign]
        # Use a low-confidence source so conversational check is not gated
        proc._goal_evaluator.evaluate_goal_completion.return_value.source = "assistant_text"

        events: list[Any] = []
        async for ev in proc._evaluate_no_tool_result("session-1", []):
            events.append(ev)

        act_events = [e for e in events if isinstance(e, AgentActEvent)]
        assert len(act_events) == 0
        assert proc._pending_completion_status == "goal_achieved:conversational_response"
        assert proc._last_process_result == ProcessorResult.COMPLETE

    @pytest.mark.asyncio
    async def test_conversational_response_gated_by_llm_self_check(self) -> None:
        """When goal evaluator explicitly says 'not achieved' via llm_self_check,
        conversational response should NOT cause early exit."""
        proc = self._build_processor_for_eval("Just a normal response, no delegation.")
        proc._is_conversational_response = MagicMock(return_value=True)  # type: ignore[method-assign]
        # source="tasks" is authoritative -- conversational exit should be gated
        # (default from _build_processor_for_eval is "tasks")

        events: list[Any] = []
        async for ev in proc._evaluate_no_tool_result("session-1", []):
            events.append(ev)

        status_events = [e for e in events if isinstance(e, AgentStatusEvent)]
        assert not any("conversational_response" in e.status for e in status_events)
        assert any("goal_pending" in e.status for e in status_events)

    @pytest.mark.asyncio
    async def test_task_ledger_only_replan_requires_tool_calls_before_text_completion(
        self,
    ) -> None:
        proc = self._build_processor_for_eval(
            "Replan complete",
            goal_should_stop=True,
        )
        proc.config.runtime_context = {
            WORKSPACE_TOOL_MODE_KEY: WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY
        }
        proc._is_conversational_response = MagicMock(return_value=True)  # type: ignore[method-assign]

        events: list[Any] = []
        async for ev in proc._evaluate_no_tool_result("session-1", []):
            events.append(ev)

        proc._goal_evaluator.evaluate_goal_completion.assert_not_awaited()
        assert proc._last_process_result == ProcessorResult.CONTINUE
        assert proc._no_progress_steps == 1
        assert SessionProcessor._WORKSPACE_REPLAN_TOOL_CALL_HINT in proc._response_instructions
        assert [e.status for e in events if isinstance(e, AgentStatusEvent)] == [
            "workspace_replan_requires_todoread_todowrite"
        ]

    @pytest.mark.asyncio
    async def test_task_ledger_only_replan_falls_back_to_protocol_recovery(
        self,
    ) -> None:
        proc = self._build_processor_for_eval("Replan complete")
        proc.config.runtime_context = {
            WORKSPACE_TOOL_MODE_KEY: WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY
        }
        proc.config.max_no_progress_steps = 1

        async def _fake_recovery(session_id: str):
            assert session_id == "session-1"
            proc._saw_task_events = True
            yield AgentStatusEvent(status="fake_recovery_done")

        proc._run_workspace_replan_protocol_recovery = _fake_recovery  # type: ignore[method-assign]

        events: list[Any] = []
        async for ev in proc._evaluate_no_tool_result("session-1", []):
            events.append(ev)

        assert proc._last_process_result == ProcessorResult.COMPLETE
        assert proc._pending_completion_status == "goal_achieved:workspace_replan_dispatched"
        assert [e.status for e in events if isinstance(e, AgentStatusEvent)] == [
            "workspace_replan_requires_todoread_todowrite",
            "workspace_replan_protocol_recovery",
            "fake_recovery_done",
        ]

    def test_workspace_replan_recovery_retains_completed_tasks_and_replaces_failed(
        self,
    ) -> None:
        proc = self._build_processor_for_eval("Replan complete")
        todoread_payload = {
            "todos": [
                {
                    "id": "done-step",
                    "content": "Completed implementation",
                    "status": "completed",
                    "priority": "high",
                },
                {
                    "id": "blocked-step",
                    "content": "Blocked verification",
                    "status": "failed",
                    "priority": "high",
                },
            ]
        }

        todos, action = proc._build_workspace_replan_recovery_todowrite_args(
            json.dumps(todoread_payload)
        )

        assert action == "replace"
        assert todos[0] == {
            "id": "done-step",
            "content": "Completed implementation",
            "status": "completed",
            "priority": "high",
        }
        assert todos[1]["status"] == "pending"
        assert "Protocol recovery" in todos[1]["content"]

    def test_workspace_replan_recovery_uses_retry_task_when_recovery_is_blocked(
        self,
    ) -> None:
        proc = self._build_processor_for_eval("Replan complete")
        todoread_payload = {
            "todos": [
                {
                    "id": "recovery-step",
                    "content": (
                        "Protocol recovery: reconcile blocked workspace tasks, verify current "
                        "implementation and architecture docs against the root goal, make only "
                        "minimal missing fixes, and report build/test evidence."
                    ),
                    "status": "failed",
                    "priority": "high",
                }
            ]
        }

        todos, action = proc._build_workspace_replan_recovery_todowrite_args(
            json.dumps(todoread_payload)
        )

        assert action == "replace"
        assert todos == [
            {
                "content": (
                    "Protocol recovery retry 2: reconcile blocked workspace tasks, "
                    "verify current implementation and architecture docs against the root goal, "
                    "make only minimal missing fixes, and report build/test evidence."
                ),
                "status": "pending",
                "priority": "high",
            }
        ]

    @pytest.mark.asyncio
    async def test_task_ledger_only_replan_completes_after_workspace_task_event(
        self,
    ) -> None:
        proc = self._build_processor_for_eval("Replan dispatched")
        proc.config.runtime_context = {
            WORKSPACE_TOOL_MODE_KEY: WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY
        }
        proc._saw_task_events = True
        proc._response_instructions = [SessionProcessor._WORKSPACE_REPLAN_TOOL_CALL_HINT]

        events: list[Any] = []
        async for ev in proc._evaluate_no_tool_result("session-1", []):
            events.append(ev)

        proc._goal_evaluator.evaluate_goal_completion.assert_not_awaited()
        assert events == []
        assert proc._pending_completion_status == "goal_achieved:workspace_replan_dispatched"
        assert proc._last_process_result == ProcessorResult.COMPLETE
        assert SessionProcessor._WORKSPACE_REPLAN_TOOL_CALL_HINT not in proc._response_instructions

    @pytest.mark.asyncio
    async def test_task_ledger_only_replan_completes_after_todowrite_tool_event(
        self,
    ) -> None:
        proc = self._build_processor_for_eval("Replan dispatched")
        proc.config.runtime_context = {
            WORKSPACE_TOOL_MODE_KEY: WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY
        }
        proc._saw_task_events = True

        result, events = await proc._evaluate_goal_progress(
            ProcessorResult.CONTINUE,
            had_tool_calls=True,
            session_id="session-1",
            messages=[],
        )

        assert events == []
        assert result == ProcessorResult.COMPLETE
        assert proc._pending_completion_status == "goal_achieved:workspace_replan_dispatched"

    @pytest.mark.asyncio
    async def test_task_ledger_only_replan_completion_skips_root_task_gate(
        self,
    ) -> None:
        proc = self._build_processor_for_eval("Replan dispatched")
        proc.config.runtime_context = {
            WORKSPACE_TOOL_MODE_KEY: WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY
        }
        proc._saw_task_events = True
        proc._pending_completion_status = "goal_achieved:workspace_replan_dispatched"
        proc._goal_evaluator.has_task_reader = MagicMock(return_value=True)
        proc._goal_evaluator.evaluate_task_completion_gate = AsyncMock(
            side_effect=AssertionError("root gate should be skipped")
        )
        proc._goal_evaluator.generate_suggestions = AsyncMock(return_value=[])
        proc._build_trace_url = MagicMock(return_value=None)  # type: ignore[method-assign]
        proc._build_execution_summary = AsyncMock(return_value={})  # type: ignore[method-assign]

        events: list[Any] = []
        async for ev in proc._emit_completion_events(
            ProcessorResult.COMPLETE,
            "session-1",
            [],
        ):
            events.append(ev)

        assert any(
            isinstance(event, AgentStatusEvent)
            and event.status == "goal_achieved:workspace_replan_dispatched"
            for event in events
        )
        assert any(isinstance(event, AgentCompleteEvent) for event in events)

    @pytest.mark.asyncio
    async def test_second_no_progress_turn_injects_tool_reminder(self) -> None:
        proc = self._build_processor_for_eval("Need to inspect more state before finishing.")

        first_events: list[Any] = []
        async for ev in proc._evaluate_no_tool_result("session-1", []):
            first_events.append(ev)

        assert proc._no_progress_steps == 1
        assert SessionProcessor._TOOL_USAGE_REMINDER not in proc._response_instructions
        first_statuses = [e.status for e in first_events if isinstance(e, AgentStatusEvent)]
        assert "planning_recheck" not in first_statuses

        second_events: list[Any] = []
        async for ev in proc._evaluate_no_tool_result("session-1", []):
            second_events.append(ev)

        assert proc._no_progress_steps == 2
        assert SessionProcessor._TOOL_USAGE_REMINDER in proc._response_instructions
        second_statuses = [e.status for e in second_events if isinstance(e, AgentStatusEvent)]
        assert "planning_recheck" in second_statuses

    @pytest.mark.asyncio
    async def test_tool_call_clears_tool_reminder(self) -> None:
        proc = self._build_processor_for_eval("Need to inspect more state before finishing.")
        proc._no_progress_steps = 2
        proc._response_instructions = [SessionProcessor._TOOL_USAGE_REMINDER, "keep me"]

        result, events = await proc._evaluate_goal_progress(
            ProcessorResult.CONTINUE,
            True,
            "session-1",
            [],
        )

        assert result == ProcessorResult.CONTINUE
        assert events == []
        assert proc._no_progress_steps == 0
        assert SessionProcessor._TOOL_USAGE_REMINDER not in proc._response_instructions
        assert proc._response_instructions == ["keep me"]

    @pytest.mark.asyncio
    async def test_delegate_clears_tool_reminder(self) -> None:
        proc = self._build_processor_for_eval("delegate:Planner inspect the workspace state")
        proc._response_instructions = [SessionProcessor._TOOL_USAGE_REMINDER, "keep me"]

        events: list[Any] = []
        async for ev in proc._evaluate_no_tool_result("session-1", []):
            events.append(ev)

        act_events = [e for e in events if isinstance(e, AgentActEvent)]
        assert len(act_events) == 1
        assert proc._no_progress_steps == 0
        assert SessionProcessor._TOOL_USAGE_REMINDER not in proc._response_instructions
        assert proc._response_instructions == ["keep me"]

    @pytest.mark.asyncio
    async def test_process_step_consumes_tool_reminder_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured_messages: list[dict[str, Any]] = []

        async def fake_generate(_self: Any, messages: list[dict[str, Any]], **_kwargs: Any):
            captured_messages.extend(messages)

            text_end = MagicMock()
            text_end.type = StreamEventType.TEXT_END
            text_end.data = {"full_text": "Still working on it."}
            yield text_end

            finish = MagicMock()
            finish.type = StreamEventType.FINISH
            finish.data = {"reason": "stop"}
            yield finish

        monkeypatch.setattr(
            "src.infrastructure.agent.processor.processor.LLMStream.generate",
            fake_generate,
        )

        proc = SessionProcessor(config=ProcessorConfig(model="test-model"), tools=[])
        proc._step_count = 2
        proc._response_instructions = [SessionProcessor._TOOL_USAGE_REMINDER, "keep me"]

        events = [ev async for ev in proc._process_step("session-1", [{"role": "user", "content": "hi"}])]

        assert events
        assert any(
            message["role"] == "system"
            and SessionProcessor._TOOL_USAGE_REMINDER in message["content"]
            and "keep me" in message["content"]
            for message in captured_messages
        )
        assert SessionProcessor._TOOL_USAGE_REMINDER not in proc._response_instructions
        assert proc._response_instructions == ["keep me"]

    @pytest.mark.asyncio
    async def test_process_step_keeps_tool_reminder_when_stream_fails_before_first_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_generate(_self: Any, _messages: list[dict[str, Any]], **_kwargs: Any):
            raise RuntimeError("boom")
            yield

        monkeypatch.setattr(
            "src.infrastructure.agent.processor.processor.LLMStream.generate",
            fake_generate,
        )

        proc = SessionProcessor(config=ProcessorConfig(model="test-model", max_attempts=0), tools=[])
        proc._step_count = 2
        proc._response_instructions = [SessionProcessor._TOOL_USAGE_REMINDER, "keep me"]

        with pytest.raises(RuntimeError, match="boom"):
            async for _ in proc._process_step("session-1", [{"role": "user", "content": "hi"}]):
                pass

        assert SessionProcessor._TOOL_USAGE_REMINDER in proc._response_instructions
        assert proc._response_instructions == [SessionProcessor._TOOL_USAGE_REMINDER, "keep me"]

    @pytest.mark.asyncio
    async def test_process_step_keeps_tool_reminder_when_first_stream_event_is_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_generate(_self: Any, _messages: list[dict[str, Any]], **_kwargs: Any):
            error_event = MagicMock()
            error_event.type = StreamEventType.ERROR
            error_event.data = {"message": "boom"}
            yield error_event

        monkeypatch.setattr(
            "src.infrastructure.agent.processor.processor.LLMStream.generate",
            fake_generate,
        )

        proc = SessionProcessor(config=ProcessorConfig(model="test-model", max_attempts=0), tools=[])
        proc._step_count = 2
        proc._response_instructions = [SessionProcessor._TOOL_USAGE_REMINDER, "keep me"]

        with pytest.raises(Exception, match="boom"):
            async for _ in proc._process_step("session-1", [{"role": "user", "content": "hi"}]):
                pass

        assert SessionProcessor._TOOL_USAGE_REMINDER in proc._response_instructions
        assert proc._response_instructions == [SessionProcessor._TOOL_USAGE_REMINDER, "keep me"]

    @pytest.mark.asyncio
    async def test_process_step_retry_does_not_reinject_consumed_tool_reminder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured_calls: list[list[dict[str, Any]]] = []
        attempt_state = {"count": 0}

        async def fake_generate(_self: Any, messages: list[dict[str, Any]], **_kwargs: Any):
            captured_calls.append(list(messages))
            attempt_state["count"] += 1

            text_end = MagicMock()
            text_end.type = StreamEventType.TEXT_END
            text_end.data = {"full_text": f"Attempt {attempt_state['count']}"}
            yield text_end

            if attempt_state["count"] == 1:
                raise RuntimeError("retryable")

            finish = MagicMock()
            finish.type = StreamEventType.FINISH
            finish.data = {"reason": "stop"}
            yield finish

        monkeypatch.setattr(
            "src.infrastructure.agent.processor.processor.LLMStream.generate",
            fake_generate,
        )

        proc = SessionProcessor(config=ProcessorConfig(model="test-model", max_attempts=1), tools=[])
        proc.retry_policy.is_retryable = MagicMock(return_value=True)
        proc.retry_policy.calculate_delay = MagicMock(return_value=0)
        proc._step_count = 2
        proc._response_instructions = [SessionProcessor._TOOL_USAGE_REMINDER, "keep me"]

        events = [ev async for ev in proc._process_step("session-1", [{"role": "user", "content": "hi"}])]

        assert events
        assert len(captured_calls) == 2
        assert any(
            message["role"] == "system"
            and SessionProcessor._TOOL_USAGE_REMINDER in message["content"]
            for message in captured_calls[0]
        )
        assert not any(
            message["role"] == "system"
            and SessionProcessor._TOOL_USAGE_REMINDER in message["content"]
            for message in captured_calls[1]
        )
        assert SessionProcessor._TOOL_USAGE_REMINDER not in proc._response_instructions

    @pytest.mark.asyncio
    async def test_no_progress_streak_does_not_requeue_consumed_reminder(self) -> None:
        proc = self._build_processor_for_eval("Need to inspect more state before finishing.")

        async for _ in proc._evaluate_no_tool_result("session-1", []):
            pass
        async for _ in proc._evaluate_no_tool_result("session-1", []):
            pass

        assert proc._tool_reminder_issued_for_streak is True
        assert SessionProcessor._TOOL_USAGE_REMINDER in proc._response_instructions

        proc._clear_tool_usage_reminder()
        assert SessionProcessor._TOOL_USAGE_REMINDER not in proc._response_instructions

        async for _ in proc._evaluate_no_tool_result("session-1", []):
            pass

        assert proc._no_progress_steps == 3
        assert proc._tool_reminder_issued_for_streak is True
        assert SessionProcessor._TOOL_USAGE_REMINDER not in proc._response_instructions

    @pytest.mark.asyncio
    async def test_progress_reset_allows_tool_reminder_to_be_queued_for_new_streak(self) -> None:
        proc = self._build_processor_for_eval("Need to inspect more state before finishing.")

        async for _ in proc._evaluate_no_tool_result("session-1", []):
            pass
        async for _ in proc._evaluate_no_tool_result("session-1", []):
            pass
        proc._clear_tool_usage_reminder()

        result, events = await proc._evaluate_goal_progress(
            ProcessorResult.CONTINUE,
            True,
            "session-1",
            [],
        )
        assert result == ProcessorResult.CONTINUE
        assert events == []
        assert proc._tool_reminder_issued_for_streak is False

        async for _ in proc._evaluate_no_tool_result("session-1", []):
            pass
        async for _ in proc._evaluate_no_tool_result("session-1", []):
            pass

        assert proc._tool_reminder_issued_for_streak is True
        assert SessionProcessor._TOOL_USAGE_REMINDER in proc._response_instructions

    def test_act_event_clears_tool_reminder_even_on_non_continue_result(self) -> None:
        proc = self._build_processor_for_eval("Need to inspect more state before finishing.")
        proc._response_instructions = [SessionProcessor._TOOL_USAGE_REMINDER, "keep me"]

        result, had_tool_calls = proc._classify_step_event(
            AgentActEvent(tool_name="read", tool_input={"path": "x"}, status="running"),
            ProcessorResult.COMPACT,
            False,
        )

        assert result == ProcessorResult.COMPACT
        assert had_tool_calls is True
        assert SessionProcessor._TOOL_USAGE_REMINDER not in proc._response_instructions
        assert proc._response_instructions == ["keep me"]
