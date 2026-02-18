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
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Dict, List, Optional

from src.domain.events.agent_events import (
    AgentActDeltaEvent,
    AgentActEvent,
    AgentArtifactCreatedEvent,
    AgentArtifactErrorEvent,
    AgentArtifactOpenEvent,
    AgentArtifactReadyEvent,
    AgentCompactNeededEvent,
    AgentCompleteEvent,
    AgentContextStatusEvent,
    AgentCostUpdateEvent,
    AgentDomainEvent,
    AgentDoomLoopDetectedEvent,
    AgentErrorEvent,
    AgentEventType,
    AgentMCPAppResultEvent,
    AgentObserveEvent,
    AgentPermissionAskedEvent,
    AgentRetryEvent,
    AgentStartEvent,
    AgentStatusEvent,
    AgentSuggestionsEvent,
    AgentTextDeltaEvent,
    AgentTextEndEvent,
    AgentTextStartEvent,
    AgentThoughtDeltaEvent,
    AgentThoughtEvent,
)
from src.infrastructure.adapters.secondary.sandbox.artifact_integration import (
    extract_artifacts_from_mcp_result,
)

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService


from ..core.llm_stream import LLMStream, StreamConfig, StreamEventType
from ..core.message import Message, MessageRole, ToolPart, ToolState
from ..cost import CostTracker, TokenUsage
from ..doom_loop import DoomLoopDetector
from ..hitl.coordinator import HITLCoordinator
from ..permission import PermissionAction, PermissionManager
from ..retry import RetryPolicy
from .hitl_tool_handler import (
    handle_clarification_tool,
    handle_decision_tool,
    handle_env_var_tool,
)
from .message_utils import classify_tool_by_description, extract_user_query

logger = logging.getLogger(__name__)


def _strip_artifact_binary_data(result: Dict[str, Any]) -> Dict[str, Any]:
    """Return a shallow copy of an artifact result with binary/base64 data removed.

    The artifact binary content is handled separately by ``_process_tool_artifacts``
    and must not leak into the ``AgentObserveEvent.result`` field.  Keeping it
    there causes the JSON payload persisted to Redis and PostgreSQL to be
    extremely large, which can fail the entire event-persistence transaction
    and lose all conversation history.
    """
    cleaned = {**result}
    if "artifact" in cleaned and isinstance(cleaned["artifact"], dict):
        artifact = {**cleaned["artifact"]}
        artifact.pop("data", None)
        cleaned["artifact"] = artifact
    # Also strip base64 from embedded MCP content items
    if "content" in cleaned and isinstance(cleaned["content"], list):
        stripped_content = []
        for item in cleaned["content"]:
            if isinstance(item, dict) and item.get("type") in ("image", "resource"):
                item = {**item}
                item.pop("data", None)
            stripped_content.append(item)
        cleaned["content"] = stripped_content
    return cleaned


# Canvas-displayable MIME type mapping
_CANVAS_MIME_MAP: Dict[str, str] = {
    "text/html": "preview",
    "text/markdown": "markdown",
    "text/csv": "data",
    "application/json": "data",
    "application/xml": "data",
    "text/xml": "data",
}


def _get_canvas_content_type(mime_type: str, filename: str) -> Optional[str]:
    """Determine canvas content type for a given MIME type and filename."""
    if mime_type in _CANVAS_MIME_MAP:
        return _CANVAS_MIME_MAP[mime_type]
    if mime_type.startswith("text/"):
        return "code"
    # Check common code extensions
    code_exts = {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".sh",
        ".bash",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".sql",
        ".css",
        ".scss",
        ".less",
        ".vue",
        ".svelte",
    }
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in code_exts:
        return "code"
    return None


_LANG_EXT_MAP: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".sh": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".md": "markdown",
    ".xml": "xml",
    ".toml": "toml",
}


