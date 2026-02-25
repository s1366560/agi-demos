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
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional, cast

from src.domain.events.agent_events import (
    AgentActDeltaEvent,
    AgentActEvent,
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

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService


from src.domain.model.agent.hitl_types import HITLType

from ..core.llm_stream import LLMStream, StreamConfig, StreamEventType
from ..core.message import Message, MessageRole, ToolPart, ToolState
from ..cost import CostTracker, TokenUsage
from ..doom_loop import DoomLoopDetector
from ..hitl.coordinator import HITLCoordinator
from ..permission import PermissionAction, PermissionManager
from ..retry import RetryPolicy
from .artifact_handler import ArtifactHandler, strip_artifact_binary_data
from .goal_evaluator import GoalEvaluator
from .hitl_tool_handler import (
    handle_clarification_tool,
    handle_decision_tool,
    handle_env_var_tool,
)
from .message_utils import classify_tool_by_description, extract_user_query
from .run_context import RunContext

logger = logging.getLogger(__name__)


async def _iter_events(
    events: list["ProcessorEvent"],
) -> AsyncIterator["ProcessorEvent"]:
    """Tiny helper to convert a list into an async iterator."""
    for e in events:
        yield e


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
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.0
    max_tokens: int = 4096

    # Processing limits
    max_steps: int = 50  # Maximum steps before forcing stop
    max_tool_calls_per_step: int = 10  # Max tool calls per LLM response
    doom_loop_threshold: int = 3  # Consecutive identical calls to trigger
    max_no_progress_steps: int = 3  # Consecutive no-progress checks before stop

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
    llm_client: Any | None = None

    # Tool refresh callback (optional, enables dynamic tool loading)
    # When provided, _refresh_tools() can fetch updated tools at runtime
    tool_provider: Callable[[], list["ToolDefinition"]] | None = None

    # Forced skill context (optional, for loop reinforcement)
    forced_skill_name: str | None = None
    forced_skill_tools: list[str] | None = None


@dataclass
class ToolDefinition:
    """Tool definition for LLM."""

    name: str
    description: str
    parameters: dict[str, Any]
    execute: Callable[..., Any]  # Async callable
    permission: str | None = None  # Permission required
    _tool_instance: Any = field(default=None, repr=False)  # Original tool object

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


ProcessorEvent = AgentDomainEvent | dict[str, Any]


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
        tools: list[ToolDefinition],
        permission_manager: PermissionManager | None = None,
        artifact_service: Optional["ArtifactService"] = None,
    ) -> None:
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
        self._no_progress_steps = 0
        self._last_process_result: ProcessorResult = ProcessorResult.CONTINUE
        self._current_message: Message | None = None
        self._pending_tool_calls: dict[str, ToolPart] = {}
        self._pending_tool_args: dict[str, str] = {}  # call_id -> accumulated raw args
        self._abort_event: asyncio.Event | None = None

        # Task tracking for timeline integration
        self._current_task: dict[str, Any] | None = None

        # Langfuse observability context
        self._langfuse_context: dict[str, Any] | None = None

        # HITL handler (created lazily when context is available)
        self._hitl_coordinator: HITLCoordinator | None = None

        # Tool provider callback for dynamic tool refresh
        # When set, _refresh_tools() can update self.tools at runtime
        self._tool_provider: Callable[[], list[ToolDefinition]] | None = config.tool_provider

        # Forced skill context for loop reinforcement
        self._forced_skill_name: str | None = config.forced_skill_name
        self._forced_skill_tools: set[str] | None = (
            set(config.forced_skill_tools) if config.forced_skill_tools else None
        )

        # Helper state for _execute_tool decomposition
        self.__resolve_errors: list[ProcessorEvent] = []
        self.__arg_parse_errors: list[ProcessorEvent] = []
        self._permission_asked_event: ProcessorEvent | None = None
        self._last_sse_result: Any = None
        self._last_raw_result: Any = None
        self._last_output_str: str = ""

        # Extracted subsystems
        self._goal_evaluator = GoalEvaluator(
            llm_client=config.llm_client,
            tools=self.tools,
        )
        self._artifact_handler = ArtifactHandler(
            artifact_service=artifact_service,
            langfuse_context=None,
        )

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

    def _refresh_tools(self) -> int | None:
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
            if new_tools is None:  # pyright: ignore[reportUnnecessaryComparison]
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

    @staticmethod
    def _extract_mcp_resource_uri(ui_metadata: dict[str, Any] | None) -> str:
        """Extract MCP resource URI from either camelCase or snake_case metadata."""
        if not isinstance(ui_metadata, dict):
            return ""
        uri = ui_metadata.get("resourceUri") or ui_metadata.get("resource_uri")
        return str(uri) if uri else ""

    async def _load_mcp_app_ui_metadata(self, app_id: str) -> dict[str, Any]:
        """Load MCP App UI metadata from DB by app id."""
        if not app_id or app_id.startswith("_synthetic_"):
            return {}

        try:
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.sql_mcp_app_repository import (
                SqlMCPAppRepository,
            )

            async with async_session_factory() as db:
                app_repo = SqlMCPAppRepository(db)
                app = await app_repo.find_by_id(app_id)

            if not app:
                return {}

            ui_metadata = app.ui_metadata.to_dict() if app.ui_metadata else {}
            if app.resource and app.resource.uri and "resourceUri" not in ui_metadata:
                ui_metadata["resourceUri"] = app.resource.uri
            return ui_metadata
        except Exception as exc:
            logger.debug("[MCPApp] Failed to load ui metadata for app_id=%s: %s", app_id, exc)
            return {}

    async def _hydrate_mcp_ui_metadata(
        self, tool_instance: Any, app_id: str, tool_name: str
    ) -> dict[str, Any]:
        """Ensure MCP tool has usable UI metadata for app rendering."""
        ui_metadata = getattr(tool_instance, "ui_metadata", None) or {}
        if not isinstance(ui_metadata, dict):
            ui_metadata = {}

        resource_uri = self._extract_mcp_resource_uri(ui_metadata)
        if not resource_uri and app_id:
            recovered = await self._load_mcp_app_ui_metadata(app_id)
            if recovered:
                # Preserve runtime fields while filling missing resource metadata from DB.
                ui_metadata = {**recovered, **ui_metadata}
                if hasattr(tool_instance, "_ui_metadata"):
                    tool_instance._ui_metadata = ui_metadata
                logger.debug(
                    "[MCPApp] Hydrated ui metadata from DB for tool=%s app_id=%s resource_uri=%s",
                    tool_name,
                    app_id,
                    self._extract_mcp_resource_uri(ui_metadata),
                )

        return ui_metadata

    async def process(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        abort_signal: asyncio.Event | None = None,
        langfuse_context: dict[str, Any] | None = None,
        *,
        run_ctx: RunContext | None = None,
    ) -> AsyncIterator[ProcessorEvent]:
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
            abort_signal: Optional abort signal (legacy, prefer run_ctx)
            langfuse_context: Optional Langfuse tracing context (legacy, prefer run_ctx)
            run_ctx: Per-invocation RunContext bundling abort_signal, langfuse_context,
                conversation_id, and trace_id. When provided, takes precedence over
                the legacy abort_signal / langfuse_context parameters.

        Yields:
            AgentDomainEvent objects and dict passthrough events for real-time streaming
        """
        # Build effective RunContext: prefer explicit run_ctx, fall back to legacy params
        if run_ctx is None:
            run_ctx = RunContext(
                abort_signal=abort_signal,
                langfuse_context=langfuse_context,
                conversation_id=(langfuse_context or {}).get("conversation_id"),
            )

        self._abort_event = run_ctx.abort_signal or asyncio.Event()
        self._step_count = 0
        self._no_progress_steps = 0
        self._langfuse_context = run_ctx.langfuse_context
        self._artifact_handler.set_langfuse_context(run_ctx.langfuse_context)

        # Emit start event
        yield AgentStartEvent()
        self._state = ProcessorState.THINKING

        try:
            result = ProcessorResult.CONTINUE

            while result == ProcessorResult.CONTINUE:
                abort_event = self._check_abort_and_limits()
                if abort_event is not None:
                    yield abort_event
                    self._state = ProcessorState.ERROR
                    return

                # Process one step and classify events
                had_tool_calls = False
                async for event in self._process_step(session_id, messages):
                    yield event
                    result, had_tool_calls = self._classify_step_event(
                        event, result, had_tool_calls
                    )
                    if result in (ProcessorResult.STOP, ProcessorResult.COMPACT):
                        break

                # Evaluate goal if no tool calls and still continuing
                if result == ProcessorResult.CONTINUE:
                    if had_tool_calls:
                        self._no_progress_steps = 0
                    else:
                        async for evt in self._evaluate_no_tool_result(session_id, messages):
                            yield evt
                        result = self._last_process_result

                # Append tool results to messages for next iteration
                if result == ProcessorResult.CONTINUE:
                    self._append_tool_results_to_messages(messages)

            # Emit completion events
            async for event in self._emit_completion_events(result, session_id, messages):
                yield event

        except Exception as e:
            logger.error(f"Processor error: {e}", exc_info=True)
            yield AgentErrorEvent(message=str(e), code=type(e).__name__)
            self._state = ProcessorState.ERROR

    def _check_abort_and_limits(self) -> AgentErrorEvent | None:
        """Check abort signal and step limits. Returns error event or None."""
        if self._abort_event.is_set():  # type: ignore[union-attr]
            return AgentErrorEvent(message="Processing aborted", code="ABORTED")
        self._step_count += 1
        if self._step_count > self.config.max_steps:
            return AgentErrorEvent(
                message=f"Maximum steps ({self.config.max_steps}) exceeded",
                code="MAX_STEPS_EXCEEDED",
            )
        return None

    def _classify_step_event(
        self,
        event: ProcessorEvent,
        current_result: ProcessorResult,
        had_tool_calls: bool,
    ) -> tuple[ProcessorResult, bool]:
        """Classify a step event and update loop control state."""
        event_type_raw = (
            event.get("type") if isinstance(event, dict) else getattr(event, "event_type", None)
        )
        event_type = (
            event_type_raw.value if isinstance(event_type_raw, AgentEventType) else event_type_raw
        )
        if event_type == AgentEventType.ERROR.value:
            return ProcessorResult.STOP, had_tool_calls
        if event_type == AgentEventType.ACT.value:
            return current_result, True
        if event_type == AgentEventType.COMPACT_NEEDED.value:
            return ProcessorResult.COMPACT, had_tool_calls
        return current_result, had_tool_calls

    async def _evaluate_no_tool_result(
        self, session_id: str, messages: list[dict[str, Any]]
    ) -> AsyncIterator[ProcessorEvent]:
        """Evaluate goal completion when no tools were called.

        Sets self._last_process_result for the caller to read.
        """
        goal_check = await self._goal_evaluator.evaluate_goal_completion(session_id, messages)
        if goal_check.achieved:
            self._no_progress_steps = 0
            yield AgentStatusEvent(status=f"goal_achieved:{goal_check.source}")
            self._last_process_result = ProcessorResult.COMPLETE
            return

        if self._is_conversational_response():
            # Text-only response without tool calls and without an
            # explicit goal_achieved=false signal -- treat as a
            # deliberate conversational reply.
            self._no_progress_steps = 0
            yield AgentStatusEvent(status="goal_achieved:conversational_response")
            self._last_process_result = ProcessorResult.COMPLETE
            return

        if goal_check.should_stop:
            yield AgentErrorEvent(
                message=goal_check.reason or "Goal cannot be completed",
                code="GOAL_NOT_ACHIEVED",
            )
            self._state = ProcessorState.ERROR
            self._last_process_result = ProcessorResult.STOP
            return

        # No progress -- check if we should give up
        self._no_progress_steps += 1
        yield AgentStatusEvent(status=f"goal_pending:{goal_check.source}")
        if self._no_progress_steps > 1:
            yield AgentStatusEvent(status="planning_recheck")
        if self._no_progress_steps >= self.config.max_no_progress_steps:
            yield AgentErrorEvent(
                message=(
                    "Goal not achieved after "
                    f"{self._no_progress_steps} no-progress turns. "
                    f"{goal_check.reason or 'Replan required.'}"
                ),
                code="GOAL_NOT_ACHIEVED",
            )
            self._state = ProcessorState.ERROR
            self._last_process_result = ProcessorResult.STOP
            return
        self._last_process_result = ProcessorResult.CONTINUE

    def _append_tool_results_to_messages(self, messages: list[dict[str, Any]]) -> None:
        """Append current message and tool results to the message list."""
        if not self._current_message:
            return
        messages.append(cast(dict[str, Any], self._current_message.to_llm_format()))
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

    async def _emit_completion_events(
        self,
        result: ProcessorResult,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> AsyncIterator[ProcessorEvent]:
        """Emit final completion or compact events."""
        if result == ProcessorResult.COMPLETE:
            _suggestions = await self._goal_evaluator.generate_suggestions(messages)
            suggestions_event = (
                AgentSuggestionsEvent(suggestions=_suggestions) if _suggestions else None
            )
            if suggestions_event:
                yield suggestions_event
            trace_url = self._build_trace_url(session_id)
            yield AgentCompleteEvent(trace_url=trace_url)
            self._state = ProcessorState.COMPLETED
        elif result == ProcessorResult.COMPACT:
            yield AgentStatusEvent(status="compact_needed")

    def _build_trace_url(self, session_id: str) -> str | None:
        """Build Langfuse trace URL if context is available."""
        if not self._langfuse_context:
            return None
        from src.configuration.config import get_settings

        settings = get_settings()
        if not (settings.langfuse_enabled and settings.langfuse_host):
            return None
        trace_id = self._langfuse_context.get("conversation_id", session_id)
        return f"{settings.langfuse_host}/trace/{trace_id}"

    def _extract_user_query(self, messages: list[dict[str, Any]]) -> str | None:
        """Extract the latest user query from messages."""
        return extract_user_query(messages)

    def _is_conversational_response(self) -> bool:
        """Check if the current turn is a conversational text-only response.

        When the LLM produces substantive text without requesting any tool calls
        and without an explicit goal_achieved=false signal, it has deliberately
        chosen to respond conversationally. This should be treated as
        goal-achieved to avoid unnecessary no-progress loops for simple queries
        like greetings or questions that don't require tool use.
        """
        if not self._current_message:
            return False
        full_text = self._current_message.get_full_text().strip()
        if len(full_text) < 2:
            return False
        # If the text contains a goal_achieved JSON signal, it's a structured
        # goal-check response, not conversational text.
        return "goal_achieved" not in full_text

    def _classify_tool_by_description(self, tool_name: str, tool_def: ToolDefinition) -> str:
        """Classify tool into a category based on its description."""
        return classify_tool_by_description(tool_name, tool_def.description)

    async def _process_step(  # noqa: PLR0912, PLR0915
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> AsyncIterator[ProcessorEvent]:
        """
        Process a single step in the ReAct loop.

        Args:
            session_id: Session identifier
            messages: Current messages

        Yields:
            AgentDomainEvent objects and dict passthrough events
        """
        logger.debug(f"[Processor] _process_step: session={session_id}, step={self._step_count}")

        # Create new assistant message
        self._current_message = Message(
            session_id=session_id,
            role=MessageRole.ASSISTANT,
        )
        self._goal_evaluator.set_current_message(self._current_message)

        # Reset pending tool calls
        self._pending_tool_calls = {}
        self._pending_tool_args = {}

        # Inject skill reminder for multi-step forced skill execution
        if self._forced_skill_name and self._step_count > 1:
            skill_tool_msg = (
                f" Prefer using these tools: {', '.join(sorted(self._forced_skill_tools))}"
                f" for skill-specific operations, but you may use any available tool"
                f" to complete the task."
                if self._forced_skill_tools
                else ""
            )
            skill_reminder = {
                "role": "system",
                "content": (
                    f"[SKILL REMINDER] You are executing forced skill "
                    f'"/{self._forced_skill_name}". '
                    f"Follow the skill instructions from the system prompt precisely."
                    + skill_tool_msg
                ),
            }
            messages.append(skill_reminder)

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

    # ── _execute_tool helper methods ──────────────────────────────────

    def _resolve_tool_lookup(
        self,
        call_id: str,
        tool_name: str,
    ) -> tuple[ToolPart, "ToolDefinition"] | None:
        """Look up ToolPart and ToolDefinition for a tool call.

        Returns ``(tool_part, tool_def)`` on success, or ``None`` when the
        lookup fails.  When ``None`` is returned the caller should yield the
        events stored in ``self.__resolve_errors`` and ``return``.
        """
        self.__resolve_errors = []

        tool_part = self._pending_tool_calls.get(call_id)
        if not tool_part:
            logger.error(
                "[Processor] Tool call not found in pending: call_id=%s, tool=%s",
                call_id,
                tool_name,
            )
            self.__resolve_errors.append(
                AgentObserveEvent(
                    tool_name=tool_name,
                    error=f"Tool call not found: {call_id}",
                    call_id=call_id,
                    tool_execution_id=None,
                )
            )
            return None

        tool_def = self.tools.get(tool_name)
        if not tool_def:
            tool_part.status = ToolState.ERROR
            tool_part.error = f"Unknown tool: {tool_name}"
            tool_part.end_time = time.time()
            self.__resolve_errors.append(
                AgentObserveEvent(
                    tool_name=tool_name,
                    error=f"Unknown tool: {tool_name}",
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )
            )
            return None

        return (tool_part, tool_def)

    async def _check_doom_loop(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        tool_part: ToolPart,
    ) -> AsyncIterator[ProcessorEvent] | None:
        """Check doom-loop detector; return error iterator or ``None`` to proceed."""
        if not self.doom_loop_detector.should_intervene(tool_name, arguments):
            return None

        yield_events: list[ProcessorEvent] = []
        yield_events.append(AgentDoomLoopDetectedEvent(tool=tool_name, input=arguments))
        self._state = ProcessorState.WAITING_PERMISSION

        try:
            permission_result = await asyncio.wait_for(
                self.permission_manager.ask(
                    permission="doom_loop",
                    patterns=[tool_name],
                    session_id=session_id,
                    metadata={"tool": tool_name, "input": arguments},
                ),
                timeout=self.config.permission_timeout,
            )
            if permission_result == "reject":
                tool_part.status = ToolState.ERROR
                tool_part.error = "Doom loop detected and rejected by user"
                tool_part.end_time = time.time()
                yield_events.append(
                    AgentObserveEvent(
                        tool_name=tool_name,
                        error="Doom loop detected and rejected",
                        call_id=call_id,
                        tool_execution_id=tool_part.tool_execution_id,
                    )
                )
                return _iter_events(yield_events)
        except TimeoutError:
            tool_part.status = ToolState.ERROR
            tool_part.error = "Permission request timed out"
            tool_part.end_time = time.time()
            yield_events.append(
                AgentObserveEvent(
                    tool_name=tool_name,
                    error="Permission request timed out",
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )
            )
            return _iter_events(yield_events)

        # Permission granted — emit the doom-loop event only, then proceed
        return None

    def _check_hitl_dispatch(
        self,
        tool_name: str,
    ) -> str | None:
        """Return the HITL handler method name if *tool_name* is a HITL tool, else ``None``."""
        _hitl_map: dict[str, str] = {
            "ask_clarification": "_handle_clarification_tool",
            "request_decision": "_handle_decision_tool",
            "request_env_var": "_handle_env_var_tool",
        }
        return _hitl_map.get(tool_name)

    async def _check_tool_permission(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        tool_part: ToolPart,
        tool_def: "ToolDefinition",
    ) -> AsyncIterator[ProcessorEvent] | None:
        """Check tool permission rules.

        Returns ``None`` to proceed, or an async iterator of error events to
        yield-and-return.
        """
        if not tool_def.permission:
            return None

        permission_rule = self.permission_manager.evaluate(
            permission=tool_def.permission,
            pattern=tool_name,
        )

        if permission_rule.action == PermissionAction.DENY:
            tool_part.status = ToolState.ERROR
            tool_part.error = f"Permission denied: {tool_def.permission}"
            tool_part.end_time = time.time()
            return _iter_events(
                [
                    AgentObserveEvent(
                        tool_name=tool_name,
                        error=f"Permission denied: {tool_def.permission}",
                        call_id=call_id,
                        tool_execution_id=tool_part.tool_execution_id,
                    )
                ]
            )

        if permission_rule.action == PermissionAction.ASK:
            return await self._ask_tool_permission(
                session_id,
                call_id,
                tool_name,
                arguments,
                tool_part,
                tool_def,
            )

        return None

    async def _ask_tool_permission(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        tool_part: ToolPart,
        tool_def: "ToolDefinition",
    ) -> AsyncIterator[ProcessorEvent] | None:
        """Interactive permission request via HITLCoordinator.

        Returns ``None`` when permission is granted, or an async iterator of
        error events to yield-and-return.
        """
        self._state = ProcessorState.WAITING_PERMISSION
        permission = tool_def.permission
        assert permission is not None  # caller guarantees this

        try:
            coordinator = self._get_hitl_coordinator()
            request_data = {
                "tool_name": tool_name,
                "action": "execute",
                "risk_level": "medium",
                "details": {"tool": tool_name, "input": arguments},
                "permission_type": permission,
            }
            request_id = await coordinator.prepare_request(
                hitl_type=HITLType.PERMISSION,
                request_data=request_data,
                timeout_seconds=self.config.permission_timeout,
            )

            # Store the permission-asked event so the orchestrator can yield it
            # *before* blocking on the response.
            self._permission_asked_event = AgentPermissionAskedEvent(
                request_id=request_id,
                permission=permission,
                patterns=[tool_name],
                metadata={"tool": tool_name, "input": arguments},
            )

            permission_granted = await coordinator.wait_for_response(
                request_id=request_id,
                hitl_type=HITLType.PERMISSION,
                timeout_seconds=self.config.permission_timeout,
            )

            if not permission_granted:
                tool_part.status = ToolState.ERROR
                tool_part.error = "Permission rejected by user"
                tool_part.end_time = time.time()
                return _iter_events(
                    [
                        AgentObserveEvent(
                            tool_name=tool_name,
                            error="Permission rejected by user",
                            call_id=call_id,
                            tool_execution_id=tool_part.tool_execution_id,
                        )
                    ]
                )

        except TimeoutError:
            tool_part.status = ToolState.ERROR
            tool_part.error = "Permission request timed out"
            tool_part.end_time = time.time()
            return _iter_events(
                [
                    AgentObserveEvent(
                        tool_name=tool_name,
                        error="Permission request timed out",
                        call_id=call_id,
                        tool_execution_id=tool_part.tool_execution_id,
                    )
                ]
            )
        except ValueError as e:
            logger.warning("[Processor] HITLCoordinator unavailable: %s", e)
            tool_part.status = ToolState.ERROR
            tool_part.error = "Permission request failed: no HITL context"
            tool_part.end_time = time.time()
            return _iter_events(
                [
                    AgentObserveEvent(
                        tool_name=tool_name,
                        error="Permission request failed: no HITL context",
                        call_id=call_id,
                        tool_execution_id=tool_part.tool_execution_id,
                    )
                ]
            )

        return None  # granted

    def _parse_and_fix_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tool_part: ToolPart,
        call_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Validate, fix, and return cleaned arguments.

        Returns the cleaned ``dict`` on success.  Returns ``None`` on
        failure — the caller should yield events from
        ``self.__arg_parse_errors`` and ``return``.
        """
        self.__arg_parse_errors = []

        # Handle truncated arguments
        if "_error" in arguments and arguments.get("_error") == "truncated":
            error_msg = arguments.get(
                "_message",
                "Tool arguments were truncated. The content may be too large.",
            )
            logger.error("[Processor] Tool arguments truncated for %s", tool_name)
            tool_part.status = ToolState.ERROR
            tool_part.error = error_msg
            tool_part.end_time = time.time()
            self.__arg_parse_errors.append(
                AgentObserveEvent(
                    tool_name=tool_name,
                    error=error_msg,
                    call_id=call_id,
                    tool_execution_id=tool_part.tool_execution_id,
                )
            )
            return None

        # Handle _raw arguments (failed JSON parsing in llm_stream)
        if "_raw" in arguments and len(arguments) == 1:
            parsed = self._try_parse_raw_arguments(tool_name, arguments["_raw"])
            if parsed is None:
                raw_preview = arguments["_raw"][:500]
                error_msg = f"Invalid JSON in tool arguments. Raw arguments preview: {raw_preview}"
                logger.error(
                    "[Processor] Failed to parse _raw arguments for %s",
                    tool_name,
                )
                tool_part.status = ToolState.ERROR
                tool_part.error = error_msg
                tool_part.end_time = time.time()
                self.__arg_parse_errors.append(
                    AgentObserveEvent(
                        tool_name=tool_name,
                        error=error_msg,
                        call_id=call_id,
                        tool_execution_id=tool_part.tool_execution_id,
                    )
                )
                return None
            arguments = parsed

        # Inject session_id for todoread/todowrite
        if tool_name in ("todoread", "todowrite") and "session_id" not in arguments:
            arguments["session_id"] = session_id

        return arguments

    @staticmethod
    def _try_parse_raw_arguments(
        tool_name: str,
        raw_args: str,
    ) -> dict[str, Any] | None:
        """Attempt 3-stage recovery of malformed JSON tool arguments.

        Returns the parsed ``dict`` on success, or ``None``.
        """

        def _escape_control_chars(s: str) -> str:
            s = s.replace("\n", "\\n")
            s = s.replace("\r", "\\r")
            s = s.replace("\t", "\\t")
            return s

        logger.warning(
            "[Processor] Attempting to parse _raw arguments for tool %s: %s...",
            tool_name,
            raw_args[:200] if len(raw_args) > 200 else raw_args,
        )

        # Try 1: Direct parse
        try:
            result = json.loads(raw_args)
            logger.info(
                "[Processor] Successfully parsed _raw arguments for %s",
                tool_name,
            )
            return cast(dict[str, Any], result)
        except json.JSONDecodeError:
            pass

        # Try 2: Escape control characters
        try:
            fixed = _escape_control_chars(raw_args)
            result = json.loads(fixed)
            logger.info(
                "[Processor] Parsed _raw arguments after escaping control chars for %s",
                tool_name,
            )
            return cast(dict[str, Any], result)
        except json.JSONDecodeError:
            pass

        # Try 3: Double-encoded JSON
        try:
            if raw_args.startswith('"') and raw_args.endswith('"'):
                inner = raw_args[1:-1]
                inner = inner.replace('\\"', '"').replace("\\\\", "\\")
                result = json.loads(inner)
                logger.info(
                    "[Processor] Parsed double-encoded _raw arguments for %s",
                    tool_name,
                )
                return cast(dict[str, Any], result)
        except json.JSONDecodeError:
            pass

        return None

    async def _invoke_and_emit_observe(  # noqa: PLR0912, PLR0915
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tool_part: ToolPart,
        tool_def: "ToolDefinition",
        call_id: str,
    ) -> AsyncIterator[ProcessorEvent]:
        """Execute the tool and yield AgentObserveEvent + AgentMCPAppResultEvent.

        After this method yields, the caller can access:
        - ``self._last_sse_result`` — the SSE-safe result object
        - ``self._last_raw_result`` — the raw tool result
        - ``self._last_output_str`` — the string output stored on tool_part
        """
        start_time = time.time()
        result = await tool_def.execute(**arguments)
        end_time = time.time()

        # Classify result format
        if isinstance(result, dict) and "artifact" in result:
            artifact = result["artifact"]
            output_str = result.get(
                "output",
                f"Exported artifact: {artifact.get('filename', 'unknown')} "
                f"({artifact.get('mime_type', 'unknown')}, "
                f"{artifact.get('size', 0)} bytes)",
            )
            sse_result: Any = strip_artifact_binary_data(result)
        elif isinstance(result, dict) and "output" in result:
            output_str = result.get("output", "")
            sse_result = result
        elif isinstance(result, str):
            output_str = result
            sse_result = result
        else:
            output_str = json.dumps(result)
            sse_result = result

        # Update tool_part
        tool_part.status = ToolState.COMPLETED
        tool_part.output = self._artifact_handler.sanitize_tool_output(output_str)
        tool_part.end_time = end_time

        # MCP App UI metadata
        tool_instance = getattr(tool_def, "_tool_instance", None)
        has_ui = getattr(tool_instance, "has_ui", False) if tool_instance else False
        if not has_ui and tool_name.startswith("mcp__") and tool_instance:
            _app_id_fb = getattr(tool_instance, "_app_id", "") or ""
            if _app_id_fb:
                has_ui = True
                logger.debug(
                    "[MCPApp] Fallback: tool %s has app_id=%s but no _ui_metadata",
                    tool_name,
                    _app_id_fb,
                )

        _observe_ui_meta: dict[str, Any] | None = None
        _hydrated_ui_meta: dict[str, Any] = {}
        if tool_instance and has_ui:
            _o_app_id = (
                getattr(tool_instance, "_last_app_id", "")
                or getattr(tool_instance, "_app_id", "")
                or ""
            )
            _hydrated_ui_meta = await self._hydrate_mcp_ui_metadata(
                tool_instance=tool_instance,
                app_id=_o_app_id,
                tool_name=tool_name,
            )
            _o_server = getattr(tool_instance, "_server_name", "") or ""
            _o_project_id = (self._langfuse_context or {}).get("project_id", "")
            _observe_ui_meta = {
                "resource_uri": self._extract_mcp_resource_uri(_hydrated_ui_meta),
                "server_name": _o_server,
                "app_id": _o_app_id,
                "title": _hydrated_ui_meta.get("title", ""),
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
            ui_meta = _hydrated_ui_meta or getattr(tool_instance, "ui_metadata", None) or {}
            app_id = (
                getattr(tool_instance, "_last_app_id", "")
                or getattr(tool_instance, "_app_id", "")
                or ""
            )
            if not app_id:
                app_id = f"_synthetic_{tool_name}"
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
                resource_html = getattr(tool_instance, "_last_html", "") or ""
            logger.debug(
                "[MCPApp] Emitting event: tool=%s, app_id=%s, resource_uri=%s, html_len=%d",
                tool_name,
                app_id,
                self._extract_mcp_resource_uri(ui_meta),
                len(resource_html),
            )
            _server_name = getattr(tool_instance, "_server_name", "") or ""
            _project_id = (self._langfuse_context or {}).get("project_id", "")
            _structured_content = None
            if isinstance(sse_result, dict):
                _structured_content = sse_result.get("structuredContent")

            yield AgentMCPAppResultEvent(
                app_id=app_id,
                tool_name=tool_name,
                tool_result=sse_result,
                tool_input=arguments if arguments else None,
                resource_html=resource_html,
                resource_uri=self._extract_mcp_resource_uri(ui_meta),
                ui_metadata=ui_meta,
                tool_execution_id=tool_part.tool_execution_id,
                project_id=_project_id,
                server_name=_server_name,
                structured_content=_structured_content,
            )

        # Stash for downstream side-effect helpers
        self._last_sse_result = sse_result
        self._last_raw_result = result
        self._last_output_str = output_str

    async def _emit_tool_side_effects(  # noqa: PLR0912
        self,
        tool_name: str,
        tool_def: "ToolDefinition",
        tool_part: ToolPart,
        session_id: str,
    ) -> AsyncIterator[ProcessorEvent]:
        """Yield artifact, todowrite, plugin-refresh and pending events."""
        result = self._last_raw_result
        _ = self._last_sse_result  # needed by downstream; alias kept for clarity
        output_str = self._last_output_str

        # Artifacts
        try:
            async for artifact_event in self._artifact_handler.process_tool_artifacts(
                tool_name=tool_name,
                result=result,
                tool_execution_id=tool_part.tool_execution_id,
            ):
                yield artifact_event
        except Exception as artifact_err:
            logger.error(
                "Artifact processing failed for tool %s: %s",
                tool_name,
                artifact_err,
                exc_info=True,
            )

        # Todowrite pending events
        tool_instance = getattr(tool_def, "_tool_instance", None)
        if (
            tool_name == "todowrite"
            and tool_instance
            and hasattr(tool_instance, "consume_pending_events")
        ):
            try:
                pending = tool_instance.consume_pending_events()
                logger.info(
                    "[Processor] todowrite pending events: count=%d, conversation_id=%s",
                    len(pending),
                    session_id,
                )
                if not pending:
                    logger.warning(
                        "[Processor] todowrite produced no pending events "
                        "- tool may have failed silently"
                    )
                async for ev in self._emit_todowrite_events(pending):
                    yield ev
            except Exception as task_err:
                logger.error(
                    "Task event emission failed: %s",
                    task_err,
                    exc_info=True,
                )

        # Plugin/tool refresh + pending events
        refresh_count: int | None = None
        refresh_status = "not_applicable"
        if tool_name in {"plugin_manager", "register_mcp_server"}:
            if isinstance(output_str, str) and not output_str.startswith("Error:"):
                logger.info(
                    "[Processor] %s succeeded, refreshing tools",
                    tool_name,
                )
                refresh_count = self._refresh_tools()
                refresh_status = "success" if refresh_count is not None else "failed"
            else:
                logger.debug(
                    "[Processor] %s failed or returned error, skipping tool refresh",
                    tool_name,
                )
                refresh_status = "skipped"

        _pending_tools = {
            "plugin_manager",
            "register_mcp_server",
            "skill_sync",
            "skill_installer",
            "delegate_to_subagent",
            "parallel_delegate_subagents",
            "sessions_spawn",
            "sessions_send",
            "subagents",
        }
        if (
            tool_name in _pending_tools
            and tool_instance
            and hasattr(tool_instance, "consume_pending_events")
        ):
            try:
                for event in tool_instance.consume_pending_events():
                    if (
                        tool_name in {"plugin_manager", "register_mcp_server"}
                        and isinstance(event, dict)
                        and event.get("type") == "toolset_changed"
                    ):
                        event_data = event.get("data")
                        if isinstance(event_data, dict):
                            event_data.setdefault("refresh_source", "processor")
                            event_data["refresh_status"] = refresh_status
                            if refresh_count is not None:
                                event_data["refreshed_tool_count"] = refresh_count
                    yield event
            except Exception as pending_err:
                logger.error(
                    "%s event emission failed: %s",
                    tool_name,
                    pending_err,
                )

    async def _emit_todowrite_events(
        self,
        pending: list[dict[str, Any]],
    ) -> AsyncIterator[ProcessorEvent]:
        """Convert raw todowrite pending events into typed domain events."""
        from src.domain.events.agent_events import (
            AgentTaskCompleteEvent,
            AgentTaskListUpdatedEvent,
            AgentTaskStartEvent,
            AgentTaskUpdatedEvent,
        )

        for task_event in pending:
            event_type = task_event.get("type")
            if event_type == "task_list_updated":
                tasks = task_event["tasks"]
                logger.info(
                    "[Processor] Emitting task_list_updated: %d tasks for %s",
                    len(tasks),
                    task_event["conversation_id"],
                )
                yield AgentTaskListUpdatedEvent(
                    conversation_id=task_event["conversation_id"],
                    tasks=tasks,
                )
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
                if task_status == "in_progress":
                    total = self._current_task["total_tasks"] if self._current_task else 1
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

    # ── _execute_tool orchestrator ────────────────────────────────────

    async def _execute_tool(  # noqa: PLR0912
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> AsyncIterator[ProcessorEvent]:
        """Execute a tool call (thin orchestrator).

        Delegates to helper methods for each phase:
        1. Resolve tool lookup
        2. Doom-loop check
        3. HITL dispatch (clarification / decision / env_var)
        4. Permission check
        5. Argument parsing & fixing
        6. Tool invocation + observe event emission
        7. Side-effect emission (artifacts, todowrite, plugins)
        """
        # 1. Resolve
        resolved = self._resolve_tool_lookup(call_id, tool_name)
        if resolved is None:
            for ev in self.__resolve_errors:
                yield ev
            return
        tool_part, tool_def = resolved

        # 2. Doom-loop
        doom_result = await self._check_doom_loop(
            session_id,
            call_id,
            tool_name,
            arguments,
            tool_part,
        )
        if doom_result is not None:
            async for ev in doom_result:
                yield ev
            return

        # Record for doom-loop tracking
        self.doom_loop_detector.record(tool_name, arguments)

        # 3. HITL dispatch
        hitl_handler = self._check_hitl_dispatch(tool_name)
        if hitl_handler is not None:
            handler_method = getattr(self, hitl_handler)
            async for ev in handler_method(
                session_id,
                call_id,
                tool_name,
                arguments,
                tool_part,
            ):
                yield ev
            return

        # 4. Permission check
        self._permission_asked_event = None
        perm_result = await self._check_tool_permission(
            session_id,
            call_id,
            tool_name,
            arguments,
            tool_part,
            tool_def,
        )
        # Yield permission-asked event if one was generated
        if self._permission_asked_event is not None:
            yield self._permission_asked_event
            self._permission_asked_event = None
        if perm_result is not None:
            async for ev in perm_result:
                yield ev
            return

        # 5. Parse & fix arguments
        self._state = ProcessorState.ACTING
        cleaned = self._parse_and_fix_arguments(
            tool_name,
            arguments,
            tool_part,
            call_id,
            session_id,
        )
        if cleaned is None:
            for ev in self.__arg_parse_errors:
                yield ev
            return
        arguments = cleaned

        # 6. Invoke tool + emit observe
        try:
            async for ev in self._invoke_and_emit_observe(
                tool_name,
                arguments,
                tool_part,
                tool_def,
                call_id,
            ):
                yield ev

            # 7. Side effects
            async for ev in self._emit_tool_side_effects(
                tool_name,
                tool_def,
                tool_part,
                session_id,
            ):
                yield ev

        except Exception as e:
            logger.error("Tool execution error: %s", e, exc_info=True)
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
    async def _handle_clarification_tool(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
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
        arguments: dict[str, Any],
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
        arguments: dict[str, Any],
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

    def get_session_summary(self) -> dict[str, Any]:
        """Get summary of session costs and tokens."""
        return self.cost_tracker.get_session_summary()


def create_processor(
    model: str,
    tools: list[ToolDefinition],
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs: Any,
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
