"""
BackgroundExecutor - Executes SubAgents as non-blocking background tasks.

Allows the main agent to continue responding while SubAgents work
in the background. Results are pushed via SSE events when complete.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.llm_providers.llm_types import LLMClient
    from src.infrastructure.agent.processor.factory import ProcessorFactory


from src.domain.model.agent.subagent import SubAgent

from .context_bridge import ContextBridge
from .process import SubAgentProcess
from .state_tracker import StateTracker

logger = logging.getLogger(__name__)


class BackgroundExecutor:
    """Manages background SubAgent execution.

    SubAgents started in background mode do not block the main conversation.
    The executor:
    1. Launches SubAgent in an asyncio task
    2. Tracks state via StateTracker
    3. Pushes result events to a callback when complete

    The event callback allows results to be forwarded to the client
    via SSE or Redis pub/sub after the main response has been sent.
    """

    def __init__(
        self,
        state_tracker: StateTracker | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize BackgroundExecutor.

        Args:
            state_tracker: State tracker for execution lifecycle.
            on_event: Async callback for publishing events when
                SubAgents complete. Receives event dicts.
        """
        self._tracker = state_tracker or StateTracker()
        self._on_event = on_event
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    @property
    def tracker(self) -> StateTracker:
        """Access the state tracker."""
        return self._tracker

    def launch(  # noqa: PLR0913
        self,
        subagent: SubAgent,
        user_message: str,
        conversation_id: str,
        tools: list[Any],
        base_model: str,
        conversation_context: list[dict[str, str]] | None = None,
        main_token_budget: int = 128000,
        project_id: str = "",
        tenant_id: str = "",
        base_api_key: str | None = None,
        base_url: str | None = None,
        llm_client: LLMClient | None = None,
        factory: ProcessorFactory | None = None,
    ) -> str:
        """Launch a SubAgent in the background.

        Returns immediately with an execution_id. The SubAgent runs
        asynchronously and results are delivered via the on_event callback.

        Args:
            subagent: SubAgent to execute.
            user_message: Task description.
            conversation_id: Parent conversation ID.
            tools: Available tool definitions.
            base_model: Default model name.
            conversation_context: Recent conversation for context.
            main_token_budget: Token budget for context bridging.
            project_id: Project ID.
            tenant_id: Tenant ID.
            base_api_key: API key.
            base_url: API base URL.
            llm_client: LLM client for the SubAgent.

        Returns:
            execution_id for tracking the background task.
        """
        execution_id = f"bg-{uuid.uuid4().hex[:12]}"

        # Register in state tracker
        self._tracker.register(
            execution_id=execution_id,
            subagent_id=subagent.id,
            subagent_name=subagent.display_name,
            conversation_id=conversation_id,
            task_description=user_message[:200],
        )

        # Create the background task
        task = asyncio.create_task(
            self._run(
                execution_id=execution_id,
                subagent=subagent,
                user_message=user_message,
                conversation_id=conversation_id,
                tools=tools,
                base_model=base_model,
                conversation_context=conversation_context,
                main_token_budget=main_token_budget,
                project_id=project_id,
                tenant_id=tenant_id,
                base_api_key=base_api_key,
                base_url=base_url,
                llm_client=llm_client,
                factory=factory,
            ),
            name=f"bg-subagent-{execution_id}",
        )

        self._tasks[execution_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(execution_id, None))

        logger.info(f"[BackgroundExecutor] Launched {subagent.display_name} as {execution_id}")

        return execution_id

    async def cancel(self, execution_id: str, conversation_id: str) -> bool:
        """Cancel a background SubAgent execution.

        Args:
            execution_id: Execution to cancel.
            conversation_id: Parent conversation.

        Returns:
            True if cancellation was successful.
        """
        task = self._tasks.get(execution_id)
        if task and not task.done():
            task.cancel()
            self._tracker.cancel(execution_id, conversation_id)
            logger.info(f"[BackgroundExecutor] Cancelled {execution_id}")
            return True
        return False

    def get_active(self, conversation_id: str) -> list[dict[str, Any]]:
        """Get active background executions for a conversation.

        Args:
            conversation_id: Conversation to query.

        Returns:
            List of state dicts for active executions.
        """
        return [s.to_dict() for s in self._tracker.get_active(conversation_id)]

    async def _run(  # noqa: PLR0913
        self,
        execution_id: str,
        subagent: SubAgent,
        user_message: str,
        conversation_id: str,
        tools: list[Any],
        base_model: str,
        conversation_context: list[dict[str, str]] | None = None,
        main_token_budget: int = 128000,
        project_id: str = "",
        tenant_id: str = "",
        base_api_key: str | None = None,
        base_url: str | None = None,
        llm_client: LLMClient | None = None,
        factory: ProcessorFactory | None = None,
    ) -> None:
        """Internal execution coroutine for background SubAgent."""
        self._tracker.start(execution_id, conversation_id)

        # Emit started event
        await self._emit(
            {
                "type": "background_subagent_started",
                "data": {
                    "execution_id": execution_id,
                    "subagent_name": subagent.display_name,
                    "task_description": user_message[:200],
                    "conversation_id": conversation_id,
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        try:
            # Build context
            bridge = ContextBridge()
            context = bridge.build_subagent_context(
                user_message=user_message,
                subagent_system_prompt=subagent.system_prompt,
                conversation_context=conversation_context or [],
                main_token_budget=main_token_budget,
                project_id=project_id,
                tenant_id=tenant_id,
            )

            # Create and execute process
            process = SubAgentProcess(
                subagent=subagent,
                context=context,
                tools=tools,
                base_model=base_model,
                base_api_key=base_api_key,
                base_url=base_url,
                llm_client=llm_client,
                factory=factory,
            )

            # Consume events (we don't yield them since this is background)
            async for event in process.execute():
                # Optionally relay progress events
                if event.get("type") in ("subagent.act", "subagent.observe"):
                    self._tracker.update_progress(
                        execution_id,
                        conversation_id,
                        min(
                            95, self._tracker.get_state(execution_id, conversation_id).progress + 10  # type: ignore[union-attr]
                        ),
                    )

            result = process.result

            if result and result.success:
                self._tracker.complete(
                    execution_id,
                    conversation_id,
                    summary=result.final_content[:500],
                    tokens_used=result.tokens_used,
                    tool_calls_count=result.tool_calls_count,
                )

                await self._emit(
                    {
                        "type": "background_subagent_completed",
                        "data": {
                            "execution_id": execution_id,
                            "subagent_name": subagent.display_name,
                            "conversation_id": conversation_id,
                            "result": result.to_event_data() if result else None,
                        },
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
            else:
                error = result.error if result else "No result produced"
                self._tracker.fail(execution_id, conversation_id, error=error or "Unknown error")

                await self._emit(
                    {
                        "type": "background_subagent_failed",
                        "data": {
                            "execution_id": execution_id,
                            "subagent_name": subagent.display_name,
                            "conversation_id": conversation_id,
                            "error": error,
                        },
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )

        except asyncio.CancelledError:
            self._tracker.cancel(execution_id, conversation_id)
            logger.info(f"[BackgroundExecutor] {execution_id} was cancelled")
        except Exception as e:
            self._tracker.fail(execution_id, conversation_id, error=str(e))
            logger.error(f"[BackgroundExecutor] {execution_id} failed: {e}")

            await self._emit(
                {
                    "type": "background_subagent_failed",
                    "data": {
                        "execution_id": execution_id,
                        "subagent_name": subagent.display_name,
                        "conversation_id": conversation_id,
                        "error": str(e),
                    },
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

    async def _emit(self, event: dict[str, Any]) -> None:
        """Emit an event via the callback."""
        if self._on_event:
            try:
                if asyncio.iscoroutinefunction(self._on_event):
                    await self._on_event(event)
                else:
                    self._on_event(event)
            except Exception as e:
                logger.warning(f"[BackgroundExecutor] Event emission failed: {e}")
