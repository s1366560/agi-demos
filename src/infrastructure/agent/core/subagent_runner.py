# pyright: reportUninitializedInstanceVariable=false
"""SubAgent session runner extracted from ReActAgent.

Handles SubAgent execution lifecycle: launching sessions, consuming events,
marking completion/failure/timeout/cancellation, and persisting announce metadata.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.subagent_result import SubAgentResult

from .processor import ProcessorConfig, ToolDefinition

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService
    from src.domain.llm_providers.llm_types import LLMClient

    from ..permission import PermissionManager
    from ..processor.factory import ProcessorFactory
logger = logging.getLogger(__name__)


@dataclass
class SubAgentRunnerDeps:
    """Dependencies injected into SubAgentSessionRunner.

    Holds references to shared state and services required by runner methods.
    Mutable counters (lifecycle_hook_failures) are wrapped in a list so
    mutations are visible to the owning ReActAgent.
    """

    # -- Services --
    graph_service: Any  # GraphServicePort | None
    llm_client: LLMClient | None
    permission_manager: PermissionManager
    artifact_service: ArtifactService | None
    background_executor: Any
    result_aggregator: Any

    # -- Shared registries / state --
    subagent_run_registry: Any
    subagent_lane_semaphore: asyncio.Semaphore
    subagent_lifecycle_hook: Callable[[dict[str, Any]], Any] | None
    # Mutable int counter wrapped in a list for shared mutation
    subagent_lifecycle_hook_failures: list[int] = field(
        default_factory=lambda: [0],
    )
    subagent_session_tasks: dict[str, asyncio.Task[Any]] = field(
        default_factory=dict,
    )

    # -- Model config --
    model: str = ""
    api_key: str | None = None
    base_url: str | None = None
    config: ProcessorConfig | None = None

    # -- ProcessorFactory (Wave 4) --
    factory: ProcessorFactory | None = None

    # -- SubAgent limits --
    subagents: list[SubAgent] = field(default_factory=list)
    max_subagent_delegation_depth: int = 2
    max_subagent_active_runs: int = 16
    max_subagent_active_runs_per_lineage: int = 8
    max_subagent_children_per_requester: int = 8
    enable_subagent_as_tool: bool = True

    # -- Announce config --
    subagent_announce_max_retries: int = 2
    subagent_announce_max_events: int = 20
    subagent_announce_retry_delay_ms: int = 200

    # -- Callbacks to ReActAgent (set after init) --
    get_current_tools_fn: Callable[..., tuple[dict[str, Any], list[ToolDefinition]]] | None = None
    filter_tools_fn: Callable[[SubAgent], tuple[list[ToolDefinition], set[str]]] | None = None
    inject_nested_tools_fn: Callable[..., None] | None = None


class SubAgentSessionRunner:
    """Manages SubAgent session execution lifecycle.

    Extracted from ReActAgent to reduce file size. Uses an explicit
    deps dataclass instead of back-references.
    """

    def __init__(self, deps: SubAgentRunnerDeps) -> None:
        self.deps = deps

    # ------------------------------------------------------------------
    # Memory context
    # ------------------------------------------------------------------

    async def fetch_memory_context(
        self,
        user_message: str,
        project_id: str,
    ) -> str:
        """Search for relevant memories to inject into SubAgent context."""
        if not self.deps.graph_service or not project_id:
            return ""
        try:
            from ..subagent.memory_accessor import MemoryAccessor

            accessor = MemoryAccessor(
                graph_service=self.deps.graph_service,
                project_id=project_id,
                writable=False,
            )
            items = await accessor.search(user_message)
            memory_context = accessor.format_for_context(items)
            if memory_context:
                logger.debug(
                    f"[ReActAgent] Injecting {len(items)} memory items into SubAgent context"
                )
            return memory_context
        except Exception as e:
            logger.warning(f"[ReActAgent] Memory search failed: {e}")
            return ""

    # ------------------------------------------------------------------
    # Core execution
    # ------------------------------------------------------------------

    async def execute_subagent(
        self,
        subagent: SubAgent,
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str = "",
        abort_signal: asyncio.Event | None = None,
        delegation_depth: int = 0,
        model_override: str | None = None,
        thinking_override: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute a SubAgent in an independent ReAct loop.

        Creates a SubAgentProcess with its own context window and processor,
        forwards SSE events, and yields a final complete event with the result.
        """
        from ..subagent.context_bridge import ContextBridge
        from ..subagent.process import SubAgentProcess

        memory_context = await self.fetch_memory_context(
            user_message,
            project_id,
        )

        bridge = ContextBridge()
        config = self.deps.config
        context_limit = config.context_limit if config else 128000
        subagent_context = bridge.build_subagent_context(
            user_message=user_message,
            subagent_system_prompt=subagent.system_prompt,
            conversation_context=conversation_context,
            main_token_budget=context_limit,
            project_id=project_id,
            tenant_id=tenant_id,
            memory_context=memory_context,
        )

        # Filter tools via callback
        assert self.deps.filter_tools_fn is not None
        filtered_tools, existing_tool_names = self.deps.filter_tools_fn(
            subagent,
        )

        # Inject nested tools via callback
        assert self.deps.inject_nested_tools_fn is not None
        self.deps.inject_nested_tools_fn(
            subagent=subagent,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            delegation_depth=delegation_depth,
            filtered_tools=filtered_tools,
            existing_tool_names=existing_tool_names,
        )

        process = SubAgentProcess(
            subagent=subagent,
            context=subagent_context,
            tools=filtered_tools,
            base_model=(model_override or self.deps.model),
            base_api_key=self.deps.api_key,
            base_url=self.deps.base_url,
            llm_client=self.deps.llm_client,
            permission_manager=self.deps.permission_manager,
            artifact_service=self.deps.artifact_service,
            abort_signal=abort_signal,
            factory=self.deps.factory,
        )

        async for event in process.execute():
            yield event

        result = process.result

        yield {
            "type": "complete",
            "data": {
                "content": result.final_content if result else "",
                "subagent_used": subagent.name,
                "subagent_result": (result.to_event_data() if result else None),
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def execute_parallel(
        self,
        subtasks: list[Any],
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str | None = None,
        route_id: str | None = None,
        abort_signal: asyncio.Event | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute multiple SubAgents in parallel via ParallelScheduler."""
        from ..subagent.parallel_scheduler import ParallelScheduler

        yield {
            "type": "parallel_started",
            "data": {
                "task_count": len(subtasks),
                "session_id": conversation_id or None,
                "route_id": route_id,
                "trace_id": route_id,
                "subtasks": [
                    {
                        "id": st.id,
                        "description": st.description,
                        "agent": st.target_subagent,
                    }
                    for st in subtasks
                ],
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

        subagent_map = {sa.name: sa for sa in self.deps.subagents}

        assert self.deps.get_current_tools_fn is not None
        _, current_tool_definitions = self.deps.get_current_tools_fn()

        config = self.deps.config
        context_limit = config.context_limit if config else 128000

        scheduler = ParallelScheduler()
        results: list[SubAgentResult] = []

        async for event in scheduler.execute(
            subtasks=subtasks,
            subagent_map=subagent_map,
            tools=current_tool_definitions,
            base_model=self.deps.model,
            base_api_key=self.deps.api_key,
            base_url=self.deps.base_url,
            llm_client=self.deps.llm_client,
            conversation_context=conversation_context,
            main_token_budget=context_limit,
            project_id=project_id,
            tenant_id=tenant_id,
            abort_signal=abort_signal,
            factory=self.deps.factory,
        ):
            if route_id or conversation_id:
                event_data = event.get("data")
                if isinstance(event_data, dict):
                    tagged_data = dict(event_data)
                    if route_id:
                        tagged_data.setdefault("route_id", route_id)
                        tagged_data.setdefault("trace_id", route_id)
                    if conversation_id:
                        tagged_data.setdefault(
                            "session_id",
                            conversation_id,
                        )
                    event = {**event, "data": tagged_data}
            yield event
            if event.get("type") == "subtask_completed" and event.get("data", {}).get("result"):
                result_data = event["data"]["result"]
                if isinstance(result_data, SubAgentResult):
                    results.append(result_data)

        aggregated = await self.deps.result_aggregator.aggregate_with_llm(
            results,
        )

        yield {
            "type": "parallel_completed",
            "data": {
                "session_id": conversation_id or None,
                "route_id": route_id,
                "trace_id": route_id,
                "total_tasks": len(subtasks),
                "completed": len(results),
                "all_succeeded": aggregated.all_succeeded,
                "total_tokens": aggregated.total_tokens,
                "failed_agents": list(aggregated.failed_agents),
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

        yield {
            "type": "complete",
            "data": {
                "content": aggregated.summary,
                "orchestration_mode": "parallel",
                "subtask_count": len(subtasks),
                "session_id": conversation_id or None,
                "route_id": route_id,
                "trace_id": route_id,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def execute_chain(
        self,
        subtasks: list[Any],
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str | None = None,
        route_id: str | None = None,
        abort_signal: asyncio.Event | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute SubAgents as a sequential chain (pipeline)."""
        from ..subagent.chain import ChainStep, SubAgentChain

        subagent_map = {sa.name: sa for sa in self.deps.subagents}

        ordered = self.topological_sort_subtasks(subtasks)
        chain_steps = []
        for i, st in enumerate(ordered):
            agent = subagent_map.get(st.target_subagent)
            if not agent:
                agent = self.deps.subagents[0] if self.deps.subagents else None
            if agent:
                template = "{input}" if i == 0 else "{input}\n\nPrevious result:\n{prev}"
                chain_steps.append(
                    ChainStep(
                        subagent=agent,
                        task_template=st.description + "\n\n" + template,
                        name=st.id,
                    )
                )

        if not chain_steps:
            return

        chain = SubAgentChain(steps=chain_steps)
        assert self.deps.get_current_tools_fn is not None
        _, current_tool_definitions = self.deps.get_current_tools_fn()

        config = self.deps.config
        context_limit = config.context_limit if config else 128000

        async for event in chain.execute(
            user_message=user_message,
            tools=current_tool_definitions,
            base_model=self.deps.model,
            base_api_key=self.deps.api_key,
            base_url=self.deps.base_url,
            llm_client=self.deps.llm_client,
            conversation_context=conversation_context,
            main_token_budget=context_limit,
            project_id=project_id,
            tenant_id=tenant_id,
            abort_signal=abort_signal,
            factory=self.deps.factory,
        ):
            if route_id or conversation_id:
                event_data = event.get("data")
                if isinstance(event_data, dict):
                    tagged_data = dict(event_data)
                    if route_id:
                        tagged_data.setdefault("route_id", route_id)
                        tagged_data.setdefault("trace_id", route_id)
                    if conversation_id:
                        tagged_data.setdefault(
                            "session_id",
                            conversation_id,
                        )
                    event = {**event, "data": tagged_data}
            yield event

        chain_result = chain.result
        yield {
            "type": "complete",
            "data": {
                "content": (chain_result.final_summary if chain_result else ""),
                "orchestration_mode": "chain",
                "step_count": len(chain_steps),
                "session_id": conversation_id or None,
                "route_id": route_id,
                "trace_id": route_id,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def execute_background(
        self,
        subagent: SubAgent,
        user_message: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Launch a SubAgent for background execution (non-blocking)."""
        assert self.deps.get_current_tools_fn is not None
        _, current_tool_definitions = self.deps.get_current_tools_fn()

        config = self.deps.config
        context_limit = config.context_limit if config else 128000

        execution_id = self.deps.background_executor.launch(
            subagent=subagent,
            user_message=user_message,
            conversation_id=conversation_id,
            tools=current_tool_definitions,
            base_model=self.deps.model,
            conversation_context=conversation_context,
            main_token_budget=context_limit,
            project_id=project_id,
            tenant_id=tenant_id,
            base_api_key=self.deps.api_key,
            base_url=self.deps.base_url,
            llm_client=self.deps.llm_client,
            factory=self.deps.factory,
        )

        yield {
            "type": "background_launched",
            "data": {
                "execution_id": execution_id,
                "subagent_id": subagent.id,
                "subagent_name": subagent.display_name,
                "task": user_message[:200],
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

        yield {
            "type": "complete",
            "data": {
                "content": (
                    f"Task delegated to {subagent.display_name} in background "
                    f"(ID: {execution_id}). You will be notified when "
                    "it completes."
                ),
                "orchestration_mode": "background",
                "execution_id": execution_id,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

    # ------------------------------------------------------------------
    # Lifecycle hooks & observability
    # ------------------------------------------------------------------

    async def emit_subagent_lifecycle_hook(
        self,
        event: dict[str, Any],
    ) -> None:
        """Emit detached SubAgent lifecycle hook event if configured."""
        if not self.deps.subagent_lifecycle_hook:
            return
        try:
            result = self.deps.subagent_lifecycle_hook(event)
            if inspect.isawaitable(result):
                await result
        except Exception:
            self.deps.subagent_lifecycle_hook_failures[0] += 1
            logger.warning(
                "SubAgent lifecycle hook failed",
                extra={
                    "event_type": event.get("type"),
                    "run_id": event.get("run_id"),
                },
                exc_info=True,
            )

    def get_subagent_observability_stats(self) -> dict[str, int]:
        """Return subagent lifecycle observability counters."""
        return {
            "hook_failures": int(
                self.deps.subagent_lifecycle_hook_failures[0],
            ),
        }

    # ------------------------------------------------------------------
    # Runner state-machine helpers
    # ------------------------------------------------------------------

    def runner_resolve_overrides(
        self,
        conversation_id: str,
        run_id: str,
        requested_model: str | None,
        requested_thinking: str | None,
        normalized_spawn_mode: str,
        thread_requested: bool,
        normalized_cleanup: str,
    ) -> tuple[str | None, str | None, float]:
        """Resolve model/thinking overrides from run_state metadata.

        Returns (resolved_model, resolved_thinking, configured_timeout).
        """
        resolved_model = requested_model
        resolved_thinking = requested_thinking
        configured_timeout = 0.0
        run_state = self.deps.subagent_run_registry.get_run(
            conversation_id,
            run_id,
        )
        if not run_state:
            return resolved_model, resolved_thinking, configured_timeout
        try:
            configured_timeout = float(
                run_state.metadata.get("run_timeout_seconds") or 0,
            )
        except (TypeError, ValueError):
            configured_timeout = 0.0
        if not resolved_model:
            resolved_model = (
                str(
                    run_state.metadata.get("model")
                    or run_state.metadata.get("model_override")
                    or ""
                ).strip()
                or None
            )
        if not resolved_thinking:
            resolved_thinking = (
                str(
                    run_state.metadata.get("thinking")
                    or run_state.metadata.get("thinking_override")
                    or ""
                ).strip()
                or None
            )
        self.deps.subagent_run_registry.attach_metadata(
            conversation_id=conversation_id,
            run_id=run_id,
            metadata={
                "spawn_mode": normalized_spawn_mode,
                "thread_requested": bool(thread_requested),
                "cleanup": normalized_cleanup,
                "model_override": resolved_model,
                "thinking_override": resolved_thinking,
            },
        )
        return resolved_model, resolved_thinking, configured_timeout

    def runner_mark_completion(
        self,
        conversation_id: str,
        run_id: str,
        result_success: bool,
        result_error: str | None,
        summary: str,
        tokens_used: int | None,
        execution_time_ms: int | None,
        started_at: float,
    ) -> None:
        """Mark a SubAgent run as completed or failed in the registry."""
        from src.domain.model.agent.subagent_run import SubAgentRunStatus

        current = self.deps.subagent_run_registry.get_run(
            conversation_id,
            run_id,
        )
        if not current or current.status not in {
            SubAgentRunStatus.PENDING,
            SubAgentRunStatus.RUNNING,
        }:
            return
        elapsed_ms = execution_time_ms or int(
            (time.time() - started_at) * 1000,
        )
        expected = [
            SubAgentRunStatus.PENDING,
            SubAgentRunStatus.RUNNING,
        ]
        if result_success:
            self.deps.subagent_run_registry.mark_completed(
                conversation_id=conversation_id,
                run_id=run_id,
                summary=summary,
                tokens_used=tokens_used,
                execution_time_ms=elapsed_ms,
                expected_statuses=expected,
            )
        else:
            self.deps.subagent_run_registry.mark_failed(
                conversation_id=conversation_id,
                run_id=run_id,
                error=result_error or "SubAgent session failed",
                execution_time_ms=elapsed_ms,
                expected_statuses=expected,
            )

    def runner_mark_timeout(
        self,
        conversation_id: str,
        run_id: str,
        configured_timeout: float,
    ) -> None:
        """Handle TimeoutError for a SubAgent runner."""
        from src.domain.model.agent.subagent_run import SubAgentRunStatus

        current = self.deps.subagent_run_registry.get_run(
            conversation_id,
            run_id,
        )
        if current and current.status in {
            SubAgentRunStatus.PENDING,
            SubAgentRunStatus.RUNNING,
        }:
            self.deps.subagent_run_registry.mark_timed_out(
                conversation_id=conversation_id,
                run_id=run_id,
                reason=(f"SubAgent session exceeded timeout ({configured_timeout}s)"),
                metadata={"timeout_seconds": configured_timeout},
                expected_statuses=[
                    SubAgentRunStatus.PENDING,
                    SubAgentRunStatus.RUNNING,
                ],
            )

    def runner_mark_cancelled(
        self,
        conversation_id: str,
        run_id: str,
    ) -> None:
        """Handle CancelledError for a SubAgent runner."""
        from src.domain.model.agent.subagent_run import SubAgentRunStatus

        current = self.deps.subagent_run_registry.get_run(
            conversation_id,
            run_id,
        )
        if current and current.status in {
            SubAgentRunStatus.PENDING,
            SubAgentRunStatus.RUNNING,
        }:
            self.deps.subagent_run_registry.mark_cancelled(
                conversation_id=conversation_id,
                run_id=run_id,
                reason="Cancelled by control tool",
                expected_statuses=[
                    SubAgentRunStatus.PENDING,
                    SubAgentRunStatus.RUNNING,
                ],
            )

    def runner_mark_error(
        self,
        conversation_id: str,
        run_id: str,
        exc: Exception,
        started_at: float,
    ) -> None:
        """Handle generic Exception for a SubAgent runner."""
        from src.domain.model.agent.subagent_run import SubAgentRunStatus

        current = self.deps.subagent_run_registry.get_run(
            conversation_id,
            run_id,
        )
        if current and current.status in {
            SubAgentRunStatus.PENDING,
            SubAgentRunStatus.RUNNING,
        }:
            self.deps.subagent_run_registry.mark_failed(
                conversation_id=conversation_id,
                run_id=run_id,
                error=str(exc),
                execution_time_ms=int(
                    (time.time() - started_at) * 1000,
                ),
                expected_statuses=[
                    SubAgentRunStatus.PENDING,
                    SubAgentRunStatus.RUNNING,
                ],
            )

    async def runner_finalize(
        self,
        *,
        conversation_id: str,
        run_id: str,
        subagent: SubAgent,
        cancelled_by_control: bool,
        summary: str,
        tokens_used: int | None,
        execution_time_ms: int | None,
        normalized_spawn_mode: str,
        thread_requested: bool,
        normalized_cleanup: str,
        resolved_model_override: str | None,
        resolved_thinking_override: str | None,
    ) -> None:
        """Finalize a SubAgent runner: persist announce, emit hook, cleanup."""
        if not cancelled_by_control:
            try:
                await self.persist_subagent_completion_announce(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    fallback_summary=summary,
                    fallback_tokens_used=tokens_used,
                    fallback_execution_time_ms=execution_time_ms,
                    spawn_mode=normalized_spawn_mode,
                    thread_requested=bool(thread_requested),
                    cleanup=normalized_cleanup,
                    model_override=resolved_model_override,
                    thinking_override=resolved_thinking_override,
                    max_retries=(self.deps.subagent_announce_max_retries),
                )
            except Exception:
                logger.warning(
                    "Failed to persist completion announce metadata",
                    extra={
                        "conversation_id": conversation_id,
                        "run_id": run_id,
                    },
                    exc_info=True,
                )
        final_run = self.deps.subagent_run_registry.get_run(
            conversation_id,
            run_id,
        )
        await self.emit_subagent_lifecycle_hook(
            {
                "type": "subagent_ended",
                "conversation_id": conversation_id,
                "run_id": run_id,
                "subagent_name": subagent.name,
                "status": (final_run.status.value if final_run else "unknown"),
                "summary": ((final_run.summary if final_run else summary) or ""),
                "error": ((final_run.error if final_run else "") or ""),
                "spawn_mode": normalized_spawn_mode,
                "thread_requested": bool(thread_requested),
                "cleanup": normalized_cleanup,
            }
        )
        self.deps.subagent_session_tasks.pop(run_id, None)

    async def launch_emit_lifecycle_hooks(
        self,
        *,
        conversation_id: str,
        run_id: str,
        subagent: SubAgent,
        normalized_spawn_mode: str,
        thread_requested: bool,
        normalized_cleanup: str,
        requested_model_override: str | None,
        requested_thinking_override: str | None,
    ) -> None:
        """Emit spawning + spawned lifecycle hooks for a subagent session."""
        await self.emit_subagent_lifecycle_hook(
            {
                "type": "subagent_spawning",
                "conversation_id": conversation_id,
                "run_id": run_id,
                "subagent_name": subagent.name,
                "spawn_mode": normalized_spawn_mode,
                "thread_requested": bool(thread_requested),
                "cleanup": normalized_cleanup,
                "model_override": requested_model_override,
                "thinking_override": requested_thinking_override,
            }
        )
        await self.emit_subagent_lifecycle_hook(
            {
                "type": "subagent_spawned",
                "conversation_id": conversation_id,
                "run_id": run_id,
                "subagent_name": subagent.name,
                "spawn_mode": normalized_spawn_mode,
                "thread_requested": bool(thread_requested),
                "cleanup": normalized_cleanup,
            }
        )

    # ------------------------------------------------------------------
    # Launch / consume / cancel
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_launch_params(
        spawn_mode: str,
        cleanup: str,
        model_override: str | None,
        thinking_override: str | None,
    ) -> tuple[str, str, str | None, str | None]:
        """Normalize input parameters for subagent session launch.

        Returns:
            (normalized_spawn_mode, normalized_cleanup,
             requested_model_override, requested_thinking_override)
        """
        normalized_spawn_mode = (spawn_mode or "run").strip().lower() or "run"
        normalized_cleanup = (cleanup or "keep").strip().lower() or "keep"
        requested_model_override = (model_override or "").strip() or None
        requested_thinking_override = (thinking_override or "").strip() or None
        return (
            normalized_spawn_mode,
            normalized_cleanup,
            requested_model_override,
            requested_thinking_override,
        )

    async def runner_consume_and_extract(
        self,
        *,
        subagent: SubAgent,
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        abort_signal: asyncio.Event | None,
        model_override: str | None,
        thinking_override: str | None,
    ) -> tuple[str, int | None, int | None, bool, str | None]:
        """Consume subagent events and extract completion results.

        Returns:
            (summary, tokens_used, execution_time_ms, success, error)
        """
        summary = ""
        tokens_used: int | None = None
        execution_time_ms: int | None = None
        result_success = True
        result_error: str | None = None

        async for evt in self.execute_subagent(
            subagent=subagent,
            user_message=user_message,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            model_override=model_override,
            thinking_override=thinking_override,
        ):
            if evt.get("type") != "complete":
                continue
            data = evt.get("data", {})
            subagent_result = data.get("subagent_result") or {}
            summary = subagent_result.get(
                "summary",
            ) or data.get("content", "")
            tokens_used = subagent_result.get("tokens_used")
            execution_time_ms = subagent_result.get("execution_time_ms")
            if isinstance(subagent_result, dict):
                result_success = bool(
                    subagent_result.get("success", True),
                )
                result_error = subagent_result.get("error")

        return (
            summary,
            tokens_used,
            execution_time_ms,
            result_success,
            result_error,
        )

    async def launch_subagent_session(  # noqa: PLR0913
        self,
        run_id: str,
        subagent: SubAgent,
        user_message: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        abort_signal: asyncio.Event | None = None,
        model_override: str | None = None,
        thinking_override: str | None = None,
        spawn_mode: str = "run",
        thread_requested: bool = False,
        cleanup: str = "keep",
    ) -> None:
        """Launch a detached SubAgent session tied to a run_id."""
        if run_id in self.deps.subagent_session_tasks:
            raise ValueError(f"Run {run_id} is already running")

        (
            normalized_spawn_mode,
            normalized_cleanup,
            requested_model_override,
            requested_thinking_override,
        ) = self.normalize_launch_params(
            spawn_mode,
            cleanup,
            model_override,
            thinking_override,
        )
        start_gate = asyncio.Event()

        async def _runner() -> None:
            await start_gate.wait()
            started_at = time.time()
            cancelled_by_control = False
            (
                resolved_model_override,
                resolved_thinking_override,
                configured_timeout,
            ) = self.runner_resolve_overrides(
                conversation_id=conversation_id,
                run_id=run_id,
                requested_model=requested_model_override,
                requested_thinking=requested_thinking_override,
                normalized_spawn_mode=normalized_spawn_mode,
                thread_requested=thread_requested,
                normalized_cleanup=normalized_cleanup,
            )

            summary = ""
            tokens_used: int | None = None
            execution_time_ms: int | None = None
            result_success = True
            result_error: str | None = None

            try:
                lane_wait_start = time.time()
                async with self.deps.subagent_lane_semaphore:
                    lane_wait_ms = int(
                        (time.time() - lane_wait_start) * 1000,
                    )
                    if lane_wait_ms > 0:
                        self.deps.subagent_run_registry.attach_metadata(
                            conversation_id=conversation_id,
                            run_id=run_id,
                            metadata={"lane_wait_ms": lane_wait_ms},
                        )
                    consume_coro = self.runner_consume_and_extract(
                        subagent=subagent,
                        user_message=user_message,
                        conversation_context=conversation_context,
                        project_id=project_id,
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        abort_signal=abort_signal,
                        model_override=resolved_model_override,
                        thinking_override=resolved_thinking_override,
                    )
                    if configured_timeout > 0:
                        result = await asyncio.wait_for(
                            consume_coro,
                            timeout=configured_timeout,
                        )
                    else:
                        result = await consume_coro
                    (
                        summary,
                        tokens_used,
                        execution_time_ms,
                        result_success,
                        result_error,
                    ) = result

                self.runner_mark_completion(
                    conversation_id,
                    run_id,
                    result_success,
                    result_error,
                    summary,
                    tokens_used,
                    execution_time_ms,
                    started_at,
                )
            except TimeoutError:
                self.runner_mark_timeout(
                    conversation_id,
                    run_id,
                    configured_timeout,
                )
            except asyncio.CancelledError:
                cancelled_by_control = True
                self.runner_mark_cancelled(conversation_id, run_id)
                raise
            except Exception as exc:
                self.runner_mark_error(
                    conversation_id,
                    run_id,
                    exc,
                    started_at,
                )
            finally:
                await self.runner_finalize(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    subagent=subagent,
                    cancelled_by_control=cancelled_by_control,
                    summary=summary,
                    tokens_used=tokens_used,
                    execution_time_ms=execution_time_ms,
                    normalized_spawn_mode=normalized_spawn_mode,
                    thread_requested=thread_requested,
                    normalized_cleanup=normalized_cleanup,
                    resolved_model_override=resolved_model_override,
                    resolved_thinking_override=(resolved_thinking_override),
                )

        task = asyncio.create_task(
            _runner(),
            name=f"subagent-session-{run_id}",
        )
        self.deps.subagent_session_tasks[run_id] = task
        await self.launch_emit_lifecycle_hooks(
            conversation_id=conversation_id,
            run_id=run_id,
            subagent=subagent,
            normalized_spawn_mode=normalized_spawn_mode,
            thread_requested=thread_requested,
            normalized_cleanup=normalized_cleanup,
            requested_model_override=requested_model_override,
            requested_thinking_override=requested_thinking_override,
        )
        start_gate.set()

    @staticmethod
    def resolve_subagent_completion_outcome(
        status: str,
    ) -> tuple[str, str]:
        """Map terminal run status to announce outcome labels."""
        status_key = (status or "").strip().lower()
        if status_key == "completed":
            return "success", "completed successfully"
        if status_key == "failed":
            return "error", "failed"
        if status_key == "timed_out":
            return "timeout", "timed out"
        if status_key == "cancelled":
            return "cancelled", "cancelled"
        return "unknown", status_key or "unknown"

    def append_capped_announce_event(
        self,
        events: list[dict[str, Any]],
        dropped_count: int,
        event: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        """Append announce event while enforcing bounded history size."""
        normalized_events = list(events)
        max_events = self.deps.subagent_announce_max_events
        if len(normalized_events) >= max_events:
            normalized_events = normalized_events[-(max_events - 1) :]
            dropped_count += 1
        normalized_events.append(event)
        return normalized_events, dropped_count

    @classmethod
    def build_subagent_completion_payload(
        cls,
        *,
        run: Any,
        fallback_summary: str,
        fallback_tokens_used: int | None,
        fallback_execution_time_ms: int | None,
        spawn_mode: str,
        thread_requested: bool,
        cleanup: str,
        model_override: str | None,
        thinking_override: str | None,
    ) -> dict[str, Any]:
        """Build normalized completion announce payload."""
        outcome, status_text = cls.resolve_subagent_completion_outcome(
            run.status.value,
        )
        result_text = (run.summary or fallback_summary or "").strip() or "(not available)"
        execution_time_ms = (
            run.execution_time_ms
            if run.execution_time_ms is not None
            else fallback_execution_time_ms
        )
        tokens_used = run.tokens_used if run.tokens_used is not None else fallback_tokens_used
        return {
            "run_id": run.run_id,
            "conversation_id": run.conversation_id,
            "subagent_name": run.subagent_name,
            "status": run.status.value,
            "outcome": outcome,
            "status_text": status_text,
            "result": result_text,
            "notes": run.error or "",
            "execution_time_ms": execution_time_ms,
            "tokens_used": tokens_used,
            "spawn_mode": spawn_mode,
            "thread_requested": bool(thread_requested),
            "cleanup": cleanup,
            "model_override": model_override,
            "thinking_override": thinking_override,
            "completed_at": (run.ended_at.isoformat() if run.ended_at else None),
        }

    async def persist_subagent_completion_announce(
        self,
        *,
        conversation_id: str,
        run_id: str,
        fallback_summary: str,
        fallback_tokens_used: int | None,
        fallback_execution_time_ms: int | None,
        spawn_mode: str,
        thread_requested: bool,
        cleanup: str,
        model_override: str | None,
        thinking_override: str | None,
        max_retries: int,
    ) -> None:
        """Persist terminal announce payload with retry/backoff."""
        from src.domain.model.agent.subagent_run import SubAgentRunStatus

        terminal_statuses = [
            SubAgentRunStatus.COMPLETED,
            SubAgentRunStatus.FAILED,
            SubAgentRunStatus.TIMED_OUT,
            SubAgentRunStatus.CANCELLED,
        ]
        attempts_used = 0
        last_error = "announce metadata update conflict"

        for attempt in range(max_retries + 1):
            attempts_used = attempt + 1
            run = self.deps.subagent_run_registry.get_run(
                conversation_id,
                run_id,
            )
            if not run or run.status not in terminal_statuses:
                return

            payload = self.build_subagent_completion_payload(
                run=run,
                fallback_summary=fallback_summary,
                fallback_tokens_used=fallback_tokens_used,
                fallback_execution_time_ms=fallback_execution_time_ms,
                spawn_mode=spawn_mode,
                thread_requested=thread_requested,
                cleanup=cleanup,
                model_override=model_override,
                thinking_override=thinking_override,
            )
            announce_events = run.metadata.get("announce_events")
            if not isinstance(announce_events, list):
                announce_events = []
            dropped_count = int(
                run.metadata.get("announce_events_dropped") or 0,
            )

            if attempt > 0:
                retry_event = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "type": "completion_retry",
                    "attempt": attempt,
                    "run_id": run_id,
                    "reason": last_error,
                }
                announce_events, dropped_count = self.append_capped_announce_event(
                    announce_events,
                    dropped_count,
                    retry_event,
                )

            delivered_event = {
                "timestamp": datetime.now(UTC).isoformat(),
                "type": "completion_delivered",
                "attempt": attempts_used,
                "run_id": run_id,
                "status": payload["status"],
            }
            announce_events, dropped_count = self.append_capped_announce_event(
                announce_events,
                dropped_count,
                delivered_event,
            )

            try:
                updated_run = self.deps.subagent_run_registry.attach_metadata(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    metadata={
                        "announce_payload": payload,
                        "announce_status": "delivered",
                        "announce_attempt_count": attempts_used,
                        "announce_completed_at": (datetime.now(UTC).isoformat()),
                        "announce_last_error": "",
                        "announce_events": announce_events,
                        "announce_events_dropped": dropped_count,
                    },
                    expected_statuses=terminal_statuses,
                )
            except Exception as exc:
                updated_run = None
                last_error = str(exc)
                logger.warning(
                    "Failed to attach completion announce metadata",
                    extra={
                        "conversation_id": conversation_id,
                        "run_id": run_id,
                        "attempt": attempts_used,
                    },
                    exc_info=True,
                )

            if updated_run is not None:
                return
            if not last_error:
                last_error = "announce metadata update conflict"

            if attempt < max_retries:
                delay_seconds = (self.deps.subagent_announce_retry_delay_ms * (2**attempt)) / 1000.0
                await asyncio.sleep(delay_seconds)

        run = self.deps.subagent_run_registry.get_run(
            conversation_id,
            run_id,
        )
        if not run or run.status not in terminal_statuses:
            return
        announce_events = run.metadata.get("announce_events")
        if not isinstance(announce_events, list):
            announce_events = []
        dropped_count = int(
            run.metadata.get("announce_events_dropped") or 0,
        )
        giveup_event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "type": "completion_giveup",
            "attempt": attempts_used,
            "run_id": run_id,
            "reason": last_error,
        }
        announce_events, dropped_count = self.append_capped_announce_event(
            announce_events,
            dropped_count,
            giveup_event,
        )
        self.deps.subagent_run_registry.attach_metadata(
            conversation_id=conversation_id,
            run_id=run_id,
            metadata={
                "announce_status": "giveup",
                "announce_attempt_count": attempts_used,
                "announce_last_error": last_error,
                "announce_events": announce_events,
                "announce_events_dropped": dropped_count,
            },
            expected_statuses=terminal_statuses,
        )

    async def cancel_subagent_session(self, run_id: str) -> bool:
        """Cancel a detached SubAgent session by run_id."""
        task = self.deps.subagent_session_tasks.get(run_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    @staticmethod
    def topological_sort_subtasks(subtasks: list[Any]) -> list[Any]:
        """Sort subtasks by dependency order (topological sort)."""
        id_to_task = {st.id: st for st in subtasks}
        visited: set[str] = set()
        result: list[Any] = []

        def visit(task_id: str) -> None:
            if task_id in visited:
                return
            visited.add(task_id)
            task = id_to_task.get(task_id)
            if task:
                for dep in task.dependencies:
                    visit(dep)
                result.append(task)

        for st in subtasks:
            visit(st.id)
        return result
