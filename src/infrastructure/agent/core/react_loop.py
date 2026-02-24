"""
ReAct Loop - Core reasoning and acting cycle coordinator.

Encapsulates the core ReAct loop logic:
1. Think: Call LLM for reasoning
2. Act: Execute tool calls
3. Observe: Process results
4. Repeat until complete or blocked

This module coordinates the extracted components:
- LLMInvoker for LLM calls
- ToolExecutor for tool execution
- HITLHandler for human-in-the-loop interactions
- WorkPlanGenerator for execution planning
- DoomLoopDetector for loop detection
- CostTracker for token/cost tracking

Extracted from processor.py to reduce complexity and improve testability.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from src.domain.events.agent_events import (
    AgentCompleteEvent,
    AgentDomainEvent,
    AgentErrorEvent,
    AgentEventType,
    AgentStartEvent,
    AgentStatusEvent,
    AgentThoughtEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Protocol Definitions
# ============================================================================


class LLMInvokerProtocol(Protocol):
    """Protocol for LLM invocation."""

    async def invoke(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[AgentDomainEvent]:
        """Invoke LLM and yield events."""
        ...


class ToolExecutorProtocol(Protocol):
    """Protocol for tool execution."""

    async def execute(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        call_id: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[AgentDomainEvent]:
        """Execute tool and yield events."""
        ...


class WorkPlanGeneratorProtocol(Protocol):
    """Protocol for work plan generation."""

    def generate(
        self,
        query: str,
        available_tools: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Generate work plan from query."""
        ...


class DoomLoopDetectorProtocol(Protocol):
    """Protocol for doom loop detection."""

    def record_call(self, tool_name: str, tool_args: dict[str, Any]) -> bool:
        """Record call and check for loop. Returns True if loop detected."""
        ...

    def reset(self) -> None:
        """Reset detector state."""
        ...


class CostTrackerProtocol(Protocol):
    """Protocol for cost tracking."""

    def add_usage(self, input_tokens: int, output_tokens: int, model: str) -> float:
        """Add token usage and return cost."""
        ...

    def get_total_cost(self) -> float:
        """Get total cost."""
        ...


# ============================================================================
# Data Classes
# ============================================================================


class LoopState(str, Enum):
    """State of the ReAct loop."""

    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    WAITING = "waiting"
    COMPLETED = "completed"
    ERROR = "error"


class LoopResult(str, Enum):
    """Result of loop iteration."""

    CONTINUE = "continue"
    STOP = "stop"
    COMPLETE = "complete"
    COMPACT = "compact"


@dataclass
class LoopConfig:
    """Configuration for ReAct loop."""

    max_steps: int = 50
    max_tool_calls_per_step: int = 10
    step_timeout: float = 300.0
    enable_work_plan: bool = True
    enable_doom_loop_detection: bool = True
    context_limit: int = 200000
    max_no_progress_steps: int = 3


@dataclass
class LoopContext:
    """Context for loop execution."""

    session_id: str
    project_id: str | None = None
    user_id: str | None = None
    tenant_id: str | None = None
    sandbox_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    """Result of a single step."""

    result: LoopResult
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    text_output: str = ""
    reasoning: str = ""
    tokens_used: int = 0
    cost: float = 0.0
    error: str | None = None


@dataclass
class LoopGoalCheck:
    """Goal evaluation result for the loop."""

    achieved: bool
    should_stop: bool = False
    reason: str = ""
    source: str = "unknown"
    pending_tasks: int = 0


# ============================================================================
# ReAct Loop Coordinator
# ============================================================================


