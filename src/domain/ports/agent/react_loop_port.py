"""
ReAct Loop Port - Domain interface for the core ReAct reasoning loop.

The ReAct (Reasoning + Acting) loop is the core execution pattern
where the agent thinks, acts (uses tools), and observes in a cycle.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, runtime_checkable


class ReActStepType(str, Enum):
    """Types of ReAct loop steps."""

    THOUGHT = "thought"  # Agent reasoning
    ACTION = "action"  # Tool invocation
    OBSERVATION = "observation"  # Tool result
    ANSWER = "answer"  # Final answer
    ERROR = "error"  # Error occurred


class LoopTerminationReason(str, Enum):
    """Reasons for loop termination."""

    COMPLETE = "complete"  # Task completed successfully
    MAX_STEPS = "max_steps"  # Reached maximum steps
    TIMEOUT = "timeout"  # Execution timeout
    USER_CANCEL = "user_cancel"  # User cancelled
    ERROR = "error"  # Error occurred
    DOOM_LOOP = "doom_loop"  # Detected repeating pattern


@dataclass
class ReActLoopConfig:
    """Configuration for ReAct loop execution.

    Attributes:
        max_steps: Maximum number of ReAct steps
        timeout: Total execution timeout in seconds
        step_timeout: Per-step timeout in seconds
        enable_doom_loop_detection: Detect and break infinite loops
        doom_loop_threshold: Steps before doom loop detection
        enable_work_plan: Generate work plan for complex tasks
        parallel_tool_execution: Execute independent tools in parallel
    """

    max_steps: int = 20
    timeout: Optional[float] = None
    step_timeout: Optional[float] = 60.0
    enable_doom_loop_detection: bool = True
    doom_loop_threshold: int = 5
    enable_work_plan: bool = True
    parallel_tool_execution: bool = True


@dataclass
class ReActLoopContext:
    """Context for ReAct loop execution.

    Attributes:
        conversation_id: Conversation identifier
        project_id: Project context
        user_id: User running the loop
        messages: Conversation history
        tools: Available tools
        system_prompt: System prompt to use
        variables: Template variables
        metadata: Additional context
    """

    conversation_id: str
    project_id: str
    user_id: Optional[str] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)
    tools: List[Dict[str, Any]] = field(default_factory=list)
    system_prompt: Optional[str] = None
    variables: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReActStep:
    """A single step in the ReAct loop.

    Attributes:
        step_type: Type of step
        step_number: Step number in loop
        content: Step content (thought, action, observation)
        tool_calls: Tool calls made (for ACTION steps)
        tool_results: Tool results (for OBSERVATION steps)
        tokens: Token usage for this step
        duration_ms: Step duration
        metadata: Additional step metadata
    """

    step_type: ReActStepType
    step_number: int
    content: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    tokens: Dict[str, int] = field(default_factory=dict)
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReActLoopResult:
    """Result from ReAct loop execution.

    Attributes:
        success: Whether loop completed successfully
        answer: Final answer (if any)
        termination_reason: Why loop terminated
        steps: All executed steps
        total_tokens: Total token usage
        total_cost: Total cost estimate
        duration_ms: Total execution duration
        error: Error message if failed
    """

    success: bool
    answer: Optional[str] = None
    termination_reason: LoopTerminationReason = LoopTerminationReason.COMPLETE
    steps: List[ReActStep] = field(default_factory=list)
    total_tokens: Dict[str, int] = field(default_factory=dict)
    total_cost: float = 0.0
    duration_ms: Optional[float] = None
    error: Optional[str] = None

    @property
    def step_count(self) -> int:
        """Get number of steps executed."""
        return len(self.steps)


@runtime_checkable
class ReActLoopPort(Protocol):
    """
    Protocol for the ReAct reasoning loop.

    Implementations handle the core think-act-observe cycle
    that powers agent reasoning.

    Example:
        class ReActLoop(ReActLoopPort):
            async def run(
                self,
                context: ReActLoopContext,
                config: ReActLoopConfig,
            ) -> AsyncIterator[Dict[str, Any]]:
                for step in range(config.max_steps):
                    # Think: Get LLM response
                    response = await self.llm.invoke(...)
                    yield {"type": "thought", "content": response.content}

                    # Act: Execute tool calls
                    if response.tool_calls:
                        results = await self.tools.execute_batch(...)
                        yield {"type": "observation", "results": results}

                    # Check if done
                    if self._is_complete(response):
                        yield {"type": "answer", "content": ...}
                        return
    """

    async def run(
        self,
        context: ReActLoopContext,
        config: Optional[ReActLoopConfig] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Run the ReAct loop, yielding events.

        Args:
            context: Loop execution context
            config: Loop configuration (uses defaults if None)

        Yields:
            Events during loop execution (thoughts, actions, observations)

        Returns:
            Final loop result via COMPLETE event
        """
        ...

    async def run_single_step(
        self,
        context: ReActLoopContext,
        step_number: int,
    ) -> ReActStep:
        """
        Run a single ReAct step.

        Args:
            context: Loop execution context
            step_number: Current step number

        Returns:
            The executed step
        """
        ...

    def should_terminate(
        self,
        steps: List[ReActStep],
        config: ReActLoopConfig,
    ) -> Optional[LoopTerminationReason]:
        """
        Check if loop should terminate.

        Args:
            steps: Steps executed so far
            config: Loop configuration

        Returns:
            Termination reason if should stop, None otherwise
        """
        ...
