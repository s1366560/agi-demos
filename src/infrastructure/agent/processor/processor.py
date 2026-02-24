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
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional, cast

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


from src.domain.model.agent.hitl_types import HITLType

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
_processor_bg_tasks: set[asyncio.Task[Any]] = set()


def _strip_artifact_binary_data(result: dict[str, Any]) -> dict[str, Any]:
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
_CANVAS_MIME_MAP: dict[str, str] = {
    "text/html": "preview",
    "text/markdown": "markdown",
    "text/csv": "data",
    "application/json": "data",
    "application/xml": "data",
    "text/xml": "data",
}


def _get_canvas_content_type(mime_type: str, filename: str) -> str | None:
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


_LANG_EXT_MAP: dict[str, str] = {
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


def _get_language_from_filename(filename: str) -> str | None:
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


@dataclass
class GoalCheckResult:
    """Result of goal completion evaluation."""

    achieved: bool
    should_stop: bool = False
    reason: str = ""
    source: str = "unknown"
    pending_tasks: int = 0


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
            if new_tools is None:
                logger.warning("[Processor] tool_provider returned None, skipping refresh")  # type: ignore[unreachable]
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
            abort_signal: Optional abort signal
            langfuse_context: Optional context for Langfuse tracing containing:
                - conversation_id: Unique conversation identifier
                - user_id: User identifier
                - tenant_id: Tenant identifier for multi-tenant isolation
                - project_id: Project identifier
                - extra: Additional metadata dict

        Yields:
            AgentDomainEvent objects and dict passthrough events for real-time streaming
        """
        self._abort_event = abort_signal or asyncio.Event()
        self._step_count = 0
        self._no_progress_steps = 0
        self._langfuse_context = langfuse_context  # Store for use in _process_step

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
                        async for evt in self._evaluate_no_tool_result(
                            session_id, messages
                        ):
                            yield evt
                        result = self._last_process_result

                # Append tool results to messages for next iteration
                if result == ProcessorResult.CONTINUE:
                    self._append_tool_results_to_messages(messages)

            # Emit completion events
            async for event in self._emit_completion_events(
                result, session_id, messages
            ):
                yield event

        except Exception as e:
            logger.error(f"Processor error: {e}", exc_info=True)
            yield AgentErrorEvent(message=str(e), code=type(e).__name__)
            self._state = ProcessorState.ERROR

    def _check_abort_and_limits(self) -> AgentErrorEvent | None:
        """Check abort signal and step limits. Returns error event or None."""
        if self._abort_event.is_set():
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
            event.get("type")
            if isinstance(event, dict)
            else getattr(event, "event_type", None)
        )
        event_type = (
            event_type_raw.value
            if isinstance(event_type_raw, AgentEventType)
            else event_type_raw
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
        goal_check = await self._evaluate_goal_completion(session_id, messages)
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

    def _append_tool_results_to_messages(
        self, messages: list[dict[str, Any]]
    ) -> None:
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
            suggestions_event = await self._generate_suggestions(messages)
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

    async def _evaluate_goal_completion(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> GoalCheckResult:
        """Evaluate whether the current goal is complete."""
        tasks = await self._load_session_tasks(session_id)
        if tasks:
            return self._evaluate_task_goal(tasks)
        return await self._evaluate_llm_goal(messages)

    async def _load_session_tasks(self, session_id: str) -> list[dict[str, Any]]:
        """Load tasks for the session via todoread when available."""
        todoread_tool = self.tools.get("todoread")
        if todoread_tool is None:
            return []

        try:
            raw_result = await todoread_tool.execute(session_id=session_id)
        except Exception as exc:
            logger.warning(f"[Processor] Failed to load tasks via todoread: {exc}")
            return []

        payload: dict[str, Any]
        if isinstance(raw_result, str):
            try:
                payload = json.loads(raw_result)
            except json.JSONDecodeError as exc:
                logger.warning(f"[Processor] Invalid todoread JSON result: {exc}")
                return []
        elif isinstance(raw_result, dict):
            payload = raw_result
        else:
            logger.warning(
                f"[Processor] Unsupported todoread result type: {type(raw_result).__name__}"
            )
            return []

        tasks = payload.get("todos", [])
        if not isinstance(tasks, list):
            logger.warning("[Processor] todoread payload missing list field 'todos'")
            return []

        return [t for t in tasks if isinstance(t, dict)]

    def _evaluate_task_goal(self, tasks: list[dict[str, Any]]) -> GoalCheckResult:
        """Evaluate completion from persisted task state."""
        pending_count = 0
        failed_count = 0

        for task in tasks:
            status = str(task.get("status", "")).strip().lower()
            if status in {"pending", "in_progress"}:
                pending_count += 1
            elif status == "failed":
                failed_count += 1
            elif status not in {"completed", "cancelled"}:
                pending_count += 1

        if pending_count > 0:
            return GoalCheckResult(
                achieved=False,
                reason=f"{pending_count} task(s) still in progress",
                source="tasks",
                pending_tasks=pending_count,
            )
        if failed_count > 0:
            return GoalCheckResult(
                achieved=False,
                should_stop=True,
                reason=f"{failed_count} task(s) failed",
                source="tasks",
            )
        return GoalCheckResult(
            achieved=True,
            reason="All tasks reached terminal success states",
            source="tasks",
        )

    async def _evaluate_llm_goal(self, messages: list[dict[str, Any]]) -> GoalCheckResult:
        """Evaluate completion using explicit LLM self-check in no-task mode."""
        fallback = self._evaluate_goal_from_latest_text()
        if self._llm_client is None:
            return fallback

        context_summary = self._build_goal_check_context(messages)
        if not context_summary:
            return fallback

        content = await self._call_goal_check_llm(context_summary)
        if content is None:
            return fallback

        parsed = self._extract_goal_json(content)
        if parsed is None:
            parsed = self._extract_goal_from_plain_text(content)
        if parsed is None:
            logger.debug(
                "[Processor] Goal self-check payload not parseable, using fallback: %s",
                content[:200],
            )
            return fallback

        achieved = self._coerce_goal_achieved_bool(parsed.get("goal_achieved"))
        if achieved is None:
            logger.debug("[Processor] Goal self-check missing boolean goal_achieved")
            return fallback

        reason = str(parsed.get("reason", "")).strip()
        return GoalCheckResult(
            achieved=achieved,
            reason=reason or ("Goal achieved" if achieved else "Goal not achieved"),
            source="llm_self_check",
        )

    async def _call_goal_check_llm(self, context_summary: str) -> str | None:
        """Call LLM for goal check and return content string, or None on failure."""
        try:
            response = await self._llm_client.generate(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a strict completion checker. "
                            "Return ONLY JSON object: "
                            '{"goal_achieved": boolean, "reason": string}. '
                            "Use goal_achieved=true only when user objective is fully satisfied."
                        ),
                    },
                    {"role": "user", "content": context_summary},
                ],
                temperature=0.0,
                max_tokens=120,
            )
        except Exception as exc:
            logger.warning(f"[Processor] LLM goal self-check failed: {exc}")
            return None

        if isinstance(response, dict):
            return str(response.get("content", "") or "")
        if isinstance(response, str):
            return response
        return str(response)

    @staticmethod
    def _coerce_goal_achieved_bool(value: Any) -> bool | None:
        """Coerce a goal_achieved value to bool, or return None if not possible."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "1"}:
                return True
            if lowered in {"false", "no", "0"}:
                return False
        return None

    def _extract_goal_from_plain_text(self, text: str) -> dict[str, Any] | None:
        """Parse non-JSON goal-check payloads from plain text."""
        normalized = text.strip()
        if not normalized:
            return None
        normalized = normalized[:2000]

        # Example: goal_achieved: false
        bool_match = re.search(
            r"\bgoal[_\s-]*achieved\b\s*[:=]\s*(true|false|yes|no|1|0)\b",
            normalized,
            flags=re.IGNORECASE,
        )
        if bool_match:
            bool_token = bool_match.group(1).strip().lower()
            achieved = bool_token in {"true", "yes", "1"}
            reason_match = re.search(
                r"\breason\b\s*[:=]\s*([^\n\r]{1,500})",
                normalized,
                flags=re.IGNORECASE,
            )
            reason = reason_match.group(1).strip() if reason_match else normalized[:200]
            return {"goal_achieved": achieved, "reason": reason}

        lowered = normalized.lower()
        if "goal not achieved" in lowered or "goal is not achieved" in lowered:
            return {"goal_achieved": False, "reason": normalized[:200]}
        if ("goal achieved" in lowered or "goal is achieved" in lowered) and not re.search(
            r"\b(not|still|remaining|in progress|incomplete|partial)\b",
            lowered,
        ):
            return {"goal_achieved": True, "reason": normalized[:200]}
        return None

    def _evaluate_goal_from_latest_text(self) -> GoalCheckResult:
        """Fallback goal check from latest assistant text."""
        if not self._current_message:
            return GoalCheckResult(
                achieved=False,
                reason="No assistant output available for goal check",
                source="assistant_text",
            )

        full_text = self._current_message.get_full_text().strip()
        if not full_text:
            return GoalCheckResult(
                achieved=False,
                reason="Assistant output is empty",
                source="assistant_text",
            )

        parsed = self._extract_goal_json(full_text)
        if parsed and isinstance(parsed.get("goal_achieved"), bool):
            achieved = bool(parsed["goal_achieved"])
            reason = str(parsed.get("reason", "")).strip()
            return GoalCheckResult(
                achieved=achieved,
                reason=reason or ("Goal achieved" if achieved else "Goal not achieved"),
                source="assistant_text",
            )

        if self._has_explicit_completion_phrase(full_text):
            return GoalCheckResult(
                achieved=True,
                reason="Assistant declared completion in final response",
                source="assistant_text",
            )

        return GoalCheckResult(
            achieved=False,
            reason="No explicit goal_achieved signal in assistant response",
            source="assistant_text",
        )

    def _build_goal_check_context(self, messages: list[dict[str, Any]]) -> str:
        """Build a compact context summary for goal self-check."""
        summary_lines: list[str] = []
        recent_messages = messages[-8:] if len(messages) > 8 else messages
        for msg in recent_messages:
            role = str(msg.get("role", "unknown"))
            content = msg.get("content", "")

            if isinstance(content, list):
                text_chunks = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_chunks.append(str(part.get("text", "")))
                content_text = " ".join(chunk for chunk in text_chunks if chunk).strip()
            elif isinstance(content, str):
                content_text = content.strip()
            else:
                content_text = str(content).strip() if content else ""

            if content_text:
                summary_lines.append(f"{role}: {content_text[:400]}")

        if self._current_message:
            latest_text = self._current_message.get_full_text().strip()
            if latest_text:
                summary_lines.append(f"assistant_latest: {latest_text[:400]}")

        return "\n".join(summary_lines)

    @staticmethod
    def _find_json_object_end(text: str, start_idx: int) -> int | None:
        """Find the end index (inclusive) of a balanced JSON object.

        Scans from start_idx (which must be a '{') tracking brace depth
        and string escaping. Returns the index of the closing '}' or None.
        """
        depth = 0
        in_string = False
        escape_next = False
        for index in range(start_idx, len(text)):
            char = text[index]

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
                    return index
        return None

    @staticmethod
    def _try_parse_json_dict(text: str) -> dict[str, Any] | None:
        """Try to parse text as a JSON dict. Returns dict or None."""
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
        return None

    def _extract_goal_json(self, text: str) -> dict[str, Any] | None:
        """Extract goal-check JSON object from model text."""
        stripped = text.strip()
        if not stripped:
            return None

        result = self._try_parse_json_dict(stripped)
        if result is not None:
            return result

        start_idx = stripped.find("{")
        while start_idx >= 0:
            end_idx = self._find_json_object_end(stripped, start_idx)
            if end_idx is not None:
                candidate = stripped[start_idx : end_idx + 1]
                result = self._try_parse_json_dict(candidate)
                if result is not None:
                    return result
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

    async def _generate_suggestions(
        self, messages: list[dict[str, Any]]
    ) -> AgentSuggestionsEvent | None:
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
        arguments: dict[str, Any],
    ) -> AsyncIterator[ProcessorEvent]:
        """
        Execute a tool call with permission checking and doom loop detection.

        Args:
            session_id: Session identifier
            call_id: Tool call ID
            tool_name: Name of tool to execute
            arguments: Tool arguments

        Yields:
            AgentDomainEvent objects and dict passthrough events for tool execution
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

            except TimeoutError:
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
                # Request permission via HITLCoordinator for proper response routing
                self._state = ProcessorState.WAITING_PERMISSION

                try:
                    coordinator = self._get_hitl_coordinator()

                    # Prepare permission request data
                    request_data = {
                        "tool_name": tool_name,
                        "action": "execute",
                        "risk_level": "medium",
                        "details": {"tool": tool_name, "input": arguments},
                        "permission_type": tool_def.permission,
                    }

                    # Prepare the request (registers in global coordinator registry)
                    request_id = await coordinator.prepare_request(
                        hitl_type=HITLType.PERMISSION,
                        request_data=request_data,
                        timeout_seconds=self.config.permission_timeout,
                    )

                    # Yield permission asked event with the real request_id
                    yield AgentPermissionAskedEvent(
                        request_id=request_id,
                        permission=tool_def.permission,
                        patterns=[tool_name],
                        metadata={"tool": tool_name, "input": arguments},
                    )

                    # Wait for user response via HITLCoordinator
                    # This uses the global registry so responses from
                    # LocalHITLResumeConsumer can reach us
                    permission_granted = await coordinator.wait_for_response(
                        request_id=request_id,
                        hitl_type=HITLType.PERMISSION,
                        timeout_seconds=self.config.permission_timeout,
                    )

                    if not permission_granted:
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

                except TimeoutError:
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
                except ValueError as e:
                    # HITLCoordinator not available (no langfuse context)
                    logger.warning(f"[Processor] HITLCoordinator unavailable: {e}")
                    tool_part.status = ToolState.ERROR
                    tool_part.error = "Permission request failed: no HITL context"
                    tool_part.end_time = time.time()

                    yield AgentObserveEvent(
                        tool_name=tool_name,
                        error="Permission request failed: no HITL context",
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
                def escape_control_chars(s: str) -> str:
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
                sse_result: Any = _strip_artifact_binary_data(result)
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
                    self._extract_mcp_resource_uri(ui_meta),
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
                    resource_uri=self._extract_mcp_resource_uri(ui_meta),
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

            # Emit pending SSE events from tools that support event buffering
            refresh_count: int | None = None
            refresh_status = "not_applicable"
            if tool_name in {"plugin_manager", "register_mcp_server"}:
                if isinstance(output_str, str) and not output_str.startswith("Error:"):
                    logger.info("[Processor] %s succeeded, refreshing tools", tool_name)
                    refresh_count = self._refresh_tools()
                    refresh_status = "success" if refresh_count is not None else "failed"
                else:
                    logger.debug(
                        "[Processor] %s failed or returned error, skipping tool refresh",
                        tool_name,
                    )
                    refresh_status = "skipped"

            if (
                tool_name
                in {
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
                    logger.error(f"{tool_name} event emission failed: {pending_err}")

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
        tool_execution_id: str | None = None,
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
                ) -> dict[str, Any]:
                    """Synchronous S3 upload in a thread pool."""
                    from datetime import date
                    from urllib.parse import quote

                    import boto3
                    from botocore.config import Config as BotoConfig

                    config_kwargs: dict[str, Any] = {
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
                ) -> None:
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
                            endpoint=settings.s3_endpoint_url or "",
                            access_key=settings.aws_access_key_id or "",
                            secret_key=settings.aws_secret_access_key or "",
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
                            event=cast(dict[str, Any], ready_event_dict),
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
                                event=cast(dict[str, Any], error_event_dict),
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

                _upload_task = asyncio.create_task(
                    _threaded_upload(
                        content=file_content,
                        fname=filename,
                        pid=project_id,
                        tid=tenant_id,
                        texec_id=tool_execution_id or "",
                        conv_id=conversation_id or "",
                        msg_id=message_id or "",
                        tname=tool_name,
                        art_id=artifact_id,
                        mime=mime_type,
                        cat=category.value,
                    )
                )
                _processor_bg_tasks.add(_upload_task)
                _upload_task.add_done_callback(_processor_bg_tasks.discard)
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