class ReActLoop:
    """
    Core ReAct loop coordinator.

    Orchestrates the think-act-observe cycle using extracted components.
    Keeps the main loop logic clean and focused.

    Responsibilities:
    - Coordinate LLM invocation
    - Manage tool execution queue
    - Track step progress
    - Handle loop termination conditions
    - Emit domain events
    """

    def __init__(
        self,
        llm_invoker: LLMInvokerProtocol | None = None,
        tool_executor: ToolExecutorProtocol | None = None,
        work_plan_generator: WorkPlanGeneratorProtocol | None = None,
        doom_loop_detector: DoomLoopDetectorProtocol | None = None,
        cost_tracker: CostTrackerProtocol | None = None,
        config: LoopConfig | None = None,
        debug_logging: bool = False,
    ) -> None:
        """
        Initialize ReAct loop coordinator.

        Args:
            llm_invoker: LLM invocation component
            tool_executor: Tool execution component
            work_plan_generator: Work plan generation component
            doom_loop_detector: Doom loop detection component
            cost_tracker: Cost tracking component
            config: Loop configuration
            debug_logging: Enable verbose logging
        """
        self._llm_invoker = llm_invoker
        self._tool_executor = tool_executor
        self._work_plan_generator = work_plan_generator
        self._doom_loop_detector = doom_loop_detector
        self._cost_tracker = cost_tracker
        self._config = config or LoopConfig()
        self._debug_logging = debug_logging

        # Loop state
        self._state = LoopState.IDLE
        self._step_count = 0
        self._abort_event: asyncio.Event | None = None

        # Work plan tracking
        self._work_plan: dict[str, Any] | None = None
        self._current_plan_step: int = 0
        self._task_statuses: dict[str, str] = {}
        self._no_progress_steps: int = 0

    @property
    def state(self) -> LoopState:
        """Get current loop state."""
        return self._state

    @property
    def step_count(self) -> int:
        """Get current step count."""
        return self._step_count

    def set_abort_event(self, event: asyncio.Event) -> None:
        """Set abort event for cancellation."""
        self._abort_event = event

    async def run(
        self,
        messages: list[dict[str, Any]],
        tools: dict[str, Any],
        context: LoopContext,
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Run the ReAct loop.

        Args:
            messages: Conversation messages
            tools: Available tools
            context: Execution context

        Yields:
            AgentDomainEvent objects for real-time streaming
        """
        self._step_count = 0
        self._state = LoopState.IDLE
        self._task_statuses = {}
        self._no_progress_steps = 0

        if self._doom_loop_detector:
            self._doom_loop_detector.reset()

        # Emit start event
        yield AgentStartEvent()
        self._state = LoopState.THINKING

        # Generate work plan if enabled
        if self._config.enable_work_plan and self._work_plan_generator:
            user_query = self._extract_user_query(messages)
            if user_query:
                work_plan = self._work_plan_generator.generate(user_query, tools)
                if work_plan:
                    self._work_plan = work_plan

        try:
            result = LoopResult.CONTINUE

            while result == LoopResult.CONTINUE:
                # Check abort
                if self._abort_event and self._abort_event.is_set():
                    yield AgentErrorEvent(message="Processing aborted", code="ABORTED")
                    self._state = LoopState.ERROR
                    return

                # Check step limit
                self._step_count += 1
                if self._step_count > self._config.max_steps:
                    yield AgentErrorEvent(
                        message=f"Maximum steps ({self._config.max_steps}) exceeded",
                        code="MAX_STEPS_EXCEEDED",
                    )
                    self._state = LoopState.ERROR
                    return

                # Process one step
                step_result = StepResult(result=LoopResult.CONTINUE)
                had_tool_calls = False
                last_thought = ""

                async for event in self._process_step(messages, tools, context):
                    yield event

                    # Check for stop conditions
                    if event.event_type == AgentEventType.ERROR:
                        step_result.result = LoopResult.STOP
                        break
                    elif event.event_type == AgentEventType.ACT:
                        had_tool_calls = True
                    elif event.event_type == AgentEventType.COMPACT_NEEDED:
                        step_result.result = LoopResult.COMPACT
                        break
                    elif (
                        event.event_type == AgentEventType.THOUGHT
                        and isinstance(event, AgentThoughtEvent)
                        and event.content
                    ):
                        last_thought = event.content
                    elif event.event_type == AgentEventType.TASK_LIST_UPDATED:
                        self._ingest_task_list_event(event)
                    elif event.event_type == AgentEventType.TASK_UPDATED:
                        self._ingest_task_update_event(event)

                # If no stop/compact, determine result from tool calls
                if step_result.result == LoopResult.CONTINUE:
                    if had_tool_calls:
                        self._no_progress_steps = 0
                        step_result.result = LoopResult.CONTINUE
                    else:
                        goal_check = self._evaluate_goal_state(last_thought)
                        if goal_check.achieved:
                            self._no_progress_steps = 0
                            yield AgentStatusEvent(status=f"goal_achieved:{goal_check.source}")
                            step_result.result = LoopResult.COMPLETE
                        elif self._is_conversational_text(last_thought):
                            # Text-only response without tool calls and without an
                            # explicit goal_achieved=false signal — treat as a
                            # deliberate conversational reply.
                            self._no_progress_steps = 0
                            yield AgentStatusEvent(
                                status="goal_achieved:conversational_response"
                            )
                            step_result.result = LoopResult.COMPLETE
                        elif goal_check.should_stop:
                            yield AgentErrorEvent(
                                message=goal_check.reason or "Goal cannot be completed",
                                code="GOAL_NOT_ACHIEVED",
                            )
                            self._state = LoopState.ERROR
                            step_result.result = LoopResult.STOP
                        else:
                            self._no_progress_steps += 1
                            yield AgentStatusEvent(status=f"goal_pending:{goal_check.source}")
                            if self._no_progress_steps > 1:
                                yield AgentStatusEvent(status="planning_recheck")
                            if self._no_progress_steps >= self._config.max_no_progress_steps:
                                yield AgentErrorEvent(
                                    message=(
                                        "Goal not achieved after "
                                        f"{self._no_progress_steps} no-progress turns. "
                                        f"{goal_check.reason or 'Replan required.'}"
                                    ),
                                    code="GOAL_NOT_ACHIEVED",
                                )
                                self._state = LoopState.ERROR
                                step_result.result = LoopResult.STOP
                            else:
                                step_result.result = LoopResult.CONTINUE

                result = step_result.result

            # Emit completion
            if result == LoopResult.COMPLETE:
                yield AgentCompleteEvent()
                self._state = LoopState.COMPLETED
            elif result == LoopResult.COMPACT:
                yield AgentStatusEvent(status="compact_needed")

        except asyncio.CancelledError:
            yield AgentErrorEvent(message="Processing cancelled", code="CANCELLED")
            self._state = LoopState.ERROR
        except Exception as e:
            logger.error(f"ReAct loop error: {e}", exc_info=True)
            yield AgentErrorEvent(message=str(e), code=type(e).__name__)
            self._state = LoopState.ERROR

    def _ingest_task_list_event(self, event: AgentDomainEvent) -> None:
        """Update task status cache from a task list event."""
        tasks = getattr(event, "tasks", None)
        if not isinstance(tasks, list):
            return
        for task in tasks:
            if isinstance(task, dict):
                task_id = str(task.get("id", "")).strip()
                status = str(task.get("status", "")).strip().lower()
                if task_id and status:
                    self._task_statuses[task_id] = status

    def _ingest_task_update_event(self, event: AgentDomainEvent) -> None:
        """Update task status cache from a single task update event."""
        task_id = str(getattr(event, "task_id", "")).strip()
        status = str(getattr(event, "status", "")).strip().lower()
        if task_id and status:
            self._task_statuses[task_id] = status

    def _evaluate_goal_state(self, thought_text: str) -> LoopGoalCheck:
        """Evaluate completion from tasks first, then explicit self-check text."""
        task_goal = self._evaluate_task_goal()
        if task_goal is not None:
            return task_goal
        return self._evaluate_thought_goal(thought_text)

    def _evaluate_task_goal(self) -> LoopGoalCheck | None:
        """Evaluate completion from cached task statuses."""
        if not self._task_statuses:
            return None

        statuses = [s.lower() for s in self._task_statuses.values()]
        pending_count = sum(1 for s in statuses if s in {"pending", "in_progress"})
        failed_count = sum(1 for s in statuses if s == "failed")
        unknown_count = sum(1 for s in statuses if s not in {"pending", "in_progress", "completed", "cancelled", "failed"})
        pending_count += unknown_count

        if pending_count > 0:
            return LoopGoalCheck(
                achieved=False,
                reason=f"{pending_count} task(s) still in progress",
                source="tasks",
                pending_tasks=pending_count,
            )
        if failed_count > 0:
            return LoopGoalCheck(
                achieved=False,
                should_stop=True,
                reason=f"{failed_count} task(s) failed",
                source="tasks",
            )
        return LoopGoalCheck(
            achieved=True,
            reason="All tasks reached terminal success states",
            source="tasks",
        )

    def _evaluate_thought_goal(self, thought_text: str) -> LoopGoalCheck:
        """Evaluate no-task completion from explicit self-check in thought text."""
        parsed = self._extract_goal_json(thought_text)
        if parsed and isinstance(parsed.get("goal_achieved"), bool):
            achieved = bool(parsed["goal_achieved"])
            reason = str(parsed.get("reason", "")).strip()
            return LoopGoalCheck(
                achieved=achieved,
                reason=reason or ("Goal achieved" if achieved else "Goal not achieved"),
                source="thought_self_check",
            )

        if self._has_explicit_completion_phrase(thought_text):
            return LoopGoalCheck(
                achieved=True,
                reason="Assistant declared completion in thought",
                source="thought_text",
            )

        return LoopGoalCheck(
            achieved=False,
            reason="No explicit goal_achieved signal in thought",
            source="thought_self_check",
        )

    def _extract_goal_json(self, text: str) -> dict[str, Any] | None:
        """Extract a JSON object from thought text."""
        stripped = text.strip()
        if not stripped:
            return None

        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        start_idx = stripped.find("{")
        while start_idx >= 0:
            depth = 0
            in_string = False
            escape_next = False
            for index in range(start_idx, len(stripped)):
                char = stripped[index]

                if in_string:
                    if escape_next:
                        escape_next = False
                    elif char == "\\":
                        escape_next = True
                    elif char == '"':
                        in_string = False
                    continue

                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = stripped[start_idx : index + 1]
                        try:
                            parsed = json.loads(candidate)
                        except json.JSONDecodeError:
                            break
                        if isinstance(parsed, dict):
                            return parsed
                        break
            start_idx = stripped.find("{", start_idx + 1)

        return None

    def _has_explicit_completion_phrase(self, text: str) -> bool:
        """Conservative completion phrase detection."""
        lowered = text.strip().lower()
        if not lowered:
            return False

        positive_patterns = (
            r"\bgoal\s+achieved\b",
            r"\btask\s+completed\b",
            r"\ball\s+tasks?\s+(?:are\s+)?done\b",
            r"\bwork\s+(?:is\s+)?complete\b",
            r"\bsuccessfully\s+completed\b",
        )
        negative_patterns = (
            r"\bnot\s+(?:yet\s+)?done\b",
            r"\bnot\s+(?:yet\s+)?complete\b",
            r"\bstill\s+working\b",
            r"\bin\s+progress\b",
            r"\bremaining\b",
        )

        has_positive = any(re.search(pattern, lowered) for pattern in positive_patterns)
        has_negative = any(re.search(pattern, lowered) for pattern in negative_patterns)
        return has_positive and not has_negative

    async def _process_step(
        self,
        messages: list[dict[str, Any]],
        tools: dict[str, Any],
        context: LoopContext,
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Process a single step in the loop.

        Args:
            messages: Current messages
            tools: Available tools
            context: Execution context

        Yields:
            AgentDomainEvent objects
        """
        if self._debug_logging:
            logger.debug(f"[ReActLoop] Starting step {self._step_count}")

        # Invoke LLM
        self._state = LoopState.THINKING
        tool_calls_to_execute = []

        if self._llm_invoker:
            tools_list = [
                {"type": "function", "function": t} for t in tools.values()
            ] if tools else []

            async for event in self._llm_invoker.invoke(
                messages, tools_list, {"step": self._step_count}
            ):
                yield event

                # Collect tool calls
                if event.event_type == AgentEventType.ACT:
                    tool_calls_to_execute.append({
                        "name": event.tool_name,
                        "args": event.tool_input,
                        "call_id": event.call_id,
                    })

        # Execute tool calls
        if tool_calls_to_execute:
            self._state = LoopState.ACTING

            for tool_call in tool_calls_to_execute[:self._config.max_tool_calls_per_step]:
                # Check doom loop
                if self._config.enable_doom_loop_detection and self._doom_loop_detector:
                    if self._doom_loop_detector.record_call(
                        tool_call["name"], tool_call["args"]
                    ):
                        yield AgentErrorEvent(
                            message="Doom loop detected",
                            code="DOOM_LOOP_DETECTED",
                        )
                        return

                # Execute tool
                if self._tool_executor:
                    async for event in self._tool_executor.execute(
                        tool_call["name"],
                        tool_call["args"],
                        tool_call["call_id"],
                        context={
                            "session_id": context.session_id,
                            "project_id": context.project_id,
                        },
                    ):
                        yield event

            self._state = LoopState.OBSERVING
            self._current_plan_step += 1

    def _is_conversational_text(self, text: str) -> bool:
        """Check if text is a conversational response (not a goal-check JSON).

        Returns True when the LLM produced substantive text that is NOT a
        structured goal_achieved signal, indicating a deliberate conversational
        reply that should terminate the loop.
        """
        stripped = text.strip()
        if len(stripped) < 2:
            return False
        # If the text contains a goal_achieved JSON signal, it's a goal-check
        # response, not conversational text.
        return "goal_achieved" not in stripped

    def _extract_user_query(self, messages: list[dict[str, Any]]) -> str | None:
        """Extract user query from messages."""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            return part.get("text", "")
        return None


# ============================================================================
# Singleton Management
# ============================================================================

_loop: ReActLoop | None = None


def get_react_loop() -> ReActLoop:
    """
    Get singleton ReActLoop instance.

    Raises:
        RuntimeError if loop not initialized
    """
    global _loop
    if _loop is None:
        raise RuntimeError(
            "ReActLoop not initialized. "
            "Call set_react_loop() or create_react_loop() first."
        )
    return _loop


def set_react_loop(loop: ReActLoop) -> None:
    """Set singleton ReActLoop instance."""
    global _loop
    _loop = loop


def create_react_loop(
    llm_invoker: LLMInvokerProtocol | None = None,
    tool_executor: ToolExecutorProtocol | None = None,
    work_plan_generator: WorkPlanGeneratorProtocol | None = None,
    doom_loop_detector: DoomLoopDetectorProtocol | None = None,
    cost_tracker: CostTrackerProtocol | None = None,
    config: LoopConfig | None = None,
    debug_logging: bool = False,
) -> ReActLoop:
    """
    Create and set singleton ReActLoop.

    Returns:
        Created ReActLoop instance
    """
    global _loop
    _loop = ReActLoop(
        llm_invoker=llm_invoker,
        tool_executor=tool_executor,
        work_plan_generator=work_plan_generator,
        doom_loop_detector=doom_loop_detector,
        cost_tracker=cost_tracker,
        config=config,
        debug_logging=debug_logging,
    )
    return _loop
