"""SubAgent Process - Independent execution engine for SubAgents.

Each SubAgentProcess creates an isolated ReAct loop with its own:
- Context window (message list)
- Token budget
- Tool set (filtered by SubAgent permissions)
- System prompt
- SessionProcessor instance

The orchestrator (main agent) delegates a task to a SubAgentProcess
and receives a structured SubAgentResult back.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

from src.domain.model.agent.subagent import AgentModel, SubAgent
from src.domain.model.agent.subagent_result import SubAgentResult

from .context_bridge import ContextBridge, SubAgentContext

logger = logging.getLogger(__name__)


class SubAgentProcess:
    """Independent execution process for a SubAgent.

    Creates an isolated SessionProcessor with its own context window,
    runs a full ReAct loop, and returns a structured result.

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
        tools: List[Any],
        base_model: str,
        base_api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        llm_client: Optional[Any] = None,
        permission_manager: Optional[Any] = None,
        artifact_service: Optional[Any] = None,
        abort_signal: Optional[asyncio.Event] = None,
    ) -> None:
        """Initialize a SubAgent process.

        Args:
            subagent: The SubAgent definition.
            context: Condensed context from ContextBridge.
            tools: Filtered tool definitions for this SubAgent.
            base_model: Base model name (used if SubAgent inherits).
            base_api_key: API key for LLM calls.
            base_url: Base URL for LLM API.
            llm_client: Shared LLM client instance.
            permission_manager: Permission manager for tool access.
            artifact_service: Artifact service for rich outputs.
            abort_signal: Signal to abort execution.
        """
        self._subagent = subagent
        self._context = context
        self._tools = tools
        self._llm_client = llm_client
        self._permission_manager = permission_manager
        self._artifact_service = artifact_service
        self._abort_signal = abort_signal

        # Determine actual model
        if subagent.model == AgentModel.INHERIT:
            self._model = base_model
        else:
            self._model = subagent.model.value

        self._api_key = base_api_key
        self._base_url = base_url

        # Execution state
        self._result: Optional[SubAgentResult] = None
        self._final_content = ""
        self._tool_calls_count = 0
        self._tokens_used = 0

    @property
    def result(self) -> Optional[SubAgentResult]:
        """Get the execution result (available after execute completes)."""
        return self._result

    async def execute(self) -> AsyncIterator[Dict[str, Any]]:
        """Execute the SubAgent in an independent ReAct loop.

        Yields SSE events prefixed with subagent metadata.
        After completion, self.result is populated.

        Yields:
            Dict events with subagent_id for frontend routing.
        """
        # Lazy import to avoid circular dependencies
        from ..core.processor import ProcessorConfig, SessionProcessor

        start_time = time.time()
        success = True
        error_msg: Optional[str] = None

        # Build processor config from SubAgent settings
        config = ProcessorConfig(
            model=self._model,
            api_key=self._api_key,
            base_url=self._base_url,
            temperature=self._subagent.temperature,
            max_tokens=self._subagent.max_tokens,
            max_steps=self._subagent.max_iterations,
            llm_client=self._llm_client,
        )

        # Build independent message list from context
        bridge = ContextBridge()
        messages = bridge.build_messages(self._context)

        # Create an isolated SessionProcessor
        processor = SessionProcessor(
            config=config,
            tools=self._tools,
            permission_manager=self._permission_manager,
            artifact_service=self._artifact_service,
        )

        # Emit subagent_started event
        yield self._make_event("subagent_started", {
            "subagent_id": self._subagent.id,
            "subagent_name": self._subagent.display_name,
            "task": self._context.task_description[:200],
            "model": self._model,
        })

        try:
            # Run the independent ReAct loop
            session_id = f"subagent-{self._subagent.id}-{int(time.time())}"

            async for domain_event in processor.process(
                session_id=session_id,
                messages=messages,
                abort_signal=self._abort_signal,
            ):
                # Convert and relay events with subagent prefix
                event = self._relay_event(domain_event)
                if event:
                    # Track metrics from relayed events
                    event_type = event.get("type", "")
                    if event_type == "subagent.text_delta":
                        self._final_content += event.get("data", {}).get("delta", "")
                    elif event_type == "subagent.text_end":
                        text = event.get("data", {}).get("full_text", "")
                        if text:
                            self._final_content = text
                    elif event_type == "subagent.act":
                        self._tool_calls_count += 1

                    yield event

        except Exception as e:
            logger.error(
                f"[SubAgentProcess] Error in {self._subagent.name}: {e}",
                exc_info=True,
            )
            success = False
            error_msg = str(e)

            yield self._make_event("subagent_failed", {
                "subagent_id": self._subagent.id,
                "subagent_name": self._subagent.display_name,
                "error": error_msg,
            })

        finally:
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

            # Emit subagent_completed event
            yield self._make_event("subagent_completed", self._result.to_event_data())

            logger.info(
                f"[SubAgentProcess] {self._subagent.name} completed: "
                f"success={success}, tools={self._tool_calls_count}, "
                f"time={execution_time_ms}ms"
            )

    def _relay_event(self, domain_event: Any) -> Optional[Dict[str, Any]]:
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
            "timestamp": event_dict.get(
                "timestamp", datetime.now(timezone.utc).isoformat()
            ),
        }

    def _make_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create an SSE event dict."""
        return {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
            return truncated[:cut_point + 1].strip()

        return truncated.strip() + "..."
