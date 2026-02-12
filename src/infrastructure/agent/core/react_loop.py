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
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol

from src.domain.events.agent_events import (
    AgentCompleteEvent,
    AgentDomainEvent,
    AgentErrorEvent,
    AgentEventType,
    AgentStartEvent,
    AgentStatusEvent,
    AgentStepEndEvent,
    AgentStepStartEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Protocol Definitions
# ============================================================================


class LLMInvokerProtocol(Protocol):
    """Protocol for LLM invocation."""

    async def invoke(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[AgentDomainEvent]:
        """Invoke LLM and yield events."""
        ...


class ToolExecutorProtocol(Protocol):
    """Protocol for tool execution."""

    async def execute(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        call_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[AgentDomainEvent]:
        """Execute tool and yield events."""
        ...


class WorkPlanGeneratorProtocol(Protocol):
    """Protocol for work plan generation."""

    def generate(
        self,
        query: str,
        available_tools: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Generate work plan from query."""
        ...


class DoomLoopDetectorProtocol(Protocol):
    """Protocol for doom loop detection."""

    def record_call(self, tool_name: str, tool_args: Dict[str, Any]) -> bool:
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


@dataclass
class LoopContext:
    """Context for loop execution."""

    session_id: str
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    sandbox_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    """Result of a single step."""

    result: LoopResult
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    text_output: str = ""
    reasoning: str = ""
    tokens_used: int = 0
    cost: float = 0.0
    error: Optional[str] = None


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
        llm_invoker: Optional[LLMInvokerProtocol] = None,
        tool_executor: Optional[ToolExecutorProtocol] = None,
        work_plan_generator: Optional[WorkPlanGeneratorProtocol] = None,
        doom_loop_detector: Optional[DoomLoopDetectorProtocol] = None,
        cost_tracker: Optional[CostTrackerProtocol] = None,
        config: Optional[LoopConfig] = None,
        debug_logging: bool = False,
    ):
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
        self._abort_event: Optional[asyncio.Event] = None

        # Work plan tracking
        self._work_plan: Optional[Dict[str, Any]] = None
        self._current_plan_step: int = 0

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
        messages: List[Dict[str, Any]],
        tools: Dict[str, Any],
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

                async for event in self._process_step(messages, tools, context):
                    yield event

                    # Check for stop conditions
                    if event.event_type == AgentEventType.ERROR:
                        step_result.result = LoopResult.STOP
                        break
                    elif event.event_type == AgentEventType.STEP_FINISH:
                        finish_reason = getattr(event, "finish_reason", "stop")
                        if finish_reason == "stop":
                            step_result.result = LoopResult.COMPLETE
                        elif finish_reason == "tool_calls":
                            step_result.result = LoopResult.CONTINUE
                        else:
                            step_result.result = LoopResult.COMPLETE
                    elif event.event_type == AgentEventType.COMPACT_NEEDED:
                        step_result.result = LoopResult.COMPACT
                        break

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

    async def _process_step(
        self,
        messages: List[Dict[str, Any]],
        tools: Dict[str, Any],
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
        # Get step description from work plan
        step_description = f"Step {self._step_count}"
        if self._work_plan and self._current_plan_step < len(
            self._work_plan.get("steps", [])
        ):
            step_info = self._work_plan["steps"][self._current_plan_step]
            step_description = step_info.get("description", step_description)

        # Emit step start
        yield AgentStepStartEvent(step_index=self._step_count, description=step_description)

        if self._debug_logging:
            logger.debug(f"[ReActLoop] Starting step {self._step_count}: {step_description}")

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

        # Emit step end
        yield AgentStepEndEvent(
            step_index=self._step_count,
            tool_calls_count=len(tool_calls_to_execute),
        )

    def _extract_user_query(self, messages: List[Dict[str, Any]]) -> Optional[str]:
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

_loop: Optional[ReActLoop] = None


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
    llm_invoker: Optional[LLMInvokerProtocol] = None,
    tool_executor: Optional[ToolExecutorProtocol] = None,
    work_plan_generator: Optional[WorkPlanGeneratorProtocol] = None,
    doom_loop_detector: Optional[DoomLoopDetectorProtocol] = None,
    cost_tracker: Optional[CostTrackerProtocol] = None,
    config: Optional[LoopConfig] = None,
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
