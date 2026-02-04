"""
Session Processor - Core ReAct agent processing loop.

Orchestrates the complete agent execution cycle:
1. Receives user message
2. Calls LLM for reasoning and action
3. Executes tool calls
4. Observes results
5. Continues until task complete or blocked

Integrates all core components:
- LLMStream for streaming LLM responses
- DoomLoopDetector for detecting repeated patterns
- RetryPolicy for intelligent error handling
- CostTracker for real-time cost calculation
- PermissionManager for tool permission control

Reference: OpenCode's SessionProcessor in processor.ts (406 lines)
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Dict, List, Optional

from src.domain.events.agent_events import (
    AgentActEvent,
    AgentArtifactCreatedEvent,
    AgentClarificationAnsweredEvent,
    AgentClarificationAskedEvent,
    AgentCompactNeededEvent,
    AgentCompleteEvent,
    AgentCostUpdateEvent,
    AgentDecisionAnsweredEvent,
    AgentDecisionAskedEvent,
    AgentDomainEvent,
    AgentDoomLoopDetectedEvent,
    AgentEnvVarProvidedEvent,
    AgentEnvVarRequestedEvent,
    AgentErrorEvent,
    AgentEventType,
    AgentObserveEvent,
    AgentPermissionAskedEvent,
    AgentRetryEvent,
    AgentStartEvent,
    AgentStatusEvent,
    AgentStepEndEvent,
    AgentStepFinishEvent,
    AgentStepStartEvent,
    AgentTextDeltaEvent,
    AgentTextEndEvent,
    AgentTextStartEvent,
    AgentThoughtDeltaEvent,
    AgentThoughtEvent,
    AgentWorkPlanEvent,
)
from src.infrastructure.adapters.secondary.sandbox.artifact_integration import (
    extract_artifacts_from_mcp_result,
)

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService

# Import HITLPendingException from domain layer
from src.domain.model.agent.hitl_types import HITLPendingException

from ..core.llm_stream import LLMStream, StreamConfig, StreamEventType
from ..core.message import Message, MessageRole, ToolPart, ToolState
from ..cost import CostTracker, TokenUsage
from ..doom_loop import DoomLoopDetector
from ..hitl.temporal_hitl_handler import TemporalHITLHandler
from ..permission import PermissionAction, PermissionManager
from ..retry import RetryPolicy
from .message_utils import classify_tool_by_description, extract_user_query

logger = logging.getLogger(__name__)


class ProcessorState(str, Enum):
    """Session processor state."""

    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    WAITING_PERMISSION = "waiting_permission"
    WAITING_CLARIFICATION = "waiting_clarification"  # Waiting for user clarification
    WAITING_DECISION = "waiting_decision"  # Waiting for user decision
    WAITING_ENV_VAR = "waiting_env_var"  # Waiting for user to provide env vars
    RETRYING = "retrying"
    COMPLETED = "completed"
    ERROR = "error"


class ProcessorResult(str, Enum):
    """Result of processor execution."""

    CONTINUE = "continue"  # Continue processing (tool calls pending)
    STOP = "stop"  # Stop processing (blocked or error)
    COMPACT = "compact"  # Need context compaction
    COMPLETE = "complete"  # Task completed successfully


@dataclass
class ProcessorConfig:
    """Configuration for session processor."""

    # Model configuration
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 4096

    # Processing limits
    max_steps: int = 50  # Maximum steps before forcing stop
    max_tool_calls_per_step: int = 10  # Max tool calls per LLM response
    doom_loop_threshold: int = 3  # Consecutive identical calls to trigger

    # Retry configuration
    max_attempts: int = 5
    initial_delay_ms: int = 2000

    # Permission configuration
    permission_timeout: float = 300.0  # seconds
    continue_on_deny: bool = False  # Continue loop if permission denied

    # Cost tracking
    context_limit: int = 200000  # Token limit before compaction warning

    # LLM Client (optional, provides circuit breaker + rate limiter)
    llm_client: Optional[Any] = None


@dataclass
class ToolDefinition:
    """Tool definition for LLM."""

    name: str
    description: str
    parameters: Dict[str, Any]
    execute: Callable[..., Any]  # Async callable
    permission: Optional[str] = None  # Permission required

    def to_openai_format(self) -> Dict[str, Any]:
        """Convert to OpenAI tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class SessionProcessor:
    """
    Core ReAct agent processing loop.

    Manages the complete agent execution cycle with:
    - Streaming LLM responses
    - Tool execution with permission control
    - Doom loop detection
    - Intelligent retry with backoff
    - Real-time cost tracking
    - SSE event emission
    - Artifact extraction from tool outputs

    Usage:
        processor = SessionProcessor(config, tools)
        async for event in processor.process(session_id, messages):
            yield event.to_sse_format()
    """

    def __init__(
        self,
        config: ProcessorConfig,
        tools: List[ToolDefinition],
        permission_manager: Optional[PermissionManager] = None,
        artifact_service: Optional["ArtifactService"] = None,
    ):
        """
        Initialize session processor.

        Args:
            config: Processor configuration
            tools: List of available tools
            permission_manager: Optional permission manager (creates default if None)
            artifact_service: Optional artifact service for handling rich outputs
        """
        self.config = config
        self.tools = {t.name: t for t in tools}

        # Initialize components
        self.permission_manager = permission_manager or PermissionManager()
        self.doom_loop_detector = DoomLoopDetector(threshold=config.doom_loop_threshold)
        self.retry_policy = RetryPolicy(
            max_attempts=config.max_attempts,
            initial_delay_ms=config.initial_delay_ms,
        )
        self.cost_tracker = CostTracker()

        # Artifact service for rich output handling
        self._artifact_service = artifact_service

        # LLM client for streaming (with circuit breaker + rate limiter)
        self._llm_client = config.llm_client

        # Session state
        self._state = ProcessorState.IDLE
        self._step_count = 0
        self._current_message: Optional[Message] = None
        self._pending_tool_calls: Dict[str, ToolPart] = {}
        self._abort_event: Optional[asyncio.Event] = None

        # Work plan tracking
        self._work_plan_id: Optional[str] = None
        self._work_plan_steps: List[Dict[str, Any]] = []
        self._current_plan_step: int = 0
        self._tool_to_step_mapping: Dict[str, int] = {}  # tool_name -> step_number

        # Langfuse observability context
        self._langfuse_context: Optional[Dict[str, Any]] = None

        # HITL handler (created lazily when context is available)
        self._hitl_handler: Optional[TemporalHITLHandler] = None

    @property
    def state(self) -> ProcessorState:
        """Get current processor state."""
        return self._state

    def _get_hitl_handler(self) -> TemporalHITLHandler:
        """Get or create the HITL handler for current context."""
        ctx = self._langfuse_context or {}
        conversation_id = ctx.get("conversation_id", "unknown")
        tenant_id = ctx.get("tenant_id", "unknown")
        project_id = ctx.get("project_id", "unknown")
        message_id = ctx.get("message_id")

        # Create new handler if needed or context changed
        if self._hitl_handler is None or self._hitl_handler.conversation_id != conversation_id:
            self._hitl_handler = TemporalHITLHandler(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                project_id=project_id,
                message_id=message_id,
            )

        return self._hitl_handler

    async def process(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        abort_signal: Optional[asyncio.Event] = None,
        langfuse_context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Process a conversation turn.

        Runs the ReAct loop:
        1. Call LLM with messages
        2. Process response (text, reasoning, tool calls)
        3. Execute tool calls if any
        4. Continue until complete or blocked

        Args:
            session_id: Session identifier
            messages: Conversation messages in OpenAI format
            abort_signal: Optional abort signal
            langfuse_context: Optional context for Langfuse tracing containing:
                - conversation_id: Unique conversation identifier
                - user_id: User identifier
                - tenant_id: Tenant identifier for multi-tenant isolation
                - project_id: Project identifier
                - extra: Additional metadata dict

        Yields:
            AgentDomainEvent objects for real-time streaming
        """
        self._abort_event = abort_signal or asyncio.Event()
        self._step_count = 0
        self._langfuse_context = langfuse_context  # Store for use in _process_step

        # Reset work plan tracking
        self._work_plan_id = str(uuid.uuid4())
        self._work_plan_steps = []
        self._current_plan_step = 0
        self._tool_to_step_mapping = {}

        # Emit start event
        yield AgentStartEvent()
        self._state = ProcessorState.THINKING

        # Generate and emit work plan based on available tools and user query
        user_query = self._extract_user_query(messages)
        if user_query and self.tools:
            work_plan_data = await self._generate_work_plan(user_query, messages)
            if work_plan_data:
                yield AgentWorkPlanEvent(plan=work_plan_data)

        try:
            result = ProcessorResult.CONTINUE

            while result == ProcessorResult.CONTINUE:
                # Check abort
                if self._abort_event.is_set():
                    yield AgentErrorEvent(message="Processing aborted", code="ABORTED")
                    self._state = ProcessorState.ERROR
                    return

                # Check step limit
                self._step_count += 1
                if self._step_count > self.config.max_steps:
                    yield AgentErrorEvent(
                        message=f"Maximum steps ({self.config.max_steps}) exceeded",
                        code="MAX_STEPS_EXCEEDED",
                    )
                    self._state = ProcessorState.ERROR
                    return

                # Process one step
                async for event in self._process_step(session_id, messages):
                    yield event

                    # Check for stop conditions in events
                    if event.event_type == AgentEventType.ERROR:
                        result = ProcessorResult.STOP
                        break
                    elif event.event_type == AgentEventType.STEP_FINISH:
                        # Check finish reason
                        finish_reason = event.finish_reason
                        if finish_reason == "stop":
                            result = ProcessorResult.COMPLETE
                        elif finish_reason == "tool_calls":
                            result = ProcessorResult.CONTINUE
                        else:
                            result = ProcessorResult.COMPLETE
                    elif event.event_type == AgentEventType.COMPACT_NEEDED:
                        result = ProcessorResult.COMPACT
                        break

                # If we have pending tool results, add them to messages
                if result == ProcessorResult.CONTINUE and self._current_message:
                    # Add assistant message with tool calls
                    messages.append(self._current_message.to_llm_format())

                    # Add tool results
                    for part in self._current_message.get_tool_parts():
                        if part.status == ToolState.COMPLETED:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": part.call_id,
                                    "content": part.output or "",
                                }
                            )
                        elif part.status == ToolState.ERROR:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": part.call_id,
                                    "content": f"Error: {part.error}",
                                }
                            )

            # Emit completion
            if result == ProcessorResult.COMPLETE:
                # Build trace URL if Langfuse context is available
                trace_url = None
                if self._langfuse_context:
                    from src.configuration.config import get_settings

                    settings = get_settings()
                    if settings.langfuse_enabled and settings.langfuse_host:
                        trace_id = self._langfuse_context.get("conversation_id", session_id)
                        trace_url = f"{settings.langfuse_host}/trace/{trace_id}"
                yield AgentCompleteEvent(trace_url=trace_url)
                self._state = ProcessorState.COMPLETED
            elif result == ProcessorResult.COMPACT:
                yield AgentStatusEvent(status="compact_needed")

        except HITLPendingException:
            # Let HITLPendingException bubble up to Activity layer
            # The Workflow will wait for user response and resume execution
            raise

        except Exception as e:
            logger.error(f"Processor error: {e}", exc_info=True)
            yield AgentErrorEvent(message=str(e), code=type(e).__name__)
            self._state = ProcessorState.ERROR

    def _extract_user_query(self, messages: List[Dict[str, Any]]) -> Optional[str]:
        """Extract the latest user query from messages."""
        return extract_user_query(messages)

    def _classify_tool_by_description(self, tool_name: str, tool_def: ToolDefinition) -> str:
        """Classify tool into a category based on its description."""
        return classify_tool_by_description(tool_name, tool_def.description)

    async def _generate_work_plan(
        self,
        user_query: str,
        messages: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a work plan based on user query and available tools.

        This creates a simple work plan that shows the expected execution flow
        to the user, improving transparency of the ReAct agent's process.

        Uses semantic classification of tools based on their descriptions,
        supporting dynamic tool addition via MCP or Skills.

        Args:
            user_query: The user's query
            messages: Full conversation context

        Returns:
            Work plan data dictionary for SSE event, or None if no plan needed
        """
        if not self.tools:
            return None

        # Classify all available tools by their semantic purpose
        tool_categories = {}
        for tool_name, tool_def in self.tools.items():
            category = self._classify_tool_by_description(tool_name, tool_def)
            if category not in tool_categories:
                tool_categories[category] = []
            tool_categories[category].append(tool_name)

        # Create a simple plan based on common tool patterns
        steps = []
        step_number = 0

        # Analyze query to predict likely tool usage
        query_lower = user_query.lower()

        # Pattern matching for common workflows
        needs_search = any(kw in query_lower for kw in ["搜索", "search", "查找", "find", "查询"])
        needs_scrape = any(
            kw in query_lower for kw in ["抓取", "scrape", "获取网页", "网站", "url", "http"]
        )
        needs_summary = any(
            kw in query_lower for kw in ["总结", "summarize", "summary", "概括", "归纳"]
        )
        needs_memory = any(kw in query_lower for kw in ["记忆", "memory", "记录", "知识"])
        needs_graph = any(kw in query_lower for kw in ["图谱", "graph", "实体", "entity", "关系"])
        needs_code = any(kw in query_lower for kw in ["代码", "code", "执行", "run", "python"])

        # Build steps based on detected needs and categorized tools
        if needs_search and "search" in tool_categories:
            search_tools = tool_categories["search"]
            steps.append(
                {
                    "step_number": step_number,
                    "description": "搜索相关信息",
                    "required_tools": search_tools,
                    "status": "pending",
                }
            )
            # Map all search tools to this step
            for tool_name in search_tools:
                self._tool_to_step_mapping[tool_name] = step_number
            step_number += 1

        if needs_scrape and "scrape" in tool_categories:
            scrape_tools = tool_categories["scrape"]
            steps.append(
                {
                    "step_number": step_number,
                    "description": "获取网页内容",
                    "required_tools": scrape_tools,
                    "status": "pending",
                }
            )
            # Map all scrape tools to this step
            for tool_name in scrape_tools:
                self._tool_to_step_mapping[tool_name] = step_number
            step_number += 1

        if needs_memory and "memory" in tool_categories:
            memory_tools = tool_categories["memory"]
            steps.append(
                {
                    "step_number": step_number,
                    "description": "搜索记忆库",
                    "required_tools": memory_tools,
                    "status": "pending",
                }
            )
            # Map all memory tools to this step
            for tool_name in memory_tools:
                self._tool_to_step_mapping[tool_name] = step_number
            step_number += 1

        if needs_graph:
            if "entity" in tool_categories:
                entity_tools = tool_categories["entity"]
                steps.append(
                    {
                        "step_number": step_number,
                        "description": "查询知识图谱实体",
                        "required_tools": entity_tools,
                        "status": "pending",
                    }
                )
                # Map all entity lookup tools to this step
                for tool_name in entity_tools:
                    self._tool_to_step_mapping[tool_name] = step_number
                step_number += 1

            if "graph" in tool_categories:
                graph_tools = tool_categories["graph"]
                steps.append(
                    {
                        "step_number": step_number,
                        "description": "执行图谱查询",
                        "required_tools": graph_tools,
                        "status": "pending",
                    }
                )
                # Map all graph query tools to this step
                for tool_name in graph_tools:
                    self._tool_to_step_mapping[tool_name] = step_number
                step_number += 1

        if needs_code and "code" in tool_categories:
            code_tools = tool_categories["code"]
            steps.append(
                {
                    "step_number": step_number,
                    "description": "执行代码",
                    "required_tools": code_tools,
                    "status": "pending",
                }
            )
            # Map all code execution tools to this step
            for tool_name in code_tools:
                self._tool_to_step_mapping[tool_name] = step_number
            step_number += 1

        if needs_summary and "summary" in tool_categories:
            summary_tools = tool_categories["summary"]
            steps.append(
                {
                    "step_number": step_number,
                    "description": "总结分析结果",
                    "required_tools": summary_tools,
                    "status": "pending",
                }
            )
            # Map all summary tools to this step
            for tool_name in summary_tools:
                self._tool_to_step_mapping[tool_name] = step_number
            step_number += 1

        # Always add a final synthesis step
        steps.append(
            {
                "step_number": step_number,
                "description": "生成最终回复",
                "required_tools": [],
                "status": "pending",
            }
        )

        # If no specific tools detected (only final step), don't generate a work plan
        # Simple conversations don't need execution plans - this makes the UI cleaner
        if len(steps) == 1:  # Only final step (no tool usage expected)
            self._work_plan_steps = []
            return None  # Don't show execution plan for simple conversations

        self._work_plan_steps = steps

        return {
            "plan_id": self._work_plan_id,
            "conversation_id": "",  # Will be set by caller
            "status": "in_progress",
            "steps": steps,
            "current_step": 0,
            "total_steps": len(steps),
        }

    async def _process_step(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Process a single step in the ReAct loop.

        Args:
            session_id: Session identifier
            messages: Current messages

        Yields:
            AgentDomainEvent objects
        """
        # DEBUG: Force logging at start of _process_step
        print(
            f"[Processor] _process_step called: session={session_id}, step={self._step_count}",
            flush=True,
        )
        logger.warning(
            f"[Processor] _process_step called: session={session_id}, step={self._step_count}"
        )

        # Get step description from work plan if available
        step_description = f"Step {self._step_count}"
        if self._work_plan_steps and self._current_plan_step < len(self._work_plan_steps):
            step_info = self._work_plan_steps[self._current_plan_step]
            step_description = step_info.get("description", step_description)

        # Emit step start with meaningful description
        yield AgentStepStartEvent(step_index=self._step_count, description=step_description)
        logger.warning(f"[Processor] After yield step_start, step={self._step_count}")

        # Create new assistant message
        self._current_message = Message(
            session_id=session_id,
            role=MessageRole.ASSISTANT,
        )
        logger.warning(f"[Processor] Created assistant message, step={self._step_count}")

        # Reset pending tool calls
        self._pending_tool_calls = {}

        # Prepare tools for LLM
        tools_for_llm = [t.to_openai_format() for t in self.tools.values()]
        logger.warning(
            f"[Processor] Prepared {len(tools_for_llm)} tools for LLM, step={self._step_count}"
        )

        # Create stream config
        stream_config = StreamConfig(
            model=self.config.model,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            tools=tools_for_llm if tools_for_llm else None,
        )
        logger.warning(
            f"[Processor] Created StreamConfig, model={self.config.model}, step={self._step_count}"
        )

        # Create LLM stream with optional client (provides circuit breaker + rate limiter)
        llm_stream = LLMStream(stream_config, llm_client=self._llm_client)
        logger.warning(f"[Processor] Created LLMStream, step={self._step_count}")

        # Track state for this step
        text_buffer = ""
        reasoning_buffer = ""
        tool_calls_completed = []
        step_tokens = TokenUsage()
        step_cost = 0.0
        finish_reason = "stop"

        # Process LLM stream with retry
        attempt = 0
        logger.warning(f"[Processor] Starting LLM stream retry loop, step={self._step_count}")
        while True:
            try:
                # Build step-specific langfuse context
                step_langfuse_context = None
                if self._langfuse_context:
                    step_langfuse_context = {
                        **self._langfuse_context,
                        "extra": {
                            **self._langfuse_context.get("extra", {}),
                            "step_number": self._step_count,
                            "model": self.config.model,
                        },
                    }

                logger.warning(
                    f"[Processor] About to call llm_stream.generate(), step={self._step_count}"
                )
                async for event in llm_stream.generate(
                    messages, langfuse_context=step_langfuse_context
                ):
                    # Check abort
                    if self._abort_event and self._abort_event.is_set():
                        raise asyncio.CancelledError("Aborted")

                    # Debug: log all events from LLM stream
                    logger.info(
                        f"[Processor] LLM event: type={event.type}, data_keys={list(event.data.keys()) if event.data else []}"
                    )

                    # Process stream events
                    if event.type == StreamEventType.TEXT_START:
                        logger.info("[Processor] Yielding TEXT_START")
                        yield AgentTextStartEvent()

                    elif event.type == StreamEventType.TEXT_DELTA:
                        delta = event.data.get("delta", "")
                        text_buffer += delta
                        logger.info(
                            f"[Processor] Yielding TEXT_DELTA: {delta[:30]}..."
                            if len(delta) > 30
                            else f"[Processor] Yielding TEXT_DELTA: {delta}"
                        )
                        yield AgentTextDeltaEvent(delta=delta)

                    elif event.type == StreamEventType.TEXT_END:
                        full_text = event.data.get("full_text", text_buffer)
                        logger.info(
                            f"[Processor] Yielding TEXT_END: full_text_len={len(full_text) if full_text else 0}, "
                            f"preview={full_text[:50] if full_text else '(empty)'}..."
                        )
                        self._current_message.add_text(full_text)
                        yield AgentTextEndEvent(full_text=full_text)

                    elif event.type == StreamEventType.REASONING_START:
                        yield AgentThoughtEvent(content="", thought_level="reasoning")

                    elif event.type == StreamEventType.REASONING_DELTA:
                        delta = event.data.get("delta", "")
                        reasoning_buffer += delta
                        yield AgentThoughtDeltaEvent(delta=delta)

                    elif event.type == StreamEventType.REASONING_END:
                        full_reasoning = event.data.get("full_text", reasoning_buffer)
                        self._current_message.add_reasoning(full_reasoning)
                        yield AgentThoughtEvent(content=full_reasoning, thought_level="reasoning")

                    elif event.type == StreamEventType.TOOL_CALL_START:
                        call_id = event.data.get("call_id", "")
                        tool_name = event.data.get("name", "")

                        # Create tool part (don't emit act event yet - wait for complete args)
                        tool_part = self._current_message.add_tool_call(
                            call_id=call_id,
                            tool=tool_name,
                            input={},
                        )
                        self._pending_tool_calls[call_id] = tool_part
                        # Note: Don't emit act event here - wait for TOOL_CALL_END with full args

                    elif event.type == StreamEventType.TOOL_CALL_END:
                        call_id = event.data.get("call_id", "")
                        tool_name = event.data.get("name", "")
                        arguments = event.data.get("arguments", {})

                        # === EARLY VALIDATION (P0-1) ===
                        # Validate AgentActEvent schema BEFORE yielding to prevent
                        # 3-minute delay on validation errors. Fast-fail here instead.
                        try:
                            # Validate that tool_name is a non-empty string
                            if not isinstance(tool_name, str) or not tool_name.strip():
                                raise ValueError(f"Invalid tool_name: {tool_name!r}")

                            # Validate that arguments is a dict (Pydantic requirement)
                            if not isinstance(arguments, dict):
                                raise ValueError(
                                    f"Invalid tool_input type: {type(arguments).__name__}, "
                                    f"expected dict"
                                )

                            # Validate call_id is a non-empty string if provided
                            if call_id and not isinstance(call_id, str):
                                raise ValueError(f"Invalid call_id type: {type(call_id).__name__}")

                            # Try to create AgentActEvent to catch any other validation errors
                            # This validates the entire schema before we proceed
                            _test_event = AgentActEvent(
                                tool_name=tool_name,
                                tool_input=arguments,
                                call_id=call_id,
                                status="running",
                            )
                            # Event validated successfully, don't use _test_event
                            del _test_event

                        except (ValueError, TypeError) as ve:
                            # Early validation failed - log and emit error immediately
                            logger.error(
                                f"[Processor] Early validation failed for tool call: "
                                f"tool_name={tool_name!r}, arguments={arguments!r}, "
                                f"error={ve}"
                            )
                            # Emit error event and continue with next tool call
                            yield AgentErrorEvent(
                                message=f"Tool call validation failed: {ve}",
                                code="VALIDATION_ERROR",
                            )
                            continue

                        # Update tool part
                        if call_id in self._pending_tool_calls:
                            tool_part = self._pending_tool_calls[call_id]
                            tool_part.input = arguments
                            tool_part.status = ToolState.RUNNING
                            tool_part.start_time = time.time()
                            # Generate unique execution_id for act/observe matching
                            tool_part.tool_execution_id = f"exec_{uuid.uuid4().hex[:12]}"

                            # Get step number from tool-to-step mapping
                            step_number = self._tool_to_step_mapping.get(tool_name)

                            # Update work plan step status
                            if step_number is not None and step_number < len(self._work_plan_steps):
                                self._work_plan_steps[step_number]["status"] = "running"
                                self._current_plan_step = step_number

                            yield AgentActEvent(
                                tool_name=tool_name,
                                tool_input=arguments,
                                call_id=call_id,
                                status="running",
                                tool_execution_id=tool_part.tool_execution_id,
                            )
                            # Add step_number to the event data for frontend
                            if step_number is not None:
                                # Re-emit with step_number in data
                                yield AgentStepStartEvent(
                                    step_index=step_number,
                                    description=self._work_plan_steps[step_number].get(
                                        "description", ""
                                    ),
                                )

                            # Execute tool
                            async for tool_event in self._execute_tool(
                                session_id, call_id, tool_name, arguments
                            ):
                                yield tool_event

                            tool_calls_completed.append(call_id)

                    elif event.type == StreamEventType.USAGE:
                        # Extract usage data
                        step_tokens = TokenUsage(
                            input=event.data.get("input_tokens", 0),
                            output=event.data.get("output_tokens", 0),
                            reasoning=event.data.get("reasoning_tokens", 0),
                            cache_read=event.data.get("cache_read_tokens", 0),
                            cache_write=event.data.get("cache_write_tokens", 0),
                        )

                        # Calculate cost
                        cost_result = self.cost_tracker.calculate(
                            usage={
                                "input_tokens": step_tokens.input,
                                "output_tokens": step_tokens.output,
                                "reasoning_tokens": step_tokens.reasoning,
                                "cache_read_tokens": step_tokens.cache_read,
                                "cache_write_tokens": step_tokens.cache_write,
                            },
                            model_name=self.config.model,
                        )
                        step_cost = float(cost_result.cost)

                        yield AgentCostUpdateEvent(
                            cost=step_cost,
                            tokens={
                                "input": step_tokens.input,
                                "output": step_tokens.output,
                                "reasoning": step_tokens.reasoning,
                            },
                        )

                        # Check for compaction need
                        if self.cost_tracker.needs_compaction(step_tokens):
                            yield AgentCompactNeededEvent()

                    elif event.type == StreamEventType.FINISH:
                        finish_reason = event.data.get("reason", "stop")

                    elif event.type == StreamEventType.ERROR:
                        error_msg = event.data.get("message", "Unknown error")
                        raise Exception(error_msg)

                # Step completed successfully
                break

            except Exception as e:
                # Check if retryable
                if self.retry_policy.is_retryable(e) and attempt < self.config.max_attempts:
                    attempt += 1
                    delay_ms = self.retry_policy.calculate_delay(attempt, e)

                    self._state = ProcessorState.RETRYING
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
                    raise

        # Update message tokens and cost
        self._current_message.tokens = {
            "input": step_tokens.input,
            "output": step_tokens.output,
            "reasoning": step_tokens.reasoning,
        }
        self._current_message.cost = step_cost
        self._current_message.finish_reason = finish_reason
        self._current_message.completed_at = time.time()

        # Build trace URL if Langfuse context is available
        trace_url = None
        if self._langfuse_context:
            from src.configuration.config import get_settings

            settings = get_settings()
            if settings.langfuse_enabled and settings.langfuse_host:
                trace_id = self._langfuse_context.get("conversation_id", session_id)
                trace_url = f"{settings.langfuse_host}/trace/{trace_id}"

        # Emit step finish
        yield AgentStepFinishEvent(
            tokens=self._current_message.tokens,
            cost=step_cost,
            finish_reason=finish_reason,
            trace_url=trace_url,
        )

        # Emit step end
        yield AgentStepEndEvent(step_index=self._step_count, status="completed")

    async def _execute_tool(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Execute a tool call with permission checking and doom loop detection.

        Args:
            session_id: Session identifier
            call_id: Tool call ID
            tool_name: Name of tool to execute
            arguments: Tool arguments

        Yields:
            AgentDomainEvent objects for tool execution
        """
        tool_part = self._pending_tool_calls.get(call_id)
        if not tool_part:
            logger.error(
                f"[Processor] Tool call not found in pending: call_id={call_id}, tool={tool_name}"
            )
            yield AgentObserveEvent(
                tool_name=tool_name,
                error=f"Tool call not found: {call_id}",
                call_id=call_id,
                tool_execution_id=None,
            )
            return

        # Get tool definition
        tool_def = self.tools.get(tool_name)
        if not tool_def:
            tool_part.status = ToolState.ERROR
            tool_part.error = f"Unknown tool: {tool_name}"
            tool_part.end_time = time.time()

            yield AgentObserveEvent(
                tool_name=tool_name,
                error=f"Unknown tool: {tool_name}",
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )
            return

        # Check doom loop
        if self.doom_loop_detector.should_intervene(tool_name, arguments):
            # Emit doom loop detected
            yield AgentDoomLoopDetectedEvent(tool=tool_name, input=arguments)

            # Ask for permission to continue
            self._state = ProcessorState.WAITING_PERMISSION

            try:
                permission_result = await asyncio.wait_for(
                    self.permission_manager.ask(
                        permission="doom_loop",
                        patterns=[tool_name],
                        session_id=session_id,
                        metadata={
                            "tool": tool_name,
                            "input": arguments,
                        },
                    ),
                    timeout=self.config.permission_timeout,
                )

                if permission_result == "reject":
                    tool_part.status = ToolState.ERROR
                    tool_part.error = "Doom loop detected and rejected by user"
                    tool_part.end_time = time.time()

                    yield AgentObserveEvent(
                        tool_name=tool_name,
                        error="Doom loop detected and rejected",
                        call_id=call_id,
                        tool_execution_id=tool_part.tool_execution_id,
                    )
                    return

            except asyncio.TimeoutError:
                tool_part.status = ToolState.ERROR
                tool_part.error = "Permission request timed out"
                tool_part.end_time = time.time()

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    error="Permission request timed out",
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )
                return

        # Record tool call for doom loop detection
        self.doom_loop_detector.record(tool_name, arguments)

        # === Human-in-the-Loop Tool Handling ===
        # Handle clarification and decision tools specially to enable
        # SSE event emission before blocking on user response

        if tool_name == "ask_clarification":
            async for event in self._handle_clarification_tool(
                session_id, call_id, tool_name, arguments, tool_part
            ):
                yield event
            return

        if tool_name == "request_decision":
            async for event in self._handle_decision_tool(
                session_id, call_id, tool_name, arguments, tool_part
            ):
                yield event
            return

        if tool_name == "request_env_var":
            async for event in self._handle_env_var_tool(
                session_id, call_id, tool_name, arguments, tool_part
            ):
                yield event
            return

        # Check tool permission
        if tool_def.permission:
            permission_rule = self.permission_manager.evaluate(
                permission=tool_def.permission,
                pattern=tool_name,
            )

            if permission_rule.action == PermissionAction.DENY:
                tool_part.status = ToolState.ERROR
                tool_part.error = f"Permission denied: {tool_def.permission}"
                tool_part.end_time = time.time()

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    error=f"Permission denied: {tool_def.permission}",
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )
                return

            elif permission_rule.action == PermissionAction.ASK:
                # Request permission
                self._state = ProcessorState.WAITING_PERMISSION

                yield AgentPermissionAskedEvent(
                    request_id=f"perm_{uuid.uuid4().hex[:8]}",
                    permission=tool_def.permission,
                    patterns=[tool_name],
                    metadata={"tool": tool_name, "input": arguments},
                )

                try:
                    permission_result = await asyncio.wait_for(
                        self.permission_manager.ask(
                            permission=tool_def.permission,
                            patterns=[tool_name],
                            session_id=session_id,
                            metadata={"tool": tool_name, "input": arguments},
                        ),
                        timeout=self.config.permission_timeout,
                    )

                    if permission_result == "reject":
                        tool_part.status = ToolState.ERROR
                        tool_part.error = "Permission rejected by user"
                        tool_part.end_time = time.time()

                        yield AgentObserveEvent(
                            tool_name=tool_name,
                            error="Permission rejected by user",
                            call_id=call_id,
                            tool_execution_id=tool_part.tool_execution_id,
                        )
                        return

                except asyncio.TimeoutError:
                    tool_part.status = ToolState.ERROR
                    tool_part.error = "Permission request timed out"
                    tool_part.end_time = time.time()

                    yield AgentObserveEvent(
                        tool_name=tool_name,
                        error="Permission request timed out",
                        call_id=call_id,
                        tool_execution_id=tool_part.tool_execution_id,
                    )
                    return

        # Execute tool
        self._state = ProcessorState.ACTING

        try:
            # Handle truncated arguments (from llm_stream detecting incomplete JSON)
            if "_error" in arguments and arguments.get("_error") == "truncated":
                error_msg = arguments.get(
                    "_message", "Tool arguments were truncated. The content may be too large."
                )
                logger.error(f"[Processor] Tool arguments truncated for {tool_name}")
                tool_part.status = ToolState.ERROR
                tool_part.error = error_msg
                tool_part.end_time = time.time()

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    error=error_msg,
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )
                return

            # Handle _raw arguments (from failed JSON parsing in llm_stream)
            # This happens when LLM returns malformed JSON for tool arguments
            if "_raw" in arguments and len(arguments) == 1:
                raw_args = arguments["_raw"]
                logger.warning(
                    f"[Processor] Attempting to parse _raw arguments for tool {tool_name}: "
                    f"{raw_args[:200] if len(raw_args) > 200 else raw_args}..."
                )

                # Define helper to escape control characters
                def escape_control_chars(s):
                    """Escape control characters in a JSON string."""
                    s = s.replace("\n", "\\n")
                    s = s.replace("\r", "\\r")
                    s = s.replace("\t", "\\t")
                    return s

                parse_success = False

                # Try 1: Direct parse
                try:
                    arguments = json.loads(raw_args)
                    logger.info(f"[Processor] Successfully parsed _raw arguments for {tool_name}")
                    parse_success = True
                except json.JSONDecodeError:
                    pass

                # Try 2: Escape control characters and parse
                if not parse_success:
                    try:
                        fixed_args = escape_control_chars(raw_args)
                        arguments = json.loads(fixed_args)
                        logger.info(
                            f"[Processor] Successfully parsed _raw arguments after escaping control chars for {tool_name}"
                        )
                        parse_success = True
                    except json.JSONDecodeError:
                        pass

                # Try 3: Handle double-encoded JSON
                if not parse_success:
                    try:
                        if raw_args.startswith('"') and raw_args.endswith('"'):
                            inner = raw_args[1:-1]
                            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
                            arguments = json.loads(inner)
                            logger.info(
                                f"[Processor] Successfully parsed double-encoded _raw arguments for {tool_name}"
                            )
                            parse_success = True
                    except json.JSONDecodeError:
                        pass

                # All attempts failed
                if not parse_success:
                    error_msg = (
                        f"Invalid JSON in tool arguments. "
                        f"Raw arguments preview: {raw_args[:500] if len(raw_args) > 500 else raw_args}"
                    )
                    logger.error(f"[Processor] Failed to parse _raw arguments for {tool_name}")
                    tool_part.status = ToolState.ERROR
                    tool_part.error = error_msg
                    tool_part.end_time = time.time()

                    yield AgentObserveEvent(
                        tool_name=tool_name,
                        error=error_msg,
                        call_id=call_id,
                        tool_execution_id=tool_part.tool_execution_id,
                    )
                    return

            # Call tool execute function
            start_time = time.time()
            result = await tool_def.execute(**arguments)
            end_time = time.time()

            # Handle structured return format {title, output, metadata}
            # Reference: OpenCode SkillTool structured return
            if isinstance(result, dict) and "output" in result:
                # Extract output for tool_part (used for LLM context)
                output_str = result.get("output", "")
                # Keep full result for SSE event (frontend can use metadata)
                sse_result = result
            elif isinstance(result, str):
                output_str = result
                sse_result = result
            else:
                output_str = json.dumps(result)
                sse_result = result

            # Update tool part
            tool_part.status = ToolState.COMPLETED
            tool_part.output = output_str
            tool_part.end_time = end_time

            # Update work plan step status to completed
            step_number = self._tool_to_step_mapping.get(tool_name)
            if step_number is not None and step_number < len(self._work_plan_steps):
                self._work_plan_steps[step_number]["status"] = "completed"
                # Emit step_end event
                yield AgentStepEndEvent(step_index=step_number, status="completed")

            yield AgentObserveEvent(
                tool_name=tool_name,
                result=sse_result,
                duration_ms=int((end_time - start_time) * 1000),
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )

            # Extract and upload artifacts from tool result (images, files, etc.)
            async for artifact_event in self._process_tool_artifacts(
                tool_name=tool_name,
                result=result,
                tool_execution_id=tool_part.tool_execution_id,
            ):
                yield artifact_event

        except Exception as e:
            logger.error(f"Tool execution error: {e}", exc_info=True)

            tool_part.status = ToolState.ERROR
            tool_part.error = str(e)
            tool_part.end_time = time.time()

            # Update work plan step status to failed
            step_number = self._tool_to_step_mapping.get(tool_name)
            if step_number is not None and step_number < len(self._work_plan_steps):
                self._work_plan_steps[step_number]["status"] = "failed"
                # Emit step_end event with failed status
                yield AgentStepEndEvent(step_index=step_number, status="failed")

            yield AgentObserveEvent(
                tool_name=tool_name,
                error=str(e),
                duration_ms=int((time.time() - tool_part.start_time) * 1000)
                if tool_part.start_time
                else None,
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )

        self._state = ProcessorState.OBSERVING

    async def _process_tool_artifacts(
        self,
        tool_name: str,
        result: Any,
        tool_execution_id: Optional[str] = None,
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Process tool result and extract any artifacts (images, files, etc.).

        This method:
        1. Extracts image/resource content from MCP-style results
        2. Uploads artifacts to storage via ArtifactService
        3. Emits artifact_created events for frontend display

        Args:
            tool_name: Name of the tool that produced the result
            result: Tool execution result (may contain images/resources)
            tool_execution_id: ID of the tool execution

        Yields:
            AgentArtifactCreatedEvent for each artifact created
        """
        # Log entry for debugging
        logger.info(
            f"_process_tool_artifacts: ENTER tool_name={tool_name}, "
            f"has_artifact_service={self._artifact_service is not None}, "
            f"result_type={type(result).__name__}"
        )

        if not self._artifact_service:
            # No artifact service configured, skip processing
            logger.warning("_process_tool_artifacts: No artifact_service configured, skipping")
            return

        # Get context from langfuse context
        ctx = self._langfuse_context or {}
        project_id = ctx.get("project_id")
        tenant_id = ctx.get("tenant_id")
        conversation_id = ctx.get("conversation_id")

        if not project_id or not tenant_id:
            logger.warning(
                f"Missing project_id={project_id} or tenant_id={tenant_id} for artifact processing"
            )
            return

        # Check if result contains MCP-style content
        if not isinstance(result, dict):
            logger.info(
                f"_process_tool_artifacts: result is not dict, type={type(result)}, skipping"
            )
            return

        # Log for debugging
        logger.info(
            f"_process_tool_artifacts: tool_name={tool_name}, has_artifact={result.get('artifact') is not None}"
        )

        # Check for export_artifact tool result which has special 'artifact' field
        if result.get("artifact"):
            artifact_info = result["artifact"]
            try:
                import base64

                # Get file content
                encoding = artifact_info.get("encoding", "utf-8")
                if encoding == "base64":
                    # Binary file - get data from artifact info or image content
                    data = artifact_info.get("data")
                    if not data:
                        # Check for image content
                        for item in result.get("content", []):
                            if item.get("type") == "image":
                                data = item.get("data")
                                break
                    if data:
                        file_content = base64.b64decode(data)
                    else:
                        logger.warning("export_artifact has base64 encoding but no data")
                        return
                else:
                    # Text file - get from content
                    content = result.get("content", [])
                    if content:
                        first_item = content[0] if content else {}
                        text = (
                            first_item.get("text", "")
                            if isinstance(first_item, dict)
                            else str(first_item)
                        )
                        if not text:
                            logger.warning("export_artifact returned empty text content")
                            return
                        file_content = text.encode("utf-8")
                    else:
                        logger.warning("export_artifact returned no content")
                        return

                # Create artifact
                artifact = await self._artifact_service.create_artifact(
                    file_content=file_content,
                    filename=artifact_info.get("filename", "exported_file"),
                    project_id=project_id,
                    tenant_id=tenant_id,
                    sandbox_id=None,
                    tool_execution_id=tool_execution_id,
                    conversation_id=conversation_id,
                    source_tool=tool_name,
                    source_path=artifact_info.get("path"),
                    metadata={
                        "extracted_from": "export_artifact",
                        "original_mime": artifact_info.get("mime_type"),
                        "category": artifact_info.get("category"),
                        "is_binary": artifact_info.get("is_binary"),
                    },
                )

                logger.info(
                    f"Created artifact {artifact.id} from export_artifact: "
                    f"{artifact.filename} ({artifact.category.value}, {artifact.size_bytes} bytes)"
                )

                yield AgentArtifactCreatedEvent(
                    artifact_id=artifact.id,
                    filename=artifact.filename,
                    mime_type=artifact.mime_type,
                    category=artifact.category.value,
                    size_bytes=artifact.size_bytes,
                    url=artifact.url,
                    preview_url=artifact.preview_url,
                    tool_execution_id=tool_execution_id,
                    source_tool=tool_name,
                )
                return

            except Exception as e:
                import traceback

                logger.error(
                    f"Failed to process export_artifact result: {e}\n"
                    f"Artifact info: {artifact_info}\n"
                    f"Traceback: {traceback.format_exc()}"
                )

        # Check for MCP content array with images/resources
        content = result.get("content", [])
        if not content:
            return

        # Check if there are any image or resource types
        has_rich_content = any(
            item.get("type") in ("image", "resource") for item in content if isinstance(item, dict)
        )
        if not has_rich_content:
            return

        try:
            # Extract artifacts from MCP result
            artifact_data_list = extract_artifacts_from_mcp_result(result, tool_name)

            for artifact_data in artifact_data_list:
                try:
                    # Upload artifact
                    artifact = await self._artifact_service.create_artifact(
                        file_content=artifact_data["content"],
                        filename=artifact_data["filename"],
                        project_id=project_id,
                        tenant_id=tenant_id,
                        sandbox_id=None,  # TODO: Get sandbox_id if available
                        tool_execution_id=tool_execution_id,
                        conversation_id=conversation_id,
                        source_tool=tool_name,
                        source_path=artifact_data.get("source_path"),
                        metadata={
                            "extracted_from": "mcp_result",
                            "original_mime": artifact_data["mime_type"],
                        },
                    )

                    logger.info(
                        f"Created artifact {artifact.id} from tool {tool_name}: "
                        f"{artifact.filename} ({artifact.category.value}, {artifact.size_bytes} bytes)"
                    )

                    # Emit artifact created event
                    yield AgentArtifactCreatedEvent(
                        artifact_id=artifact.id,
                        filename=artifact.filename,
                        mime_type=artifact.mime_type,
                        category=artifact.category.value,
                        size_bytes=artifact.size_bytes,
                        url=artifact.url,
                        preview_url=artifact.preview_url,
                        tool_execution_id=tool_execution_id,
                        source_tool=tool_name,
                    )

                except Exception as e:
                    logger.error(f"Failed to create artifact from {tool_name}: {e}")

        except Exception as e:
            logger.error(f"Error processing artifacts from tool {tool_name}: {e}")

    async def _handle_clarification_tool(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_part: ToolPart,
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Handle clarification tool with SSE event emission via TemporalHITLHandler.

        Uses the unified Temporal-based HITL system for cross-process communication.

        Args:
            session_id: Session identifier
            call_id: Tool call ID
            tool_name: Tool name (ask_clarification)
            arguments: Tool arguments
            tool_part: Tool part for tracking state

        Yields:
            AgentDomainEvent objects for clarification flow
        """
        self._state = ProcessorState.WAITING_CLARIFICATION
        handler = self._get_hitl_handler()

        try:
            # Parse arguments
            question = arguments.get("question", "")
            clarification_type = arguments.get("clarification_type", "custom")
            options_raw = arguments.get("options", [])
            allow_custom = arguments.get("allow_custom", True)
            context_raw = arguments.get("context", {})
            timeout = arguments.get("timeout", 300.0)
            default_value = arguments.get("default_value")

            # Ensure context is a dictionary (LLM might pass a string)
            if isinstance(context_raw, str):
                context = {"description": context_raw} if context_raw else {}
            elif isinstance(context_raw, dict):
                context = context_raw.copy()
            else:
                context = {}

            # Convert options to standard format for SSE event
            clarification_options = []
            for opt in options_raw:
                clarification_options.append(
                    {
                        "id": opt.get("id", ""),
                        "label": opt.get("label", ""),
                        "description": opt.get("description"),
                        "recommended": opt.get("recommended", False),
                    }
                )

            # Generate request ID for tracking
            request_id = f"clar_{uuid.uuid4().hex[:8]}"

            # Emit clarification_asked event BEFORE blocking
            yield AgentClarificationAskedEvent(
                request_id=request_id,
                question=question,
                clarification_type=clarification_type,
                options=clarification_options,
                allow_custom=allow_custom,
                context=context,
            )

            # Use TemporalHITLHandler for request/response
            start_time = time.time()
            try:
                answer = await handler.request_clarification(
                    question=question,
                    options=clarification_options,
                    clarification_type=clarification_type,
                    allow_custom=allow_custom,
                    timeout_seconds=timeout,
                    context=context,
                    default_value=default_value,
                    request_id=request_id,  # Pass the same request_id
                )
                end_time = time.time()

                # Emit answered event
                yield AgentClarificationAnsweredEvent(
                    request_id=request_id,
                    answer=answer,
                )

                # Update tool part
                tool_part.status = ToolState.COMPLETED
                tool_part.output = answer
                tool_part.end_time = end_time

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    result=answer,
                    duration_ms=int((end_time - start_time) * 1000),
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )

            except asyncio.TimeoutError:
                tool_part.status = ToolState.ERROR
                tool_part.error = "Clarification request timed out"
                tool_part.end_time = time.time()

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    error="Clarification request timed out",
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )

        except HITLPendingException:
            # Let HITLPendingException bubble up to Activity layer
            # The Workflow will wait for user response and resume execution
            raise

        except Exception as e:
            logger.error(f"Clarification tool error: {e}", exc_info=True)
            tool_part.status = ToolState.ERROR
            tool_part.error = str(e)
            tool_part.end_time = time.time()

            yield AgentObserveEvent(
                tool_name=tool_name,
                error=str(e),
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )

        self._state = ProcessorState.OBSERVING

    async def _handle_decision_tool(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_part: ToolPart,
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Handle decision tool with SSE event emission via TemporalHITLHandler.

        Uses the unified Temporal-based HITL system for cross-process communication.

        Args:
            session_id: Session identifier
            call_id: Tool call ID
            tool_name: Tool name (request_decision)
            arguments: Tool arguments
            tool_part: Tool part for tracking state

        Yields:
            AgentDomainEvent objects for decision flow
        """
        self._state = ProcessorState.WAITING_DECISION
        handler = self._get_hitl_handler()

        try:
            # Parse arguments
            question = arguments.get("question", "")
            decision_type = arguments.get("decision_type", "custom")
            options_raw = arguments.get("options", [])
            allow_custom = arguments.get("allow_custom", False)
            default_option = arguments.get("default_option")
            context_raw = arguments.get("context", {})
            timeout = arguments.get("timeout", 300.0)

            # Ensure context is a dictionary (LLM might pass a string)
            if isinstance(context_raw, str):
                context = {"description": context_raw} if context_raw else {}
            elif isinstance(context_raw, dict):
                context = context_raw.copy()
            else:
                context = {}

            # Convert options to standard format for SSE event
            decision_options = []
            for opt in options_raw:
                decision_options.append(
                    {
                        "id": opt.get("id", ""),
                        "label": opt.get("label", ""),
                        "description": opt.get("description"),
                        "recommended": opt.get("recommended", False),
                        "estimated_time": opt.get("estimated_time"),
                        "estimated_cost": opt.get("estimated_cost"),
                        "risks": opt.get("risks", []),
                    }
                )

            # Generate request ID for tracking
            request_id = f"deci_{uuid.uuid4().hex[:8]}"

            # Emit decision_asked event BEFORE blocking
            yield AgentDecisionAskedEvent(
                request_id=request_id,
                question=question,
                decision_type=decision_type,
                options=decision_options,
                allow_custom=allow_custom,
                default_option=default_option,
                context=context,
            )

            # Use TemporalHITLHandler for request/response
            start_time = time.time()
            try:
                decision = await handler.request_decision(
                    question=question,
                    options=decision_options,
                    decision_type=decision_type,
                    allow_custom=allow_custom,
                    timeout_seconds=timeout,
                    context=context,
                    default_option=default_option,
                    request_id=request_id,  # Pass the same request_id
                )
                end_time = time.time()

                # Emit answered event
                yield AgentDecisionAnsweredEvent(
                    request_id=request_id,
                    decision=decision,
                )

                # Update tool part
                tool_part.status = ToolState.COMPLETED
                tool_part.output = decision
                tool_part.end_time = end_time

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    result=decision,
                    duration_ms=int((end_time - start_time) * 1000),
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )

            except asyncio.TimeoutError:
                tool_part.status = ToolState.ERROR
                tool_part.error = "Decision request timed out"
                tool_part.end_time = time.time()

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    error="Decision request timed out",
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )

        except HITLPendingException:
            # Let HITLPendingException bubble up to Activity layer
            # The Workflow will wait for user response and resume execution
            raise

        except Exception as e:
            logger.error(f"Decision tool error: {e}", exc_info=True)
            tool_part.status = ToolState.ERROR
            tool_part.error = str(e)
            tool_part.end_time = time.time()

            yield AgentObserveEvent(
                tool_name=tool_name,
                error=str(e),
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )

        self._state = ProcessorState.OBSERVING

    async def _handle_env_var_tool(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_part: ToolPart,
    ) -> AsyncIterator[AgentDomainEvent]:
        """
        Handle environment variable request tool with SSE event emission.

        Uses the unified Temporal-based HITL system. After receiving values,
        optionally saves them encrypted to the database.

        Args:
            session_id: Session identifier
            call_id: Tool call ID
            tool_name: Tool name (request_env_var)
            arguments: Tool arguments
            tool_part: Tool part for tracking state

        Yields:
            AgentDomainEvent objects for env var request flow
        """
        self._state = ProcessorState.WAITING_ENV_VAR
        handler = self._get_hitl_handler()

        try:
            # Parse arguments
            target_tool_name = arguments.get("tool_name", "")
            fields_raw = arguments.get("fields", [])
            message = arguments.get("message")
            context_raw = arguments.get("context", {})
            timeout = arguments.get("timeout", 300.0)
            save_to_project = arguments.get("save_to_project", False)

            # Ensure context is a dictionary
            if isinstance(context_raw, dict):
                context = context_raw.copy()
            else:
                context = {}

            # Convert fields to standard format for SSE event and handler
            fields_for_sse = []
            fields_for_handler = []
            for field in fields_raw:
                # Map from agent tool schema to internal format
                var_name = field.get("variable_name", field.get("name", ""))
                display_name = field.get("display_name", field.get("label", var_name))
                input_type_str = field.get("input_type", "text")
                is_required = field.get("is_required", field.get("required", True))
                is_secret = field.get("is_secret", True)

                # Create field dict for SSE (frontend format)
                field_dict = {
                    "name": var_name,
                    "label": display_name,
                    "description": field.get("description"),
                    "required": is_required,
                    "input_type": input_type_str,
                    "default_value": field.get("default_value"),
                    "placeholder": field.get("placeholder"),
                    "secret": is_secret,
                }
                fields_for_sse.append(field_dict)
                fields_for_handler.append(field_dict)

            # Generate request ID for tracking
            request_id = f"envvar_{uuid.uuid4().hex[:8]}"

            # Emit env_var_requested event BEFORE blocking
            yield AgentEnvVarRequestedEvent(
                request_id=request_id,
                tool_name=target_tool_name,
                fields=fields_for_sse,
                context=context if context else {},
            )

            # Use TemporalHITLHandler for request/response
            start_time = time.time()
            try:
                values = await handler.request_env_vars(
                    tool_name=target_tool_name,
                    fields=fields_for_handler,
                    message=message,
                    timeout_seconds=timeout,
                )
                end_time = time.time()

                # values is a Dict[str, str] of variable_name -> value
                saved_variables = []

                # Save environment variables to database
                ctx = self._langfuse_context or {}
                tenant_id = ctx.get("tenant_id")
                project_id = ctx.get("project_id")

                if tenant_id and values:
                    try:
                        from src.domain.model.agent.tool_environment_variable import (
                            EnvVarScope,
                            ToolEnvironmentVariable,
                        )
                        from src.infrastructure.adapters.secondary.persistence.database import (
                            async_session_factory,
                        )
                        from src.infrastructure.adapters.secondary.persistence.sql_tool_environment_variable_repository import (
                            SqlToolEnvironmentVariableRepository,
                        )
                        from src.infrastructure.security.encryption_service import (
                            get_encryption_service,
                        )

                        encryption_service = get_encryption_service()
                        scope = (
                            EnvVarScope.PROJECT
                            if save_to_project and project_id
                            else EnvVarScope.TENANT
                        )
                        effective_project_id = project_id if save_to_project else None

                        async with async_session_factory() as db_session:
                            repository = SqlToolEnvironmentVariableRepository(db_session)
                            for field_spec in fields_for_sse:
                                var_name = field_spec["name"]
                                if var_name in values and values[var_name]:
                                    # Encrypt the value
                                    encrypted_value = encryption_service.encrypt(values[var_name])

                                    # Create domain entity
                                    env_var = ToolEnvironmentVariable(
                                        tenant_id=tenant_id,
                                        project_id=effective_project_id,
                                        tool_name=target_tool_name,
                                        variable_name=var_name,
                                        encrypted_value=encrypted_value,
                                        description=field_spec.get("description"),
                                        is_required=field_spec.get("required", True),
                                        is_secret=field_spec.get("secret", True),
                                        scope=scope,
                                    )

                                    # Upsert to database
                                    await repository.upsert(env_var)
                                    saved_variables.append(var_name)

                                    logger.info(f"Saved env var: {target_tool_name}/{var_name}")
                            await db_session.commit()
                    except Exception as e:
                        logger.error(f"Error saving env vars to database: {e}")
                        # Even if save fails, include the variable names
                        saved_variables = list(values.keys()) if values else []
                else:
                    saved_variables = list(values.keys()) if values else []

                # Emit provided event
                yield AgentEnvVarProvidedEvent(
                    request_id=request_id,
                    tool_name=target_tool_name,
                    saved_variables=saved_variables,
                )

                # Update tool part
                tool_part.status = ToolState.COMPLETED
                result = {
                    "success": True,
                    "tool_name": target_tool_name,
                    "saved_variables": saved_variables,
                    "message": f"Successfully saved {len(saved_variables)} environment variable(s)",
                }
                tool_part.output = json.dumps(result)
                tool_part.end_time = end_time

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    result=result,
                    duration_ms=int((end_time - start_time) * 1000),
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )

            except asyncio.TimeoutError:
                tool_part.status = ToolState.ERROR
                tool_part.error = "Environment variable request timed out"
                tool_part.end_time = time.time()

                yield AgentObserveEvent(
                    tool_name=tool_name,
                    error="Environment variable request timed out",
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )

        except HITLPendingException:
            # Let HITLPendingException bubble up to Activity layer
            # The Workflow will wait for user response and resume execution
            raise

        except Exception as e:
            logger.error(f"Environment variable tool error: {e}", exc_info=True)
            tool_part.status = ToolState.ERROR
            tool_part.error = str(e)
            tool_part.end_time = time.time()

            yield AgentObserveEvent(
                tool_name=tool_name,
                error=str(e),
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
            )

        self._state = ProcessorState.OBSERVING

    def abort(self) -> None:
        """Abort current processing."""
        if self._abort_event:
            self._abort_event.set()

    def get_session_summary(self) -> Dict[str, Any]:
        """Get summary of session costs and tokens."""
        return self.cost_tracker.get_session_summary()


def create_processor(
    model: str,
    tools: List[ToolDefinition],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    **kwargs,
) -> SessionProcessor:
    """
    Factory function to create session processor.

    Args:
        model: Model name
        tools: List of tool definitions
        api_key: Optional API key
        base_url: Optional base URL
        **kwargs: Additional configuration options

    Returns:
        Configured SessionProcessor instance
    """
    config = ProcessorConfig(
        model=model,
        api_key=api_key,
        base_url=base_url,
        **kwargs,
    )
    return SessionProcessor(config, tools)