def _get_language_from_filename(filename: str) -> Optional[str]:
    """Get language identifier from filename extension."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _LANG_EXT_MAP.get(ext)


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
    max_cost_per_request: float = 0  # Per-request cost limit (0 = unlimited)
    max_cost_per_session: float = 0  # Per-session cost limit (0 = unlimited)

    # LLM Client (optional, provides circuit breaker + rate limiter)
    llm_client: Optional[Any] = None

    # Tool refresh callback (optional, enables dynamic tool loading)
    # When provided, _refresh_tools() can fetch updated tools at runtime
    tool_provider: Optional[Callable[[], List["ToolDefinition"]]] = None


@dataclass
class ToolDefinition:
    """Tool definition for LLM."""

    name: str
    description: str
    parameters: Dict[str, Any]
    execute: Callable[..., Any]  # Async callable
    permission: Optional[str] = None  # Permission required
    _tool_instance: Any = field(default=None, repr=False)  # Original tool object

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
        self.cost_tracker = CostTracker(
            context_limit=config.context_limit,
            max_cost_per_request=config.max_cost_per_request,
            max_cost_per_session=config.max_cost_per_session,
        )

        # Artifact service for rich output handling
        self._artifact_service = artifact_service

        # LLM client for streaming (with circuit breaker + rate limiter)
        self._llm_client = config.llm_client

        # Session state
        self._state = ProcessorState.IDLE
        self._step_count = 0
        self._current_message: Optional[Message] = None
        self._pending_tool_calls: Dict[str, ToolPart] = {}
        self._pending_tool_args: Dict[str, str] = {}  # call_id -> accumulated raw args
        self._abort_event: Optional[asyncio.Event] = None

        # Task tracking for timeline integration
        self._current_task: Optional[Dict[str, Any]] = None

        # Langfuse observability context
        self._langfuse_context: Optional[Dict[str, Any]] = None

        # HITL handler (created lazily when context is available)
        self._hitl_coordinator: Optional[HITLCoordinator] = None

        # Tool provider callback for dynamic tool refresh
        # When set, _refresh_tools() can update self.tools at runtime
        self._tool_provider: Optional[Callable[[], List[ToolDefinition]]] = config.tool_provider

    @property
    def state(self) -> ProcessorState:
        """Get current processor state."""
        return self._state

    def _get_hitl_coordinator(self) -> HITLCoordinator:
        """Get or create the HITL coordinator for current context."""
        ctx = self._langfuse_context or {}
        conversation_id = ctx.get("conversation_id", "unknown")
        tenant_id = ctx.get("tenant_id", "unknown")
        project_id = ctx.get("project_id", "unknown")
        message_id = ctx.get("message_id")

        if (
            self._hitl_coordinator is None
            or self._hitl_coordinator.conversation_id != conversation_id
        ):
            logger.debug(
                f"[Processor] Creating HITL coordinator for conversation={conversation_id}"
            )
            self._hitl_coordinator = HITLCoordinator(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                project_id=project_id,
                message_id=message_id,
            )

        return self._hitl_coordinator

    def _refresh_tools(self) -> Optional[int]:
        """Refresh tools from the tool_provider callback.

        Called after register_mcp_server succeeds to load newly registered
        MCP tools into the current session. This enables immediate access
        to new tools without restarting the session.

        Returns:
            Number of tools after refresh, or None if no provider set or error.
        """
        if self._tool_provider is None:
            return None

        try:
            new_tools = self._tool_provider()
            if new_tools is None:
                logger.warning("[Processor] tool_provider returned None, skipping refresh")
                return None

            # Update tools dict with new tool definitions
            self.tools = {t.name: t for t in new_tools}
            logger.info(
                "[Processor] Refreshed tools from provider: %d tools available", len(self.tools)
            )
            return len(self.tools)

        except Exception as e:
            logger.warning("[Processor] Failed to refresh tools from provider: %s", e)
            return None

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

        # Emit start event
        yield AgentStartEvent()
        self._state = ProcessorState.THINKING

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
                had_tool_calls = False
                async for event in self._process_step(session_id, messages):
                    yield event

                    # Check for stop conditions in events
                    if event.event_type == AgentEventType.ERROR:
                        result = ProcessorResult.STOP
                        break
                    elif event.event_type == AgentEventType.ACT:
                        had_tool_calls = True
                    elif event.event_type == AgentEventType.COMPACT_NEEDED:
                        result = ProcessorResult.COMPACT
                        break

                # If no stop/compact, determine result from tool calls
                if result == ProcessorResult.CONTINUE:
                    if had_tool_calls:
                        result = ProcessorResult.CONTINUE
                    else:
                        result = ProcessorResult.COMPLETE

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
                # Generate follow-up suggestions
                suggestions_event = await self._generate_suggestions(messages)
                if suggestions_event:
                    yield suggestions_event

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

        except Exception as e:
            logger.error(f"Processor error: {e}", exc_info=True)
            yield AgentErrorEvent(message=str(e), code=type(e).__name__)
            self._state = ProcessorState.ERROR

    def _extract_user_query(self, messages: List[Dict[str, Any]]) -> Optional[str]:
        """Extract the latest user query from messages."""
        return extract_user_query(messages)

    async def _generate_suggestions(
        self, messages: List[Dict[str, Any]]
    ) -> Optional[AgentSuggestionsEvent]:
        """Generate follow-up suggestions based on conversation context.

        Uses a lightweight LLM call to produce 2-3 contextually relevant
        follow-up prompts that the user might want to ask next.

        Args:
            messages: Full conversation messages in OpenAI format

        Returns:
            AgentSuggestionsEvent if suggestions were generated, None otherwise
        """
        if not self._llm_client:
            return None

        try:
            # Extract recent context (last few messages for efficiency)
            recent = messages[-6:] if len(messages) > 6 else messages
            context_summary = []
            for msg in recent:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    context_summary.append(f"{role}: {content[:200]}")

            if not context_summary:
                return None

            suggestion_prompt = [
                {
                    "role": "system",
                    "content": (
                        "Based on the conversation below, generate exactly 3 short follow-up "
                        "questions or actions the user might want to take next. "
                        "Each suggestion should be concise (under 60 characters), actionable, "
                        "and contextually relevant. Return ONLY a JSON array of strings, "
                        "no other text. Example: "
                        '["Explain the error in detail", "Show me the code fix", '
                        '"Run the tests again"]'
                    ),
                },
                {
                    "role": "user",
                    "content": "\n".join(context_summary),
                },
            ]

            response = await self._llm_client.generate(
                messages=suggestion_prompt,
                temperature=0.7,
                max_tokens=200,
            )

            content = response.get("content", "")
            # Parse JSON array from response
            suggestions = json.loads(content)
            if isinstance(suggestions, list) and all(isinstance(s, str) for s in suggestions):
                return AgentSuggestionsEvent(suggestions=suggestions[:3])
        except Exception as e:
            logger.debug(f"Failed to generate suggestions: {e}")

        return None

    def _classify_tool_by_description(self, tool_name: str, tool_def: ToolDefinition) -> str:
        """Classify tool into a category based on its description."""
        return classify_tool_by_description(tool_name, tool_def.description)

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
        logger.debug(f"[Processor] _process_step: session={session_id}, step={self._step_count}")

        # Create new assistant message
        self._current_message = Message(
            session_id=session_id,
            role=MessageRole.ASSISTANT,
        )

        # Reset pending tool calls
        self._pending_tool_calls = {}
        self._pending_tool_args = {}

        # Prepare tools for LLM
        tools_for_llm = [t.to_openai_format() for t in self.tools.values()]

        # Create stream config
        stream_config = StreamConfig(
            model=self.config.model,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            tools=tools_for_llm if tools_for_llm else None,
        )

        # Create LLM stream with optional client (provides circuit breaker + rate limiter)
        llm_stream = LLMStream(stream_config, llm_client=self._llm_client)

        # Track state for this step
        text_buffer = ""
        reasoning_buffer = ""
        tool_calls_completed = []
        step_tokens = TokenUsage()
        step_cost = 0.0
        finish_reason = "stop"

        # Process LLM stream with retry
        attempt = 0
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

                logger.debug(f"[Processor] Calling llm_stream.generate(), step={self._step_count}")
                async for event in llm_stream.generate(
                    messages, langfuse_context=step_langfuse_context
                ):
                    # Check abort
                    if self._abort_event and self._abort_event.is_set():
                        raise asyncio.CancelledError("Aborted")

                    # Process stream events
                    if event.type == StreamEventType.TEXT_START:
                        yield AgentTextStartEvent()

                    elif event.type == StreamEventType.TEXT_DELTA:
                        delta = event.data.get("delta", "")
                        text_buffer += delta
                        yield AgentTextDeltaEvent(delta=delta)

                    elif event.type == StreamEventType.TEXT_END:
                        full_text = event.data.get("full_text", text_buffer)
                        logger.debug(
                            f"[Processor] TEXT_END: len={len(full_text) if full_text else 0}"
                        )
                        self._current_message.add_text(full_text)
                        yield AgentTextEndEvent(full_text=full_text)

                    elif event.type == StreamEventType.REASONING_START:
                        # Only track state internally - don't emit an empty thought event.
                        # The subsequent REASONING_DELTA events handle streaming display,
                        # and REASONING_END emits the full thought content.
                        pass

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
                        self._pending_tool_args[call_id] = ""

                        # Emit act_delta so frontend can show tool skeleton immediately
                        yield AgentActDeltaEvent(
                            tool_name=tool_name,
                            call_id=call_id,
                            arguments_fragment="",
                            accumulated_arguments="",
                        )

                    elif event.type == StreamEventType.TOOL_CALL_DELTA:
                        call_id = event.data.get("call_id", "")
                        args_delta = event.data.get("arguments_delta", "")
                        if call_id in self._pending_tool_calls and args_delta:
                            self._pending_tool_args[call_id] = (
                                self._pending_tool_args.get(call_id, "") + args_delta
                            )
                            tool_part = self._pending_tool_calls[call_id]
                            yield AgentActDeltaEvent(
                                tool_name=tool_part.tool or "",
                                call_id=call_id,
                                arguments_fragment=args_delta,
                                accumulated_arguments=self._pending_tool_args[call_id],
                            )

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

                            yield AgentActEvent(
                                tool_name=tool_name,
                                tool_input=arguments,
                                call_id=call_id,
                                status="running",
                                tool_execution_id=tool_part.tool_execution_id,
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

                        # Emit context status using this call's input tokens
                        # (= actual context window size the LLM processed)
                        context_limit = self.config.context_limit
                        current_input = step_tokens.input
                        occupancy = (
                            (current_input / context_limit * 100) if context_limit > 0 else 0
                        )
                        yield AgentContextStatusEvent(
                            current_tokens=current_input,
                            token_budget=context_limit,
                            occupancy_pct=round(occupancy, 1),
                            compression_level="none",
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

        # Emit context status update after step completes.
        # If LLM reported usage (via USAGE event), step_tokens.input is accurate.
        # Otherwise, estimate from message content length (~4 chars/token).
        context_limit = self.config.context_limit
        current_input = step_tokens.input
        if current_input == 0:
            total_chars = sum(len(str(m.get("content", ""))) for m in messages)
            current_input = total_chars // 4
        occupancy = (current_input / context_limit * 100) if context_limit > 0 else 0
        yield AgentContextStatusEvent(
            current_tokens=current_input,
            token_budget=context_limit,
            occupancy_pct=round(occupancy, 1),
            compression_level="none",
        )

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

            # Inject session_id for tools that need conversation context
            # (todoread/todowrite) so LLM doesn't have to guess it
            if tool_name in ("todoread", "todowrite") and "session_id" not in arguments:
                arguments["session_id"] = session_id

            # Call tool execute function
            start_time = time.time()
            result = await tool_def.execute(**arguments)
            end_time = time.time()

            # Handle structured return format {title, output, metadata}
            # Reference: OpenCode SkillTool structured return
            if isinstance(result, dict) and "artifact" in result:
                # Artifact result (e.g., export_artifact) - use summary, never base64
                artifact = result["artifact"]
                output_str = result.get(
                    "output",
                    f"Exported artifact: {artifact.get('filename', 'unknown')} "
                    f"({artifact.get('mime_type', 'unknown')}, "
                    f"{artifact.get('size', 0)} bytes)",
                )
                # Strip binary data from SSE result to prevent huge JSON in
                # Redis/DB persistence.  The artifact binary is handled
                # separately by _process_tool_artifacts().
                sse_result = _strip_artifact_binary_data(result)
            elif isinstance(result, dict) and "output" in result:
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
            tool_part.output = self._sanitize_tool_output(output_str)
            tool_part.end_time = end_time

            # Check if tool has MCP App UI metadata (needed for observe + mcp_app_result)
            tool_instance = getattr(tool_def, "_tool_instance", None)
            has_ui = getattr(tool_instance, "has_ui", False) if tool_instance else False

            # Fallback: for mcp__ tools without _ui_metadata, try DB lookup
            if not has_ui and tool_name.startswith("mcp__") and tool_instance:
                _app_id_fb = getattr(tool_instance, "_app_id", "") or ""
                if _app_id_fb:
                    has_ui = True
                    logger.debug(
                        "[MCPApp] Fallback: tool %s has app_id=%s but no _ui_metadata",
                        tool_name,
                        _app_id_fb,
                    )

            # Build observe-level ui_metadata for MCP tools with UI
            _observe_ui_meta: dict | None = None
            if tool_instance and has_ui:
                _raw_ui = getattr(tool_instance, "ui_metadata", None) or {}
                _o_app_id = (
                    getattr(tool_instance, "_last_app_id", "")
                    or getattr(tool_instance, "_app_id", "")
                    or ""
                )
                _o_server = getattr(tool_instance, "_server_name", "") or ""
                _o_project_id = (self._langfuse_context or {}).get("project_id", "")
                _observe_ui_meta = {
                    "resource_uri": _raw_ui.get("resourceUri", ""),
                    "server_name": _o_server,
                    "app_id": _o_app_id,
                    "title": _raw_ui.get("title", ""),
                    "project_id": _o_project_id,
                }

            yield AgentObserveEvent(
                tool_name=tool_name,
                result=sse_result,
                duration_ms=int((end_time - start_time) * 1000),
                call_id=call_id,
                tool_execution_id=tool_part.tool_execution_id,
                ui_metadata=_observe_ui_meta,
            )

            if tool_instance and has_ui:
                ui_meta = getattr(tool_instance, "ui_metadata", None) or {}
                app_id = (
                    getattr(tool_instance, "_last_app_id", "")
                    or getattr(tool_instance, "_app_id", "")
                    or ""
                )
                # Generate a synthetic app_id from tool name when no DB record
                if not app_id:
                    app_id = f"_synthetic_{tool_name}"
                # Fetch live HTML from MCP server via resources/read
                resource_html = ""
                fetch_fn = getattr(tool_instance, "fetch_resource_html", None)
                if fetch_fn:
                    try:
                        resource_html = await fetch_fn()
                    except Exception as fetch_err:
                        logger.warning(
                            "[MCPApp] fetch_resource_html failed for %s: %s",
                            tool_name,
                            fetch_err,
                        )
                if not resource_html:
                    # Fallback to cached inline HTML
                    resource_html = getattr(tool_instance, "_last_html", "") or ""
                logger.debug(
                    "[MCPApp] Emitting event: tool=%s, app_id=%s, resource_uri=%s, html_len=%d",
                    tool_name,
                    app_id,
                    ui_meta.get("resourceUri", ""),
                    len(resource_html),
                )
                _server_name = getattr(tool_instance, "_server_name", "") or ""
                _project_id = (self._langfuse_context or {}).get("project_id", "")

                # SEP-1865: Extract structuredContent from tool result if present
                _structured_content = None
                if isinstance(sse_result, dict):
                    _structured_content = sse_result.get("structuredContent")

                yield AgentMCPAppResultEvent(
                    app_id=app_id,
                    tool_name=tool_name,
                    tool_result=sse_result,
                    tool_input=arguments if arguments else None,
                    resource_html=resource_html,
                    resource_uri=ui_meta.get("resourceUri", ""),
                    ui_metadata=ui_meta,
                    tool_execution_id=tool_part.tool_execution_id,
                    project_id=_project_id,
                    server_name=_server_name,
                    structured_content=_structured_content,
                )

            # Extract and upload artifacts from tool result (images, files, etc.)
            # Timeouts are handled inside _process_tool_artifacts itself.
            try:
                async for artifact_event in self._process_tool_artifacts(
                    tool_name=tool_name,
                    result=result,
                    tool_execution_id=tool_part.tool_execution_id,
                ):
                    yield artifact_event
            except Exception as artifact_err:
                logger.error(
                    f"Artifact processing failed for tool {tool_name}: {artifact_err}",
                    exc_info=True,
                )

            # Emit pending task SSE events from todowrite tool
            tool_instance = getattr(tool_def, "_tool_instance", None)
            if (
                tool_name == "todowrite"
                and tool_instance
                and hasattr(tool_instance, "consume_pending_events")
            ):
                try:
                    pending = tool_instance.consume_pending_events()
                    logger.info(
                        f"[Processor] todowrite pending events: count={len(pending)}, "
                        f"conversation_id={session_id}"
                    )
                    if not pending:
                        logger.warning(
                            "[Processor] todowrite produced no pending events - "
                            "tool may have failed silently"
                        )
                    for task_event in pending:
                        from src.domain.events.agent_events import (
                            AgentTaskCompleteEvent,
                            AgentTaskListUpdatedEvent,
                            AgentTaskStartEvent,
                            AgentTaskUpdatedEvent,
                        )

                        event_type = task_event.get("type")
                        if event_type == "task_list_updated":
                            tasks = task_event["tasks"]
                            logger.info(
                                f"[Processor] Emitting task_list_updated: "
                                f"{len(tasks)} tasks for {task_event['conversation_id']}"
                            )
                            yield AgentTaskListUpdatedEvent(
                                conversation_id=task_event["conversation_id"],
                                tasks=tasks,
                            )
                            # Track total tasks for timeline progress
                            total = len(tasks)
                            for t in tasks:
                                if t.get("status") == "in_progress":
                                    self._current_task = {
                                        "task_id": t["id"],
                                        "content": t["content"],
                                        "order_index": t.get("order_index", 0),
                                        "total_tasks": total,
                                    }
                                    yield AgentTaskStartEvent(
                                        task_id=t["id"],
                                        content=t["content"],
                                        order_index=t.get("order_index", 0),
                                        total_tasks=total,
                                    )
                        elif event_type == "task_updated":
                            task_status = task_event["status"]
                            yield AgentTaskUpdatedEvent(
                                conversation_id=task_event["conversation_id"],
                                task_id=task_event["task_id"],
                                status=task_status,
                                content=task_event.get("content"),
                            )
                            # Detect task transitions for timeline events
                            if task_status == "in_progress":
                                total = (
                                    self._current_task["total_tasks"] if self._current_task else 1
                                )
                                self._current_task = {
                                    "task_id": task_event["task_id"],
                                    "content": task_event.get("content", ""),
                                    "order_index": task_event.get("order_index", 0),
                                    "total_tasks": total,
                                }
                                yield AgentTaskStartEvent(
                                    task_id=task_event["task_id"],
                                    content=task_event.get("content", ""),
                                    order_index=task_event.get("order_index", 0),
                                    total_tasks=total,
                                )
                            elif task_status in (
                                "completed",
                                "failed",
                                "cancelled",
                            ):
                                ct = self._current_task
                                if ct and ct["task_id"] == task_event["task_id"]:
                                    yield AgentTaskCompleteEvent(
                                        task_id=ct["task_id"],
                                        status=task_status,
                                        order_index=ct["order_index"],
                                        total_tasks=ct["total_tasks"],
                                    )
                                    self._current_task = None
                except Exception as task_err:
                    logger.error(f"Task event emission failed: {task_err}", exc_info=True)

            # Emit pending SSE events from register_mcp_server tool
            if (
                tool_name == "register_mcp_server"
                and tool_instance
                and hasattr(tool_instance, "consume_pending_events")
            ):
                try:
                    for event in tool_instance.consume_pending_events():
                        yield event
                except Exception as reg_err:
                    logger.error(f"{tool_name} event emission failed: {reg_err}")

            # Refresh tools after successful register_mcp_server execution
            # This enables immediate access to newly registered MCP tools
            if tool_name == "register_mcp_server":
                # Check if registration succeeded (no error prefix in output)
                if isinstance(output_str, str) and not output_str.startswith("Error:"):
                    logger.info("[Processor] register_mcp_server succeeded, refreshing tools")
                    self._refresh_tools()
                else:
                    logger.debug(
                        "[Processor] register_mcp_server failed or returned error, "
                        "skipping tool refresh"
                    )

        except Exception as e:
            logger.error(f"Tool execution error: {e}", exc_info=True)

            tool_part.status = ToolState.ERROR
            tool_part.error = str(e)
            tool_part.end_time = time.time()

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

    # Max bytes for tool output stored in LLM context
    _MAX_TOOL_OUTPUT_BYTES = 30_000

    # Regex matching long base64-like sequences (256+ chars of [A-Za-z0-9+/=])
    _BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/=]{256,}")

    def _sanitize_tool_output(self, output: str) -> str:
        """Sanitize tool output to prevent binary/base64 data from entering LLM context.

        Applies two defensive filters:
        1. Replace long base64-like sequences with a placeholder.
        2. Truncate output exceeding _MAX_TOOL_OUTPUT_BYTES.
        """
        if not output:
            return output

        # Strip embedded base64 blobs
        sanitized = self._BASE64_PATTERN.sub("[binary data omitted]", output)

        # Hard size cap
        encoded = sanitized.encode("utf-8", errors="replace")
        if len(encoded) > self._MAX_TOOL_OUTPUT_BYTES:
            sanitized = encoded[: self._MAX_TOOL_OUTPUT_BYTES].decode("utf-8", errors="ignore")
            sanitized += "\n... [output truncated]"

        return sanitized

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
        # Use WARNING level for artifact processing diagnostics (INFO not visible under uvicorn)
        logger.warning(
            f"[ArtifactUpload] Processing tool={tool_name}, "
            f"has_service={self._artifact_service is not None}, "
            f"result_type={type(result).__name__}"
        )

        if not self._artifact_service:
            logger.warning("[ArtifactUpload] No artifact_service configured, skipping")
            return

        # Get context from langfuse context
        ctx = self._langfuse_context or {}
        project_id = ctx.get("project_id")
        tenant_id = ctx.get("tenant_id")
        conversation_id = ctx.get("conversation_id")
        message_id = ctx.get("message_id")

        if not project_id or not tenant_id:
            logger.warning(
                f"[ArtifactUpload] Missing context: project_id={project_id}, tenant_id={tenant_id}"
            )
            return

        # Check if result contains MCP-style content
        if not isinstance(result, dict):
            return

        has_artifact = result.get("artifact") is not None
        if has_artifact:
            has_data = result["artifact"].get("data") is not None
            logger.warning(
                f"[ArtifactUpload] tool={tool_name}, has_data={has_data}, "
                f"encoding={result['artifact'].get('encoding')}"
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
                        logger.warning(
                            f"[ArtifactUpload] Decoded {len(file_content)} bytes from base64"
                        )
                    else:
                        logger.warning("[ArtifactUpload] base64 encoding but no data found")
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

                # Detect MIME type for the artifact_created event
                from src.application.services.artifact_service import (
                    detect_mime_type,
                    get_category_from_mime,
                )

                filename = artifact_info.get("filename", "exported_file")
                mime_type = detect_mime_type(filename)
                category = get_category_from_mime(mime_type)
                artifact_id = str(uuid.uuid4())

                # Yield artifact_created event IMMEDIATELY so the frontend
                # knows about the artifact even if the upload is slow.
                yield AgentArtifactCreatedEvent(
                    artifact_id=artifact_id,
                    filename=filename,
                    mime_type=mime_type,
                    category=category.value,
                    size_bytes=len(file_content),
                    url=None,
                    preview_url=None,
                    tool_execution_id=tool_execution_id,
                    source_tool=tool_name,
                    source_path=artifact_info.get("path"),
                )

                # Emit artifact_open for canvas-displayable content
                canvas_type = _get_canvas_content_type(mime_type, filename)
                if canvas_type and len(file_content) < 500_000:
                    try:
                        text_content = file_content.decode("utf-8")
                        yield AgentArtifactOpenEvent(
                            artifact_id=artifact_id,
                            title=filename,
                            content=text_content,
                            content_type=canvas_type,
                            language=_get_language_from_filename(filename),
                        )
                    except (UnicodeDecodeError, ValueError):
                        pass  # Binary content, skip canvas open

                # Upload artifact in a background thread to avoid event loop
                # contention. aioboto3 upload hangs when the event loop is busy
                # with LLM streaming, so we use synchronous boto3 in a thread.
                logger.warning(
                    f"[ArtifactUpload] Scheduling threaded upload: filename={filename}, "
                    f"size={len(file_content)}, project_id={project_id}"
                )

                def _sync_upload(
                    content: bytes,
                    fname: str,
                    pid: str,
                    tid: str,
                    texec_id: str,
                    tname: str,
                    art_id: str,
                    bucket: str,
                    endpoint: str,
                    access_key: str,
                    secret_key: str,
                    region: str,
                    mime: str,
                    no_proxy: bool = False,
                ) -> dict:
                    """Synchronous S3 upload in a thread pool."""
                    from datetime import date
                    from urllib.parse import quote

                    import boto3
                    from botocore.config import Config as BotoConfig

                    config_kwargs: dict = {
                        "connect_timeout": 10,
                        "read_timeout": 30,
                        "retries": {"max_attempts": 5, "mode": "standard"},
                    }
                    if no_proxy:
                        config_kwargs["proxies"] = {"http": None, "https": None}

                    s3 = boto3.client(
                        "s3",
                        endpoint_url=endpoint,
                        aws_access_key_id=access_key,
                        aws_secret_access_key=secret_key,
                        region_name=region,
                        config=BotoConfig(**config_kwargs),
                    )

                    date_part = date.today().strftime("%Y/%m/%d")
                    unique_id = art_id[:8]
                    safe_fname = fname.replace("/", "_")
                    object_key = (
                        f"artifacts/{tid}/{pid}/{date_part}"
                        f"/{texec_id or 'direct'}/{unique_id}_{safe_fname}"
                    )

                    metadata = {
                        "artifact_id": art_id,
                        "project_id": pid,
                        "tenant_id": tid,
                        "filename": quote(fname, safe=""),
                        "source_tool": tname or "",
                    }

                    s3.put_object(
                        Bucket=bucket,
                        Key=object_key,
                        Body=content,
                        ContentType=mime,
                        Metadata=metadata,
                    )

                    url = s3.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": bucket, "Key": object_key},
                        ExpiresIn=7 * 24 * 3600,
                    )

                    return {
                        "url": url,
                        "object_key": object_key,
                        "size_bytes": len(content),
                    }

                async def _threaded_upload(
                    content: bytes,
                    fname: str,
                    pid: str,
                    tid: str,
                    texec_id: str,
                    conv_id: str,
                    msg_id: str,
                    tname: str,
                    art_id: str,
                    mime: str,
                    cat: str,
                ):
                    """Run sync upload in thread, then publish result to Redis and DB."""
                    import time as _time

                    from src.configuration.config import get_settings
                    from src.infrastructure.agent.actor.execution import (
                        _persist_events,
                        _publish_event_to_stream,
                    )

                    settings = get_settings()

                    try:
                        result = await asyncio.to_thread(
                            _sync_upload,
                            content=content,
                            fname=fname,
                            pid=pid,
                            tid=tid,
                            texec_id=texec_id,
                            tname=tname,
                            art_id=art_id,
                            bucket=settings.s3_bucket_name,
                            endpoint=settings.s3_endpoint_url,
                            access_key=settings.aws_access_key_id,
                            secret_key=settings.aws_secret_access_key,
                            region=settings.aws_region,
                            mime=mime,
                            no_proxy=settings.s3_no_proxy,
                        )
                        logger.warning(
                            f"[ArtifactUpload] Threaded upload SUCCESS: "
                            f"filename={fname}, url={result['url'][:80]}"
                        )

                        ready_event = AgentArtifactReadyEvent(
                            artifact_id=art_id,
                            filename=fname,
                            mime_type=mime,
                            category=cat,
                            size_bytes=result["size_bytes"],
                            url=result["url"],
                            tool_execution_id=texec_id,
                            source_tool=tname,
                        )
                        ready_event_dict = ready_event.to_event_dict()
                        ready_time_us = int(_time.time() * 1_000_000)
                        await _publish_event_to_stream(
                            conversation_id=conv_id,
                            event=ready_event_dict,
                            message_id=msg_id,
                            event_time_us=ready_time_us,
                            event_counter=0,
                        )
                        # Persist to DB so history loading can merge URL into artifact_created
                        await _persist_events(
                            conversation_id=conv_id,
                            message_id=msg_id,
                            events=[
                                {
                                    **ready_event_dict,
                                    "event_time_us": ready_time_us,
                                    "event_counter": 0,
                                }
                            ],
                        )
                    except Exception as upload_err:
                        logger.error(
                            f"[ArtifactUpload] Threaded upload failed: {fname}: {upload_err}"
                        )
                        error_event = AgentArtifactErrorEvent(
                            artifact_id=art_id,
                            filename=fname,
                            tool_execution_id=texec_id,
                            error=f"Upload failed: {upload_err}",
                        )
                        error_event_dict = error_event.to_event_dict()
                        error_time_us = int(_time.time() * 1_000_000)
                        try:
                            await _publish_event_to_stream(
                                conversation_id=conv_id,
                                event=error_event_dict,
                                message_id=msg_id,
                                event_time_us=error_time_us,
                                event_counter=0,
                            )
                        except Exception:
                            logger.error("[ArtifactUpload] Failed to publish error event")
                        # Persist to DB so history loading shows error instead of uploading
                        try:
                            await _persist_events(
                                conversation_id=conv_id,
                                message_id=msg_id,
                                events=[
                                    {
                                        **error_event_dict,
                                        "event_time_us": error_time_us,
                                        "event_counter": 0,
                                    }
                                ],
                            )
                        except Exception:
                            logger.error("[ArtifactUpload] Failed to persist error event")

                asyncio.create_task(
                    _threaded_upload(
                        content=file_content,
                        fname=filename,
                        pid=project_id,
                        tid=tenant_id,
                        texec_id=tool_execution_id,
                        conv_id=conversation_id or "",
                        msg_id=message_id or "",
                        tname=tool_name,
                        art_id=artifact_id,
                        mime=mime_type,
                        cat=category.value,
                    )
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
        """Handle clarification tool — delegates to hitl_tool_handler."""
        self._state = ProcessorState.WAITING_CLARIFICATION
        coordinator = self._get_hitl_coordinator()
        async for event in handle_clarification_tool(
            coordinator=coordinator,
            call_id=call_id,
            tool_name=tool_name,
            arguments=arguments,
            tool_part=tool_part,
        ):
            yield event
        self._state = ProcessorState.OBSERVING

    async def _handle_decision_tool(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_part: ToolPart,
    ) -> AsyncIterator[AgentDomainEvent]:
        """Handle decision tool — delegates to hitl_tool_handler."""
        self._state = ProcessorState.WAITING_DECISION
        coordinator = self._get_hitl_coordinator()
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id=call_id,
            tool_name=tool_name,
            arguments=arguments,
            tool_part=tool_part,
        ):
            yield event
        self._state = ProcessorState.OBSERVING

    async def _handle_env_var_tool(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_part: ToolPart,
    ) -> AsyncIterator[AgentDomainEvent]:
        """Handle env var request tool — delegates to hitl_tool_handler."""
        self._state = ProcessorState.WAITING_ENV_VAR
        coordinator = self._get_hitl_coordinator()
        async for event in handle_env_var_tool(
            coordinator=coordinator,
            call_id=call_id,
            tool_name=tool_name,
            arguments=arguments,
            tool_part=tool_part,
            langfuse_context=self._langfuse_context,
        ):
            yield event
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
