"""Drive one ReAct turn with the selected release and the host's scoped effects."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from plugins.business.agent.engine.processor.model_step_control_v2 import (
    ModelStepInterruptedV2,
    await_model_control_v2,
)
from plugins.business.agent.engine.processor.processor import ProcessorResult, ProcessorState
from src.domain.events.agent_events import AgentErrorEvent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from plugins.business.agent.engine.processor.processor import ProcessorEvent, SessionProcessor

logger = logging.getLogger(__name__)


async def run_turn(  # noqa: C901, PLR0912, PLR0915
    processor: SessionProcessor,
    session_id: str,
    messages: list[dict[str, Any]],
    advance: Callable[[str, str, int], Awaitable[str]],
) -> AsyncIterator[ProcessorEvent]:
    processor._state = ProcessorState.THINKING

    await processor._notify_plugin_hook(
        "on_session_start",
        {
            "session_id": session_id,
            "message_count": len(messages),
            **processor._runtime_hook_context_fields(),
        },
    )

    # --- Command interception: handle slash commands before ReAct loop ---
    cmd_events = await processor._try_intercept_command(messages)
    if cmd_events is not None:
        for evt in cmd_events:
            yield evt
        return

    try:
        processor._saw_task_events = False
        processor._pending_completion_status = None
        processor._artifact_count = 0
        result = ProcessorResult.CONTINUE

        phase = "start"
        had_tool_calls = False
        completed_step_context_length: int | None = None
        while True:
            action = await advance(phase, result.value, processor._step_count)
            if (
                action == "finish"
                and phase in {"judged", "observed"}
                and result != ProcessorResult.CONTINUE
            ):
                break
            if action == "stop":
                yield AgentErrorEvent(
                    message="Agent loop stopped this turn", code="AGENT_LOOP_STOPPED"
                )
                processor._state = ProcessorState.ERROR
                result = ProcessorResult.STOP
                break

            if (
                action == "step"
                and phase in {"start", "observed", "restart"}
                and result == ProcessorResult.CONTINUE
            ):
                abort_event = processor._check_abort_and_limits()
                if abort_event is not None:
                    yield abort_event
                    processor._state = ProcessorState.ERROR
                    return
                had_tool_calls = False
                completed_step_context_length = None
            elif action == "judge" and phase == "stepped":
                pass
            elif action == "observe" and phase == "judged" and result == ProcessorResult.CONTINUE:
                processor._append_tool_results_to_messages(messages)
                for event in await processor._check_agent_announcements(messages):
                    yield event
                for event in await processor._check_control_channel(messages):
                    yield event
                    if isinstance(event, AgentErrorEvent):
                        result = ProcessorResult.STOP
                        break
                phase = "observed"
                continue
            else:
                raise ValueError(f"invalid ReAct instruction {action!r} for {phase}/{result.value}")

            try:
                if action == "step":
                    async for event in processor._process_step(session_id, messages):
                        yield event
                        result, had_tool_calls = processor._classify_step_event(
                            event, result, had_tool_calls
                        )
                        if result != ProcessorResult.CONTINUE:
                            break
                    completed_step_context_length = len(messages)
                    phase = "stepped"
                else:
                    result, progress_events = await await_model_control_v2(
                        processor._evaluate_goal_progress(
                            result, had_tool_calls, session_id, messages
                        ),
                        lambda: processor._poll_model_control_v2(messages),
                    )
                    for event in progress_events:
                        yield event
                    phase = "judged"
            except ModelStepInterruptedV2 as control:
                for control_event in control.events:
                    yield control_event
                if not control.restart:
                    result = ProcessorResult.STOP
                    break
                if completed_step_context_length is not None:
                    # Preserve tool results that completed before a steer arrived.
                    messages[completed_step_context_length:completed_step_context_length] = (
                        processor._current_step_model_messages()
                    )
                result = ProcessorResult.CONTINUE
                phase = "restart"

        # Emit completion events
        async for event in processor._emit_completion_events(result, session_id, messages):
            yield event

        effective_result = (
            processor._last_process_result if result == ProcessorResult.COMPLETE else result
        )
        await processor._notify_plugin_hook(
            "on_session_end",
            {
                "session_id": session_id,
                "step_count": processor._step_count,
                **processor._runtime_hook_context_fields(),
                "result": (
                    effective_result.name
                    if hasattr(effective_result, "name")
                    else str(effective_result)
                ),
            },
        )
    except Exception as e:
        logger.error(f"Processor error: {e}", exc_info=True)
        await processor._notify_plugin_hook(
            "on_error",
            {
                "session_id": session_id,
                **processor._runtime_hook_context_fields(),
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        yield AgentErrorEvent(message=str(e), code=type(e).__name__)
        processor._state = ProcessorState.ERROR
