"""
LLM Invoker - High-level LLM invocation with retry and event processing.

Encapsulates:
- StreamConfig creation from processor config
- Retry logic with exponential backoff
- LLM stream event processing and transformation
- Usage/cost calculation delegation

Extracted from processor.py to reduce complexity and improve testability.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Protocol

from src.domain.events.agent_events import (
    AgentActEvent,
    AgentCompactNeededEvent,
    AgentCostUpdateEvent,
    AgentDomainEvent,
    AgentErrorEvent,
    AgentRetryEvent,
    AgentTextDeltaEvent,
    AgentTextEndEvent,
    AgentTextStartEvent,
    AgentThoughtDeltaEvent,
    AgentThoughtEvent,
)

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependency
# LLMStream, StreamConfig, StreamEventType are imported in methods that need them


# ============================================================================
# Protocol Definitions (for dependency injection)
# ============================================================================


class RetryPolicyProtocol(Protocol):
    """Protocol for retry policy."""

    def is_retryable(self, error: Exception) -> bool:
        """Check if error is retryable."""
        ...

    def calculate_delay(self, attempt: int, error: Exception) -> int:
        """Calculate delay in milliseconds for next retry."""
        ...


class CostTrackerProtocol(Protocol):
    """Protocol for cost tracking."""

    def calculate(
        self, usage: Dict[str, int], model_name: str
    ) -> Any:  # Returns CostResult-like object
        """Calculate cost from usage."""
        ...

    def needs_compaction(self, tokens: Any) -> bool:  # tokens is TokenUsage-like
        """Check if context compaction is needed."""
        ...


class ToolProtocol(Protocol):
    """Protocol for tool definitions."""

    def to_openai_format(self) -> Dict[str, Any]:
        """Convert tool to OpenAI function format."""
        ...


class MessageProtocol(Protocol):
    """Protocol for tracking current message state."""

    def add_text(self, text: str) -> None:
        """Add text content."""
        ...

    def add_reasoning(self, reasoning: str) -> None:
        """Add reasoning content."""
        ...

    def add_tool_call(
        self, call_id: str, tool: str, input: Dict[str, Any]
    ) -> "ToolPartProtocol":
        """Add a tool call and return the tool part."""
        ...


class ToolPartProtocol(Protocol):
    """Protocol for tool call part."""

    input: Dict[str, Any]
    status: Any  # ToolState
    start_time: float
    tool_execution_id: str


# ============================================================================
# Data Classes
# ============================================================================


class InvokerState(str, Enum):
    """States for LLM invoker."""

    IDLE = "idle"
    STREAMING = "streaming"
    RETRYING = "retrying"
    ERROR = "error"
    COMPLETE = "complete"


@dataclass
class TokenUsage:
    """Token usage tracking."""

    input: int = 0
    output: int = 0
    reasoning: int = 0
    cache_read: int = 0
    cache_write: int = 0

    def to_dict(self) -> Dict[str, int]:
        """Convert to dictionary."""
        return {
            "input": self.input,
            "output": self.output,
            "reasoning": self.reasoning,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
        }


@dataclass
class InvocationConfig:
    """Configuration for a single LLM invocation."""

    model: str
    api_key: str
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    max_attempts: int = 3
    llm_client: Optional[Any] = None  # Optional LiteLLMClient for unified resilience


@dataclass
class InvocationContext:
    """Context for LLM invocation tracking."""

    step_count: int
    langfuse_context: Optional[Dict[str, Any]] = None
    abort_event: Optional[asyncio.Event] = None


@dataclass
class InvocationResult:
    """Result of LLM invocation step."""

    text: str = ""
    reasoning: str = ""
    tool_calls_completed: List[str] = field(default_factory=list)
    tokens: TokenUsage = field(default_factory=TokenUsage)
    cost: float = 0.0
    finish_reason: str = "stop"
    trace_url: Optional[str] = None


# ============================================================================
# LLM Invoker
# ============================================================================


class LLMInvoker:
    """
    High-level LLM invocation handler.

    Responsibilities:
    - Create LLMStream with proper configuration
    - Handle retry logic with exponential backoff
    - Process stream events and emit domain events
    - Delegate cost calculation to CostTracker
    - Coordinate with tool execution callbacks
    """

    def __init__(
        self,
        retry_policy: RetryPolicyProtocol,
        cost_tracker: CostTrackerProtocol,
        debug_logging: bool = False,
    ):
        """
        Initialize LLM invoker.

        Args:
            retry_policy: Policy for retry decisions and delays
            cost_tracker: Tracker for cost calculation
            debug_logging: Enable verbose debug logging
        """
        self._retry_policy = retry_policy
        self._cost_tracker = cost_tracker
        self._debug_logging = debug_logging
        self._state = InvokerState.IDLE

    @property
    def state(self) -> InvokerState:
        """Get current invoker state."""
        return self._state

    async def invoke(
        self,
        config: InvocationConfig,
        messages: List[Dict[str, Any]],
        tools: Dict[str, ToolProtocol],
        context: InvocationContext,
        current_message: MessageProtocol,
        pending_tool_calls: Dict[str, ToolPartProtocol],
        work_plan_steps: List[Dict[str, Any]],
        tool_to_step_mapping: Dict[str, int],
        execute_tool_callback: Callable[
            [str, str, str, Dict[str, Any]], AsyncIterator[AgentDomainEvent]
        ],
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Invoke LLM and stream events.

        Args:
            config: Invocation configuration
            messages: Messages to send to LLM
            tools: Available tools
            context: Invocation context
            current_message: Message being built
            pending_tool_calls: Map of pending tool calls
            work_plan_steps: Work plan steps for tracking
            tool_to_step_mapping: Tool name to step index mapping
            execute_tool_callback: Callback for tool execution

        Yields:
            Domain events from LLM stream and tool execution
        """
        # Lazy import to avoid circular dependency
        from src.infrastructure.agent.core.llm_stream import LLMStream, StreamConfig

        self._state = InvokerState.STREAMING

        # Prepare tools for LLM
        tools_for_llm = [t.to_openai_format() for t in tools.values()] if tools else None

        if self._debug_logging:
            logger.debug(
                f"[LLMInvoker] Prepared {len(tools_for_llm) if tools_for_llm else 0} tools, "
                f"step={context.step_count}"
            )

        # Create stream config
        stream_config = StreamConfig(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            tools=tools_for_llm,
        )

        # Create LLM stream with optional client for unified resilience
        llm_stream = LLMStream(stream_config, llm_client=config.llm_client)

        # Track state for this step
        result = InvocationResult()
        current_plan_step: Optional[int] = None

        # Process LLM stream with retry
        attempt = 0
        while True:
            try:
                # Build step-specific langfuse context
                step_langfuse_context = None
                if context.langfuse_context:
                    step_langfuse_context = {
                        **context.langfuse_context,
                        "extra": {
                            **context.langfuse_context.get("extra", {}),
                            "step_number": context.step_count,
                            "model": config.model,
                        },
                    }

                async for event in llm_stream.generate(
                    messages, langfuse_context=step_langfuse_context
                ):
                    # Check abort
                    if context.abort_event and context.abort_event.is_set():
                        raise asyncio.CancelledError("Aborted")

                    # Process stream events
                    async for domain_event in self._process_stream_event(
                        event=event,
                        result=result,
                        config=config,
                        context=context,
                        current_message=current_message,
                        pending_tool_calls=pending_tool_calls,
                        work_plan_steps=work_plan_steps,
                        tool_to_step_mapping=tool_to_step_mapping,
                        execute_tool_callback=execute_tool_callback,
                        current_plan_step_holder=[current_plan_step],
                    ):
                        yield domain_event

                # Step completed successfully
                break

            except asyncio.CancelledError:
                self._state = InvokerState.ERROR
                raise

            except Exception as e:
                # Check if retryable
                if (
                    self._retry_policy.is_retryable(e)
                    and attempt < config.max_attempts
                ):
                    attempt += 1
                    delay_ms = self._retry_policy.calculate_delay(attempt, e)

                    self._state = InvokerState.RETRYING
                    yield AgentRetryEvent(
                        attempt=attempt,
                        delay_ms=delay_ms,
                        message=str(e),
                    )

                    # Wait before retry
                    await asyncio.sleep(delay_ms / 1000)
                    continue
                else:
                    # Not retryable or max retries exceeded
                    self._state = InvokerState.ERROR
                    raise

        # Update message metadata
        current_message.tokens = result.tokens.to_dict()
        current_message.cost = result.cost
        current_message.finish_reason = result.finish_reason
        current_message.completed_at = time.time()

        # Build trace URL if Langfuse context is available
        _trace_url = self._build_trace_url(context)

        self._state = InvokerState.COMPLETE

    async def _process_stream_event(
        self,
        event: Any,  # StreamEvent
        result: InvocationResult,
        config: InvocationConfig,
        context: InvocationContext,
        current_message: MessageProtocol,
        pending_tool_calls: Dict[str, ToolPartProtocol],
        work_plan_steps: List[Dict[str, Any]],
        tool_to_step_mapping: Dict[str, int],
        execute_tool_callback: Callable,
        current_plan_step_holder: List[Optional[int]],
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Process a single stream event and yield domain events.

        Args:
            event: Stream event from LLMStream
            result: Result object being built
            config: Invocation config
            context: Invocation context
            current_message: Message being built
            pending_tool_calls: Pending tool calls map
            work_plan_steps: Work plan steps
            tool_to_step_mapping: Tool to step mapping
            execute_tool_callback: Tool execution callback
            current_plan_step_holder: Mutable holder for current step index
        """
        # Lazy import to avoid circular dependency
        from src.infrastructure.agent.core.llm_stream import StreamEventType

        if event.type == StreamEventType.TEXT_START:
            yield AgentTextStartEvent()

        elif event.type == StreamEventType.TEXT_DELTA:
            delta = event.data.get("delta", "")
            result.text += delta
            yield AgentTextDeltaEvent(delta=delta)

        elif event.type == StreamEventType.TEXT_END:
            full_text = event.data.get("full_text", result.text)
            current_message.add_text(full_text)
            yield AgentTextEndEvent(full_text=full_text)

        elif event.type == StreamEventType.REASONING_START:
            yield AgentThoughtEvent(content="", thought_level="reasoning")

        elif event.type == StreamEventType.REASONING_DELTA:
            delta = event.data.get("delta", "")
            result.reasoning += delta
            yield AgentThoughtDeltaEvent(delta=delta)

        elif event.type == StreamEventType.REASONING_END:
            full_reasoning = event.data.get("full_text", result.reasoning)
            current_message.add_reasoning(full_reasoning)
            yield AgentThoughtEvent(content=full_reasoning, thought_level="reasoning")

        elif event.type == StreamEventType.TOOL_CALL_START:
            call_id = event.data.get("call_id", "")
            tool_name = event.data.get("name", "")

            # Create tool part (don't emit act event yet - wait for complete args)
            tool_part = current_message.add_tool_call(
                call_id=call_id,
                tool=tool_name,
                input={},
            )
            pending_tool_calls[call_id] = tool_part

        elif event.type == StreamEventType.TOOL_CALL_END:
            async for tool_event in self._handle_tool_call_end(
                event=event,
                result=result,
                context=context,
                pending_tool_calls=pending_tool_calls,
                work_plan_steps=work_plan_steps,
                tool_to_step_mapping=tool_to_step_mapping,
                execute_tool_callback=execute_tool_callback,
                current_plan_step_holder=current_plan_step_holder,
            ):
                yield tool_event

        elif event.type == StreamEventType.USAGE:
            async for usage_event in self._handle_usage_event(
                event=event,
                result=result,
                config=config,
            ):
                yield usage_event

        elif event.type == StreamEventType.FINISH:
            result.finish_reason = event.data.get("reason", "stop")

        elif event.type == StreamEventType.ERROR:
            error_msg = event.data.get("message", "Unknown error")
            raise Exception(error_msg)

    async def _handle_tool_call_end(
        self,
        event: Any,
        result: InvocationResult,
        context: InvocationContext,
        pending_tool_calls: Dict[str, ToolPartProtocol],
        work_plan_steps: List[Dict[str, Any]],
        tool_to_step_mapping: Dict[str, int],
        execute_tool_callback: Callable,
        current_plan_step_holder: List[Optional[int]],
    ) -> AsyncIterator[AgentDomainEvent]:
        """Handle tool call end event."""
        call_id = event.data.get("call_id", "")
        tool_name = event.data.get("name", "")
        arguments = event.data.get("arguments", {})

        # Validate tool call
        validation_error = self._validate_tool_call(call_id, tool_name, arguments)
        if validation_error:
            logger.error(f"[LLMInvoker] Validation failed: {validation_error}")
            yield AgentErrorEvent(
                message=f"Tool call validation failed: {validation_error}",
                code="VALIDATION_ERROR",
            )
            return

        # Update tool part
        if call_id in pending_tool_calls:
            tool_part = pending_tool_calls[call_id]
            tool_part.input = arguments
            tool_part.status = "running"  # ToolState.RUNNING
            tool_part.start_time = time.time()
            tool_part.tool_execution_id = f"exec_{uuid.uuid4().hex[:12]}"

            # Get step number from tool-to-step mapping
            step_number = tool_to_step_mapping.get(tool_name)

            # Update work plan step status
            if step_number is not None and step_number < len(work_plan_steps):
                work_plan_steps[step_number]["status"] = "running"
                current_plan_step_holder[0] = step_number

            yield AgentActEvent(
                tool_name=tool_name,
                tool_input=arguments,
                call_id=call_id,
                status="running",
                tool_execution_id=tool_part.tool_execution_id,
            )

            # Execute tool via callback
            session_id = ""  # Will be provided by processor
            async for tool_event in execute_tool_callback(
                session_id, call_id, tool_name, arguments
            ):
                yield tool_event

            result.tool_calls_completed.append(call_id)

    def _validate_tool_call(
        self,
        call_id: str,
        tool_name: str,
        arguments: Any,
    ) -> Optional[str]:
        """
        Validate tool call parameters.

        Returns:
            Error message if validation fails, None if valid
        """
        # Validate tool_name
        if not isinstance(tool_name, str) or not tool_name.strip():
            return f"Invalid tool_name: {tool_name!r}"

        # Validate arguments is a dict
        if not isinstance(arguments, dict):
            return f"Invalid tool_input type: {type(arguments).__name__}, expected dict"

        # Validate call_id if provided
        if call_id and not isinstance(call_id, str):
            return f"Invalid call_id type: {type(call_id).__name__}"

        return None

    async def _handle_usage_event(
        self,
        event: Any,
        result: InvocationResult,
        config: InvocationConfig,
    ) -> AsyncIterator[AgentDomainEvent]:
        """Handle usage event and emit cost update."""
        # Extract usage data
        result.tokens = TokenUsage(
            input=event.data.get("input_tokens", 0),
            output=event.data.get("output_tokens", 0),
            reasoning=event.data.get("reasoning_tokens", 0),
            cache_read=event.data.get("cache_read_tokens", 0),
            cache_write=event.data.get("cache_write_tokens", 0),
        )

        # Calculate cost
        cost_result = self._cost_tracker.calculate(
            usage={
                "input_tokens": result.tokens.input,
                "output_tokens": result.tokens.output,
                "reasoning_tokens": result.tokens.reasoning,
                "cache_read_tokens": result.tokens.cache_read,
                "cache_write_tokens": result.tokens.cache_write,
            },
            model_name=config.model,
        )
        result.cost = float(cost_result.cost)

        yield AgentCostUpdateEvent(
            cost=result.cost,
            tokens={
                "input": result.tokens.input,
                "output": result.tokens.output,
                "reasoning": result.tokens.reasoning,
            },
        )

        # Check for compaction need
        if self._cost_tracker.needs_compaction(result.tokens):
            yield AgentCompactNeededEvent()

    def _build_trace_url(self, context: InvocationContext) -> Optional[str]:
        """Build Langfuse trace URL if available."""
        if not context.langfuse_context:
            return None

        try:
            from src.configuration.config import get_settings

            settings = get_settings()
            if settings.langfuse_enabled and settings.langfuse_host:
                trace_id = context.langfuse_context.get("conversation_id", "")
                if trace_id:
                    return f"{settings.langfuse_host}/trace/{trace_id}"
        except Exception:
            pass

        return None


# ============================================================================
# Singleton Management
# ============================================================================

_invoker: Optional[LLMInvoker] = None


def get_llm_invoker() -> LLMInvoker:
    """
    Get singleton LLMInvoker instance.

    Returns:
        LLMInvoker instance

    Raises:
        RuntimeError if invoker not initialized
    """
    global _invoker
    if _invoker is None:
        raise RuntimeError(
            "LLMInvoker not initialized. Call set_llm_invoker() first "
            "or pass retry_policy and cost_tracker to create_llm_invoker()."
        )
    return _invoker


def set_llm_invoker(invoker: LLMInvoker) -> None:
    """Set singleton LLMInvoker instance."""
    global _invoker
    _invoker = invoker


def create_llm_invoker(
    retry_policy: RetryPolicyProtocol,
    cost_tracker: CostTrackerProtocol,
    debug_logging: bool = False,
) -> LLMInvoker:
    """
    Create and set singleton LLMInvoker.

    Args:
        retry_policy: Retry policy instance
        cost_tracker: Cost tracker instance
        debug_logging: Enable debug logging

    Returns:
        Created LLMInvoker instance
    """
    global _invoker
    _invoker = LLMInvoker(
        retry_policy=retry_policy,
        cost_tracker=cost_tracker,
        debug_logging=debug_logging,
    )
    return _invoker
