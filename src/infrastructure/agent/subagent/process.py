"""SubAgent Process - Independent execution engine for SubAgents.

Each SubAgentProcess creates an isolated ReAct loop with its own:
- Context window (message list)
- Token budget
- Tool set (filtered by SubAgent permissions)
- System prompt
- SessionProcessor instance
- Session-level doom loop detection (catches message-level cycling)

The orchestrator (main agent) delegates a task to a SubAgentProcess
and receives a structured SubAgentResult back.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService
    from src.domain.llm_providers.llm_types import LLMClient
    from src.infrastructure.agent.permission.manager import PermissionManager
    from src.infrastructure.agent.processor.factory import ProcessorFactory

from src.domain.events.agent_events import (
    SubAgentCompletedEvent,
    SubAgentDoomLoopEvent,
    SubAgentFailedEvent,
    SubAgentKilledEvent,
    SubAgentRetryEvent,
    SubAgentStartedEvent,
)
from src.domain.model.agent.subagent import AgentModel, SubAgent
from src.domain.model.agent.subagent_result import SubAgentResult

from ..doom_loop.detector import DoomLoopDetector
from ..processor.run_context import RunContext
from .context_bridge import ContextBridge, SubAgentContext

logger = logging.getLogger(__name__)


class SubAgentProcess:
    """Independent execution process for a SubAgent.

    Creates an isolated SessionProcessor with its own context window,
    runs a full ReAct loop, and returns a structured result.

    Doom loop protection operates at two levels:
    1. **Tool-level** (via SessionProcessor's built-in DoomLoopDetector):
       Detects repeated identical tool calls within a single ReAct loop.
    2. **Session-level** (this class): Detects when the SubAgent's
       text output becomes repetitive across steps, indicating the
       agent is cycling at the message level even if tool calls vary.

    Usage:
        process = SubAgentProcess(
            subagent=my_subagent,
            context=subagent_context,
            tools=filtered_tools,
            base_model="qwen-max",
        )
        async for event in process.execute():
            yield event  # forward SSE events
        result = process.result
    """

    def __init__(
        self,
        subagent: SubAgent,
        context: SubAgentContext,
        tools: list[Any],
        base_model: str = "",
        base_api_key: str | None = None,
        base_url: str | None = None,
        llm_client: LLMClient | None = None,
        permission_manager: PermissionManager | None = None,
        artifact_service: ArtifactService | None = None,
        abort_signal: asyncio.Event | None = None,
        factory: ProcessorFactory | None = None,
        doom_loop_threshold: int = 3,
    ) -> None:
        """Initialize a SubAgent process.

        Args:
            subagent: The SubAgent definition.
            context: Condensed context from ContextBridge.
            tools: Filtered tool definitions for this SubAgent.
            base_model: Base model name (used if SubAgent inherits). Legacy.
            base_api_key: API key for LLM calls. Legacy.
            base_url: Base URL for LLM API. Legacy.
            llm_client: Shared LLM client instance. Legacy.
            permission_manager: Permission manager for tool access. Legacy.
            artifact_service: Artifact service for rich outputs. Legacy.
            abort_signal: Signal to abort execution.
            factory: ProcessorFactory with shared deps. Preferred over individual params.
            doom_loop_threshold: Threshold for session-level doom loop detection.
                Detects repetitive text output across steps. Default: 3.

        Note:
            Retry configuration (max_retries, fallback_models) is read from
            the SubAgent entity. Default max_retries=0 means no retry.
        """
        self._subagent = subagent
        self._context = context
        self._tools = tools
        self._abort_signal = abort_signal
        self._factory = factory
        self._doom_loop_threshold = doom_loop_threshold
        self._max_retries: int = getattr(subagent, "max_retries", 0)
        fallback_models: list[str] = getattr(subagent, "fallback_models", [])
        self._fallback_models = fallback_models or []

        # Session-level doom loop detector: catches repetitive text output
        # across processor steps (complements processor's tool-level detector).
        self._session_doom_detector = DoomLoopDetector(
            threshold=doom_loop_threshold,
            window_size=doom_loop_threshold * 3,
        )

        # Legacy individual deps (used when factory is not provided)
        self._llm_client = llm_client
        self._permission_manager = permission_manager
        self._artifact_service = artifact_service

        # Determine actual model
        if subagent.model == AgentModel.INHERIT:
            self._model = base_model
        else:
            self._model = subagent.model.value

        self._api_key = base_api_key
        self._base_url = base_url
        # Execution state
        self._result: SubAgentResult | None = None
        self._final_content = ""
        self._tool_calls_count = 0
        self._tokens_used = 0
        self._current_step_text = ""

    @property
    def result(self) -> SubAgentResult | None:
        """Get the execution result (available after execute completes)."""
        return self._result

    async def execute(self) -> AsyncIterator[dict[str, Any]]:
        """Execute the SubAgent in an independent ReAct loop.

        Supports retry with model fallback when max_retries > 0.
        Retries are only attempted when no tool calls were made during
        the failed attempt (to avoid repeating side effects).

        Yields SSE events prefixed with subagent metadata.
        After completion, self.result is populated.

        Yields:
            Dict events with subagent_id for frontend routing.
        """
        start_time = time.time()
        success = True
        error_msg: str | None = None
        last_attempt = 0

        for attempt in range(1 + self._max_retries):
            last_attempt = attempt
            current_model = self._get_model_for_attempt(attempt)

            if attempt > 0:
                self._reset_execution_state()

            processor = self._build_processor(
                model_override=current_model if attempt > 0 else None,
            )

            # Build independent message list from context
            bridge = ContextBridge()
            messages = bridge.build_messages(self._context)

            # Emit subagent_started event (only on first attempt)
            if attempt == 0:
                yield dict(
                    SubAgentStartedEvent(
                        subagent_id=self._subagent.id,
                        subagent_name=self._subagent.display_name,
                        task=self._context.task_description[:200],
                        model=current_model,
                    ).to_event_dict()
                )

            success = True
            error_msg = None
            attempt_had_doom_loop = False

            try:
                # Run the independent ReAct loop
                session_id = f"subagent-{self._subagent.id}-{int(time.time())}"

                run_ctx = RunContext(
                    abort_signal=self._abort_signal,
                    conversation_id=f"subagent-{self._subagent.id}",
                    trace_id=session_id,
                )

                async for domain_event in processor.process(
                    session_id=session_id,
                    messages=messages,
                    run_ctx=run_ctx,
                ):
                    # Convert and relay events with subagent prefix
                    event = self._relay_event(domain_event)
                    if event:
                        self._track_event_metrics(event)

                        # Session-level doom loop check on text boundaries
                        doom_result = self._check_session_doom_loop(event)
                        if doom_result is not None:
                            yield doom_result
                            success = False
                            error_msg = (
                                "Session-level doom loop: SubAgent produced repetitive output"
                            )
                            attempt_had_doom_loop = True
                            break

                        yield event

            except Exception as e:
                if isinstance(e, asyncio.CancelledError):
                    yield dict(
                        SubAgentKilledEvent(
                            subagent_id=self._subagent.id,
                            subagent_name=self._subagent.display_name,
                            kill_reason="Cancelled during execution",
                        ).to_event_dict()
                    )
                logger.error(
                    f"[SubAgentProcess] Error in {self._subagent.name} "
                    f"(attempt {attempt + 1}/{1 + self._max_retries}): {e}",
                    exc_info=True,
                )
                success = False
                error_msg = str(e)

            # Decide whether to retry
            if not success and self._should_retry(attempt, attempt_had_doom_loop):
                next_model = self._get_model_for_attempt(attempt + 1)
                yield dict(
                    SubAgentRetryEvent(
                        subagent_id=self._subagent.id,
                        subagent_name=self._subagent.display_name,
                        attempt=attempt + 1,
                        max_retries=self._max_retries,
                        model=next_model,
                        reason=error_msg or "Unknown error",
                    ).to_event_dict()
                )

                # Exponential backoff: 1s, 2s, 4s, capped at 8s
                backoff = min(2**attempt, 8)
                await asyncio.sleep(backoff)
                continue

            # Success or non-retriable failure: stop the loop
            break

        # --- Post-loop finalization (runs once) ---
        async for event in self._finalize_execution(start_time, success, error_msg, last_attempt):
            yield event

    async def _finalize_execution(
        self,
        start_time: float,
        success: bool,
        error_msg: str | None,
        last_attempt: int,
    ) -> AsyncIterator[dict[str, Any]]:
        """Finalize execution: build result, emit completion events.

        Extracted from execute() to keep statement count within limits.
        """
        end_time = time.time()
        execution_time_ms = int((end_time - start_time) * 1000)

        # Build summary from final content
        summary = self._extract_summary(self._final_content)

        # Build result
        self._result = SubAgentResult(
            subagent_id=self._subagent.id,
            subagent_name=self._subagent.display_name,
            summary=summary,
            success=success,
            tool_calls_count=self._tool_calls_count,
            tokens_used=self._tokens_used,
            execution_time_ms=execution_time_ms,
            final_content=self._final_content,
            error=error_msg,
        )

        # Record execution stats on the SubAgent
        self._subagent.record_execution(execution_time_ms, success)

        # Emit failure event if we exhausted retries and still failed
        if not success:
            yield dict(
                SubAgentFailedEvent(
                    subagent_id=self._subagent.id,
                    subagent_name=self._subagent.display_name,
                    error=error_msg or "Unknown error",
                ).to_event_dict()
            )

        # Emit subagent_completed event
        yield dict(
            SubAgentCompletedEvent(
                subagent_id=self._subagent.id,
                subagent_name=self._subagent.display_name,
                success=success,
                summary=summary,
                tool_calls_count=self._tool_calls_count,
                tokens_used=self._tokens_used,
                execution_time_ms=execution_time_ms,
                error=error_msg,
                final_content=self._final_content,
            ).to_event_dict()
        )

        logger.info(
            f"[SubAgentProcess] {self._subagent.name} completed: "
            f"success={success}, tools={self._tool_calls_count}, "
            f"time={execution_time_ms}ms, attempts={last_attempt + 1}"
        )

    def _build_processor(self, model_override: str | None = None) -> Any:
        """Build a SessionProcessor for this SubAgent.

        Args:
            model_override: If provided, overrides the SubAgent's configured model.
                Used during retry attempts to switch to fallback models.
        """
        if self._factory is not None:
            return self._factory.create_for_subagent(
                subagent=self._subagent,
                tools=self._tools,
                doom_loop_threshold=self._doom_loop_threshold,
                model_override=model_override,
            )
        # Legacy path: manual construction from individual params
        from ..core.processor import ProcessorConfig, SessionProcessor

        effective_model = model_override or self._model
        config = ProcessorConfig(
            model=effective_model,
            api_key=self._api_key,
            base_url=self._base_url,
            temperature=self._subagent.temperature,
            max_tokens=self._subagent.max_tokens,
            max_steps=self._subagent.max_iterations,
            llm_client=self._llm_client,
        )
        return SessionProcessor(
            config=config,
            tools=self._tools,
            permission_manager=self._permission_manager,
            artifact_service=self._artifact_service,
        )

    def _reset_execution_state(self) -> None:
        """Reset mutable state between retry attempts."""
        self._final_content = ""
        self._tool_calls_count = 0
        self._tokens_used = 0
        self._current_step_text = ""
        self._session_doom_detector = DoomLoopDetector(
            threshold=self._doom_loop_threshold,
            window_size=self._doom_loop_threshold * 3,
        )

    def _get_model_for_attempt(self, attempt: int) -> str:
        """Get model name for the given retry attempt (0-indexed).

        Attempt 0 always uses the original model. Subsequent attempts
        cycle through fallback_models. If no fallback_models configured,
        retries use the original model.
        """
        if attempt == 0 or not self._fallback_models:
            return self._model
        idx = (attempt - 1) % len(self._fallback_models)
        return self._fallback_models[idx]

    def _should_retry(self, attempt: int, had_doom_loop: bool) -> bool:
        """Determine if the current failure should be retried.

        Retries are blocked when:
        - All retry attempts are exhausted
        - Tool calls were made (side effects may have occurred)
        - Doom loop detected (retrying would likely repeat the loop)
        """
        if attempt >= self._max_retries:
            return False
        if self._tool_calls_count > 0:
            logger.info(
                "[SubAgentProcess] Skipping retry for %s: "
                "%d tool calls were made (side-effect safety)",
                self._subagent.name,
                self._tool_calls_count,
            )
            return False
        if had_doom_loop:
            logger.info(
                "[SubAgentProcess] Skipping retry for %s: doom loop detected",
                self._subagent.name,
            )
            return False
        return True

    def _track_event_metrics(self, event: dict[str, Any]) -> None:
        """Update internal metrics from a relayed event."""
        event_type = event.get("type", "")
        if event_type == "subagent.text_delta":
            delta = event.get("data", {}).get("delta", "")
            self._final_content += delta
            self._current_step_text += delta
        elif event_type == "subagent.text_end":
            text = event.get("data", {}).get("full_text", "")
            if text:
                self._final_content = text
                self._current_step_text = text
        elif event_type == "subagent.act":
            self._tool_calls_count += 1

    def _check_session_doom_loop(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Check for session-level doom loop on text_end boundaries.

        Returns a doom-loop event dict if intervention is needed,
        or None if everything is fine.
        """
        if event.get("type") != "subagent.text_end":
            return None

        step_text = self._current_step_text.strip()
        if not step_text:
            self._current_step_text = ""
            return None

        if self._session_doom_detector.should_intervene("text_output", step_text):
            logger.warning(
                "[SubAgentProcess] Session-level doom loop detected in %s: repetitive text output",
                self._subagent.name,
            )
            self._current_step_text = ""
            return dict(
                SubAgentDoomLoopEvent(
                    subagent_id=self._subagent.id,
                    subagent_name=self._subagent.display_name,
                    reason="Repetitive text output detected",
                    threshold=self._doom_loop_threshold,
                ).to_event_dict()
            )

        self._session_doom_detector.record("text_output", step_text)
        self._current_step_text = ""
        return None

    def _relay_event(self, domain_event: Any) -> dict[str, Any] | None:
        """Convert a domain event to a prefixed SSE event.

        Adds subagent metadata and prefixes the event type.

        Args:
            domain_event: AgentDomainEvent from the processor.

        Returns:
            Dict event with subagent prefix, or None to skip.
        """
        if isinstance(domain_event, dict):
            event_dict = domain_event
        elif hasattr(domain_event, "to_event_dict"):
            event_dict = domain_event.to_event_dict()
        else:
            return None
        original_type = event_dict.get("type", "unknown")

        # Prefix with subagent namespace
        return {
            "type": f"subagent.{original_type}",
            "data": {
                **event_dict.get("data", {}),
                "subagent_id": self._subagent.id,
                "subagent_name": self._subagent.display_name,
            },
            "timestamp": event_dict.get("timestamp", datetime.now(UTC).isoformat()),
        }

    def _make_event(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Create an SSE event dict."""
        return {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def _extract_summary(self, content: str, max_length: int = 500) -> str:
        """Extract a concise summary from the SubAgent's output.

        For Phase 1, uses simple truncation. Phase 2+ can upgrade
        to LLM-based summarization.

        Args:
            content: Full text output from the SubAgent.
            max_length: Maximum summary length in characters.

        Returns:
            Concise summary string.
        """
        if not content:
            return "No output produced."

        content = content.strip()

        if len(content) <= max_length:
            return content

        # Truncate at the last sentence boundary within the limit
        truncated = content[:max_length]
        last_period = truncated.rfind(".")
        last_newline = truncated.rfind("\n")
        cut_point = max(last_period, last_newline)

        if cut_point > max_length // 2:
            return truncated[: cut_point + 1].strip()

        return truncated.strip() + "..."
