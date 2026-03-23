"""
BackgroundExecutor - Executes SubAgents as non-blocking background tasks.

Allows the main agent to continue responding while SubAgents work
in the background. Results are pushed via SSE events when complete.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

    from src.domain.llm_providers.llm_types import LLMClient
    from src.infrastructure.agent.processor.factory import ProcessorFactory

from src.domain.events.agent_events import (
    SubAgentKilledEvent,
    SubAgentSessionUpdateEvent,
    SubAgentSpawnRejectedEvent,
)
from src.domain.model.agent.subagent import SubAgent
from src.infrastructure.agent.subagent.span_service import SubAgentSpanService

from .context_bridge import ContextBridge
from .orphan_sweeper import OrphanSweeper
from .process import SubAgentProcess
from .spawn_validator import SpawnValidator
from .state_tracker import StateTracker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _noop_span_ctx() -> AsyncIterator[None]:
    """No-op async context manager used when span_service is None."""
    yield None


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
        timeout_seconds: int = 300,
        redis_client: AsyncRedis | None = None,
        orphan_sweeper: OrphanSweeper | None = None,
        spawn_validator: SpawnValidator | None = None,
        span_service: SubAgentSpanService | None = None,
        fork_merge_service: object | None = None,
    ) -> None:
        """Initialize BackgroundExecutor.

        Args:
            state_tracker: State tracker for execution lifecycle.
            on_event: Async callback for publishing events when
                SubAgents complete. Receives event dicts.
            timeout_seconds: Max allowed runtime per SubAgent task.
                Tasks exceeding this are killed by the orphan sweep.
            orphan_sweeper: Optional OrphanSweeper for delegated orphan
                detection. Falls back to inline implementation when None.
            spawn_validator: Optional SpawnValidator for pre-launch policy
                checks. When set, rejects spawns that violate spawn policy.
            span_service: Optional SubAgentSpanService for tracing runs.
            fork_merge_service: Optional SessionForkMergeService for
                forking/merging sessions across SubAgent boundaries.
        """
        self._tracker = state_tracker or StateTracker()
        self._on_event = on_event
        self._timeout_seconds = timeout_seconds
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._sweep_task: asyncio.Task[Any] | None = None
        self._redis_client: AsyncRedis | None = redis_client
        self._orphan_sweeper = orphan_sweeper
        self._spawn_validator = spawn_validator
        self._span_service = span_service
        self._fork_merge_service = fork_merge_service

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

        if self._spawn_validator is not None:
            result = self._spawn_validator.validate(
                subagent_name=subagent.display_name,
                current_depth=0,
                conversation_id=conversation_id,
                requester_session_id=None,
            )
            if not result.allowed:
                logger.warning(
                    "[BackgroundExecutor] Spawn rejected for %s: %s",
                    subagent.display_name,
                    result.rejection_reason,
                )
                if self._on_event:
                    event = SubAgentSpawnRejectedEvent(
                        subagent_name=subagent.display_name,
                        rejection_code=(
                            result.rejection_code.value if result.rejection_code else ""
                        ),
                        rejection_reason=result.rejection_reason or "",
                        context=result.context,
                    )
                    self._on_event(dict(event.to_event_dict()))
                return execution_id

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
            await self._emit(
                dict(
                    SubAgentKilledEvent(
                        subagent_id="",
                        subagent_name="",
                        kill_reason="Cancelled by user",
                    ).to_event_dict(),
                ),
            )
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
                "type": "background_launched",
                "data": {
                    "execution_id": execution_id,
                    "subagent_name": subagent.display_name,
                    "task_description": user_message[:200],
                    "conversation_id": conversation_id,
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        span_ctx: Any
        if self._span_service is not None:
            from src.domain.model.agent.subagent_run import SubAgentRun

            sa_run = SubAgentRun(
                conversation_id=conversation_id,
                subagent_name=subagent.display_name,
                task=user_message[:200],
                run_id=execution_id,
            )
            trace_info = self._span_service.extract_trace_context()
            if trace_info is not None:
                sa_run.with_trace_context(trace_info[0], trace_info[1])
            span_ctx = self._span_service.trace_run(sa_run)
        else:
            span_ctx = _noop_span_ctx()

        try:
            async with span_ctx as span:
                bridge = ContextBridge()
                context = bridge.build_subagent_context(
                    user_message=user_message,
                    subagent_system_prompt=subagent.system_prompt,
                    conversation_context=conversation_context or [],
                    main_token_budget=main_token_budget,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                )

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

                async for event in process.execute():
                    if event.get("type") in ("subagent.act", "subagent.observe"):
                        new_progress = min(
                            95,
                            self._tracker.get_state(execution_id, conversation_id).progress + 10,  # type: ignore[union-attr]
                        )
                        self._tracker.update_progress(
                            execution_id,
                            conversation_id,
                            new_progress,
                        )
                        await self._emit(
                            dict(
                                SubAgentSessionUpdateEvent(
                                    subagent_id=subagent.id,
                                    subagent_name=subagent.display_name,
                                    progress=new_progress,
                                    status_message="Processing",
                                ).to_event_dict(),
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

                    _ss = self._span_service
                    if span is not None and _ss is not None:
                        _ss.mark_span_completed(
                            span,
                            summary=result.final_content[:500],
                            tokens_used=result.tokens_used,
                        )

                    await self._emit(
                        {
                            "type": "subagent_completed",
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
                    self._tracker.fail(
                        execution_id, conversation_id, error=error or "Unknown error"
                    )

                    _ss2 = self._span_service
                    if span is not None and _ss2 is not None:
                        _ss2.mark_span_failed(span, error=error or "Unknown error")

                    await self._emit(
                        {
                            "type": "subagent_failed",
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
            await self._emit(
                dict(
                    SubAgentKilledEvent(
                        subagent_id=subagent.id,
                        subagent_name=subagent.display_name,
                        kill_reason="Cancelled during background execution",
                    ).to_event_dict(),
                ),
            )
            logger.info(f"[BackgroundExecutor] {execution_id} was cancelled")
        except Exception as e:
            self._tracker.fail(execution_id, conversation_id, error=str(e))
            logger.error(f"[BackgroundExecutor] {execution_id} failed: {e}")

            await self._emit(
                {
                    "type": "subagent_failed",
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

    def start_orphan_sweep(self, interval_seconds: int = 60) -> None:
        """Start the periodic orphan detection sweep.

        Launches a background asyncio task that periodically scans
        for timed-out or done tasks and cleans them up.

        Args:
            interval_seconds: Seconds between sweep iterations.
        """
        if self._sweep_task is not None and not self._sweep_task.done():
            logger.debug("[BackgroundExecutor] Orphan sweep already running")
            return
        self._sweep_task = asyncio.create_task(
            self._orphan_sweep_loop(interval_seconds),
            name="bg-orphan-sweep",
        )
        logger.info(
            f"[BackgroundExecutor] Orphan sweep started (interval={interval_seconds}s, "
            f"timeout={self._timeout_seconds}s)"
        )

    async def _orphan_sweep_loop(self, interval: int) -> None:
        """Loop that periodically invokes _sweep_orphans."""
        try:
            while True:
                await asyncio.sleep(interval)
                await self._sweep_orphans()
        except asyncio.CancelledError:
            logger.info("[BackgroundExecutor] Orphan sweep loop cancelled")

    async def _sweep_orphans(self) -> None:
        """Scan tasks and clean up done, timed-out, or cancel-signalled entries.

        Done tasks are simply removed from the task dict.
        Running tasks that exceed ``_timeout_seconds`` are cancelled
        and their state is marked as failed via the tracker.
        Tasks with a Redis cancel signal (``subagent:cancel:{eid}``) are
        cancelled and a ``SubAgentKilledEvent`` is emitted.
        A ``SubAgentKilledEvent`` is emitted for each killed task.
        """
        if self._orphan_sweeper is not None:
            removed = await self._orphan_sweeper.sweep(self._tasks)
            for eid in removed:
                self._tasks.pop(eid, None)
            for event in self._orphan_sweeper.consume_pending_events():
                await self._emit(event)
            return

        await self._sweep_orphans_fallback()

    async def _sweep_orphans_fallback(self) -> None:
        """Original orphan sweep logic used when no OrphanSweeper is injected."""
        now = datetime.now(UTC)
        to_remove: list[str] = []

        for eid, task in list(self._tasks.items()):
            if task.done():
                to_remove.append(eid)
                continue

            # Check timeout via tracker state
            state = self._tracker.get_state_by_execution_id(eid)
            if state is None:
                continue

            # Check for Redis cancel signal
            if self._redis_client is not None:
                try:
                    cancel_key = f"subagent:cancel:{eid}"
                    cancel_data_raw = await self._redis_client.get(cancel_key)
                    if cancel_data_raw is not None:
                        task.cancel()
                        import json as _json

                        cancel_info = _json.loads(cancel_data_raw)
                        reason = cancel_info.get("reason", "Cancelled by user")
                        self._tracker.fail(
                            eid,
                            state.conversation_id,
                            error=f"Cancelled: {reason}",
                        )
                        to_remove.append(eid)

                        await self._emit(
                            dict(
                                SubAgentKilledEvent(
                                    subagent_id=state.subagent_id,
                                    subagent_name=state.subagent_name,
                                    kill_reason=reason,
                                ).to_event_dict(),
                            ),
                        )
                        # Delete the cancel key so it's not re-processed
                        await self._redis_client.delete(cancel_key)
                        logger.info(
                            f"[BackgroundExecutor] Cancelled {eid} via Redis signal "
                            f"({state.subagent_name}, reason={reason})"
                        )
                        continue
                except Exception as exc:
                    logger.warning(
                        f"[BackgroundExecutor] Error checking cancel signal for {eid}: {exc}"
                    )

            if state.started_at is None:
                continue

            elapsed = (now - state.started_at).total_seconds()
            if elapsed > self._timeout_seconds:
                task.cancel()
                self._tracker.fail(
                    eid,
                    state.conversation_id,
                    error=f"Timed out after {self._timeout_seconds}s (orphan sweep)",
                )
                to_remove.append(eid)

                await self._emit(
                    dict(
                        SubAgentKilledEvent(
                            subagent_id=state.subagent_id,
                            subagent_name=state.subagent_name,
                            kill_reason="orphan_sweep",
                        ).to_event_dict(),
                    ),
                )
                logger.warning(
                    f"[BackgroundExecutor] Killed orphan {eid} "
                    f"({state.subagent_name}, {elapsed:.0f}s elapsed)"
                )

        for eid in to_remove:
            self._tasks.pop(eid, None)

    def stop_orphan_sweep(self) -> None:
        """Stop the orphan sweep loop if running."""
        if self._sweep_task is not None and not self._sweep_task.done():
            self._sweep_task.cancel()
            logger.info("[BackgroundExecutor] Orphan sweep stopped")
