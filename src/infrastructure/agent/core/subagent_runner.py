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
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from src.domain.events.agent_events import (
    AgentBackgroundLaunchedEvent,
    AgentCompleteEvent,
    AgentParallelCompletedEvent,
    AgentParallelStartedEvent,
    SubAgentDepthLimitedEvent,
    SubAgentKilledEvent,
    SubAgentQueuedEvent,
    SubAgentSpawningEvent,
    SubAgentSpawnRejectedEvent,
)
from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.subagent_result import SubAgentResult
from src.domain.model.agent.subagent_run import SubAgentRunStatus
from src.infrastructure.agent.subagent.async_run_registry_v2 import (
    AsyncSubAgentRunRegistryV2,
    registry_call_v2,
    registry_transaction_v2,
)
from src.infrastructure.agent.subagent.owner_control_v2 import SubAgentOwnerControlV2
from src.infrastructure.agent.subagent.owner_lease_v2 import SubAgentExecutionOwnerV2
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.subagent.spawn_validator import SpawnValidator
from src.infrastructure.plugins.v2.agent_operation_tool_contributions import (
    lease_operation_tool_definitions_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    ForkedAgentOperationV2,
    detached_operation_task_context_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.tool_set import ToolSetV2

from .detached_subagent_task_supervisor import DetachedSubAgentTaskSupervisor
from .processor import ProcessorConfig, ToolDefinition
from .subagent_registry_authority import (
    SubAgentRunRegistryResolverV2,
    require_subagent_run_registry_v2,
)
from .subagent_tool_set_v2 import InheritedToolSetV2, SubAgentToolSetBindingV2

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
    operation_reserver: Callable[[], Awaitable[ForkedAgentOperationV2]]
    session_factory: Callable[[], Any] | None

    # -- Shared registries / state --
    subagent_run_registry_resolver: SubAgentRunRegistryResolverV2
    subagent_lane_semaphore: asyncio.Semaphore
    subagent_lifecycle_hook: Callable[[dict[str, Any]], Any] | None
    # Mutable int counter wrapped in a list for shared mutation
    subagent_lifecycle_hook_failures: list[int] = field(
        default_factory=lambda: [0],
    )
    detached_subagent_task_supervisor: DetachedSubAgentTaskSupervisor = field(
        default_factory=DetachedSubAgentTaskSupervisor,
    )

    # -- Model config --
    model: str = ""
    api_key: str | None = None
    base_url: str | None = None
    config: ProcessorConfig | None = None

    # -- ProcessorFactory (Wave 4) --
    factory: ProcessorFactory | None = None

    # -- SubAgent limits --
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
    inherited_tool_set_fn: Callable[[], InheritedToolSetV2] | None = None
    operation_context_fn: Callable[[], Any] | None = None
    filter_tools_fn: Callable[..., tuple[list[ToolDefinition], set[str]]] | None = None
    inject_nested_tools_fn: Callable[..., None] | None = None

    # -- Spawn validation --
    spawn_validator: SpawnValidator | None = None

    @property
    def subagent_run_registry(self) -> SubAgentRunRegistry:
        """Resolve the registry from the exact V2 operation on every access."""
        return require_subagent_run_registry_v2(self.subagent_run_registry_resolver)


class SubAgentSessionRunner:
    """Manages SubAgent session execution lifecycle.

    Extracted from ReActAgent to reduce file size. Uses an explicit
    deps dataclass instead of back-references.
    """

    def __init__(self, deps: SubAgentRunnerDeps) -> None:
        self.deps = deps

    def _resolve_inherited_tool_set(
        self,
        inherited_tool_set: InheritedToolSetV2 | None,
    ) -> InheritedToolSetV2:
        if inherited_tool_set is None:
            resolver = self.deps.inherited_tool_set_fn
            if resolver is None:
                raise RuntimeV2Error(
                    "subagent_tool_set_not_inherited",
                    "SubAgent execution requires an explicit parent ToolSet snapshot",
                )
            inherited_tool_set = resolver()
        if not isinstance(inherited_tool_set, InheritedToolSetV2):
            raise RuntimeV2Error(
                "invalid_subagent_tool_set",
                "SubAgent ToolSet inheritance resolver returned an invalid snapshot",
            )
        return inherited_tool_set

    def _policy_intersection_definitions(
        self,
        subagents: Sequence[SubAgent],
        inherited_tool_set: InheritedToolSetV2,
    ) -> list[ToolDefinition]:
        """Return the parent-ordered intersection permitted to every child."""
        assert self.deps.filter_tools_fn is not None
        allowed_names: set[str] | None = None
        seen: set[str] = set()
        for subagent in subagents:
            identity = subagent.id or subagent.name
            if identity in seen:
                continue
            seen.add(identity)
            filtered, names = self.deps.filter_tools_fn(
                subagent,
                inherited_tool_set=inherited_tool_set,
            )
            filtered_names = {definition.name for definition in filtered} & names
            allowed_names = (
                filtered_names if allowed_names is None else allowed_names & filtered_names
            )
        allowed_names = (allowed_names or set()) - inherited_tool_set.rebindable_tool_names
        return [
            definition
            for definition in inherited_tool_set.tool_set.definitions
            if definition.name in allowed_names
        ]

    async def _prepare_child_tool_definitions(
        self,
        *,
        subagent: SubAgent,
        available_subagents: Sequence[SubAgent],
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        abort_signal: asyncio.Event | None,
        delegation_depth: int,
        inherited_tool_set: InheritedToolSetV2,
    ) -> list[ToolDefinition]:
        """Filter and rebind nested tools without expanding the parent snapshot."""
        assert self.deps.filter_tools_fn is not None
        filtered_tools, existing_tool_names = self.deps.filter_tools_fn(
            subagent,
            inherited_tool_set=inherited_tool_set,
        )
        from src.infrastructure.plugins.v2.subagent_wasm_tool_leases_v2 import (
            rebind_inherited_wasm_tool_leases_v2,
        )

        filtered_tools = await rebind_inherited_wasm_tool_leases_v2(filtered_tools)
        existing_tool_names = {definition.name for definition in filtered_tools}
        allowed_rebindable_names = frozenset(
            existing_tool_names & inherited_tool_set.rebindable_tool_names
        )
        base_definitions = [
            definition
            for definition in filtered_tools
            if definition.name not in inherited_tool_set.rebindable_tool_names
        ]
        if not allowed_rebindable_names:
            return base_definitions

        if self.deps.operation_context_fn is None:
            from src.infrastructure.plugins.v2.boundary import current_operation_context_v2

            operation = current_operation_context_v2()
        else:
            operation = self.deps.operation_context_fn()
        inherited_tool_set.validate_generation(operation.descriptor)
        child_binding = SubAgentToolSetBindingV2(operation=operation)
        nested_definitions: list[ToolDefinition] = []
        nested_names: set[str] = set()
        assert self.deps.inject_nested_tools_fn is not None
        self.deps.inject_nested_tools_fn(
            subagent=subagent,
            available_subagents=available_subagents,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            delegation_depth=delegation_depth,
            tool_set_binding=child_binding,
            allowed_tool_names=allowed_rebindable_names,
            filtered_tools=nested_definitions,
            existing_tool_names=nested_names,
        )
        if not nested_definitions:
            return base_definitions

        nested_tool_set = await lease_operation_tool_definitions_v2(
            operation=operation,
            source_id=f"nested-subagent:{subagent.id}:depth-{delegation_depth + 1}",
            definitions=nested_definitions,
        )
        nested_by_name = {definition.name: definition for definition in nested_tool_set.definitions}
        combined_definitions: list[ToolDefinition] = []
        combined_tools: dict[str, Any] = {}
        for definition in filtered_tools:
            name = definition.name
            if name in inherited_tool_set.rebindable_tool_names:
                replacement = nested_by_name.get(name)
                if replacement is None:
                    continue
                combined_definitions.append(replacement)
                combined_tools[name] = nested_tool_set.tools[name]
                continue
            combined_definitions.append(definition)
            combined_tools[name] = inherited_tool_set.tool_set.tools[name]
        child_binding.bind(
            ToolSetV2(
                tools=MappingProxyType(combined_tools),
                definitions=tuple(combined_definitions),
                selection_trace=inherited_tool_set.tool_set.selection_trace,
            ),
            rebindable_tool_names=nested_by_name,
        )
        return combined_definitions

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

    async def execute_subagent(  # noqa: PLR0913
        self,
        subagent: SubAgent,
        available_subagents: Sequence[SubAgent],
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str = "",
        abort_signal: asyncio.Event | None = None,
        delegation_depth: int = 0,
        model_override: str | None = None,
        thinking_override: str | None = None,
        inherited_tool_set: InheritedToolSetV2 | None = None,
        run_id: str | None = None,
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
            conversation_id=conversation_id,
            memory_context=memory_context,
        )

        parent_tool_set = self._resolve_inherited_tool_set(inherited_tool_set)
        filtered_tools = await self._prepare_child_tool_definitions(
            subagent=subagent,
            available_subagents=available_subagents,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            delegation_depth=delegation_depth,
            inherited_tool_set=parent_tool_set,
        )

        process = SubAgentProcess(
            subagent=subagent,
            run_id=run_id,
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

        yield cast(
            dict[str, Any],
            AgentCompleteEvent(
                content=result.final_content if result else "",
                subagent_used=subagent.name,
                subagent_result=(result.to_event_data() if result else None),
            ).to_event_dict(),
        )

    async def execute_parallel(
        self,
        subtasks: list[Any],
        available_subagents: Sequence[SubAgent],
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str | None = None,
        route_id: str | None = None,
        abort_signal: asyncio.Event | None = None,
        inherited_tool_set: InheritedToolSetV2 | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute multiple SubAgents in parallel via ParallelScheduler."""
        from ..subagent.parallel_scheduler import ParallelScheduler

        yield cast(
            dict[str, Any],
            AgentParallelStartedEvent(
                task_count=len(subtasks),
                session_id=conversation_id or None,
                route_id=route_id,
                trace_id=route_id,
                subtasks=[
                    {
                        "id": st.id,
                        "description": st.description,
                        "agent": st.target_subagent,
                    }
                    for st in subtasks
                ],
            ).to_event_dict(),
        )

        subagent_map = {sa.name: sa for sa in available_subagents}
        parent_tool_set = self._resolve_inherited_tool_set(inherited_tool_set)
        execution_subagents = [
            subagent_map.get(st.target_subagent)
            or (available_subagents[0] if available_subagents else None)
            for st in subtasks
        ]
        current_tool_definitions = self._policy_intersection_definitions(
            [subagent for subagent in execution_subagents if subagent is not None],
            parent_tool_set,
        )

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
            conversation_id=conversation_id or "",
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

        yield cast(
            dict[str, Any],
            AgentParallelCompletedEvent(
                session_id=conversation_id or None,
                route_id=route_id,
                trace_id=route_id,
                total_tasks=len(subtasks),
                completed=len(results),
                all_succeeded=aggregated.all_succeeded,
                total_tokens=aggregated.total_tokens,
                failed_agents=list(aggregated.failed_agents),
            ).to_event_dict(),
        )

        yield cast(
            dict[str, Any],
            AgentCompleteEvent(
                content=aggregated.summary,
                orchestration_mode="parallel",
                subtask_count=len(subtasks),
                session_id=conversation_id or None,
                route_id=route_id,
                trace_id=route_id,
            ).to_event_dict(),
        )

    async def execute_chain(
        self,
        subtasks: list[Any],
        available_subagents: Sequence[SubAgent],
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str | None = None,
        route_id: str | None = None,
        abort_signal: asyncio.Event | None = None,
        inherited_tool_set: InheritedToolSetV2 | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute SubAgents as a sequential chain (pipeline)."""
        from ..subagent.chain import ChainStep, SubAgentChain

        subagent_map = {sa.name: sa for sa in available_subagents}

        ordered = self.topological_sort_subtasks(subtasks)
        chain_steps = []
        for i, st in enumerate(ordered):
            agent = subagent_map.get(st.target_subagent)
            if not agent:
                agent = available_subagents[0] if available_subagents else None
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
        parent_tool_set = self._resolve_inherited_tool_set(inherited_tool_set)
        current_tool_definitions = self._policy_intersection_definitions(
            [step.subagent for step in chain_steps],
            parent_tool_set,
        )

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
            conversation_id=conversation_id or "",
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
        yield cast(
            dict[str, Any],
            AgentCompleteEvent(
                content=(chain_result.final_summary if chain_result else ""),
                orchestration_mode="chain",
                step_count=len(chain_steps),
                session_id=conversation_id or None,
                route_id=route_id,
                trace_id=route_id,
            ).to_event_dict(),
        )

    async def execute_background(
        self,
        subagent: SubAgent,
        user_message: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        inherited_tool_set: InheritedToolSetV2 | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Launch a SubAgent for background execution (non-blocking)."""
        parent_tool_set = self._resolve_inherited_tool_set(inherited_tool_set)
        current_tool_definitions = self._policy_intersection_definitions(
            [subagent],
            parent_tool_set,
        )

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

        yield cast(
            dict[str, Any],
            AgentBackgroundLaunchedEvent(
                execution_id=execution_id,
                subagent_id=subagent.id,
                subagent_name=subagent.display_name,
                task=user_message[:200],
            ).to_event_dict(),
        )

        yield cast(
            dict[str, Any],
            AgentCompleteEvent(
                content=(
                    f"Task delegated to "
                    f"{subagent.display_name} in background "
                    f"(ID: {execution_id}). You will be "
                    "notified when it completes."
                ),
                orchestration_mode="background",
                execution_id=execution_id,
            ).to_event_dict(),
        )

    # ------------------------------------------------------------------
    # Lifecycle hooks & observability
    # ------------------------------------------------------------------

    async def emit_subagent_lifecycle_hook(
        self,
        event: dict[str, Any],
    ) -> None:
        """Emit the explicitly configured detached SubAgent lifecycle callback."""
        if self.deps.subagent_lifecycle_hook:
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

    async def runner_resolve_overrides(
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
        run_state = await registry_call_v2(
            self.deps.subagent_run_registry,
            "get_run",
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
        await registry_call_v2(
            self.deps.subagent_run_registry,
            "attach_metadata",
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

    async def runner_mark_completion(
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
        current = await registry_call_v2(
            self.deps.subagent_run_registry,
            "get_run",
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
            await registry_call_v2(
                self.deps.subagent_run_registry,
                "mark_completed",
                conversation_id=conversation_id,
                run_id=run_id,
                summary=summary,
                tokens_used=tokens_used,
                execution_time_ms=elapsed_ms,
                expected_statuses=expected,
            )
        else:
            await registry_call_v2(
                self.deps.subagent_run_registry,
                "mark_failed",
                conversation_id=conversation_id,
                run_id=run_id,
                error=result_error or "SubAgent session failed",
                execution_time_ms=elapsed_ms,
                expected_statuses=expected,
            )

    async def runner_mark_timeout(
        self,
        conversation_id: str,
        run_id: str,
        configured_timeout: float,
    ) -> None:
        """Handle TimeoutError for a SubAgent runner."""
        current = await registry_call_v2(
            self.deps.subagent_run_registry,
            "get_run",
            conversation_id,
            run_id,
        )
        if current and current.status in {
            SubAgentRunStatus.PENDING,
            SubAgentRunStatus.RUNNING,
        }:
            await registry_call_v2(
                self.deps.subagent_run_registry,
                "mark_timed_out",
                conversation_id=conversation_id,
                run_id=run_id,
                reason=(f"SubAgent session exceeded timeout ({configured_timeout}s)"),
                metadata={"timeout_seconds": configured_timeout},
                expected_statuses=[
                    SubAgentRunStatus.PENDING,
                    SubAgentRunStatus.RUNNING,
                ],
            )

    async def runner_mark_cancelled(
        self,
        conversation_id: str,
        run_id: str,
    ) -> None:
        """Handle CancelledError for a SubAgent runner."""
        current = await registry_call_v2(
            self.deps.subagent_run_registry,
            "get_run",
            conversation_id,
            run_id,
        )
        if current and current.status in {
            SubAgentRunStatus.PENDING,
            SubAgentRunStatus.RUNNING,
        }:
            await registry_call_v2(
                self.deps.subagent_run_registry,
                "mark_cancelled",
                conversation_id=conversation_id,
                run_id=run_id,
                reason="Cancelled by control tool",
                expected_statuses=[
                    SubAgentRunStatus.PENDING,
                    SubAgentRunStatus.RUNNING,
                ],
            )

    async def check_spawn_limits(
        self,
        conversation_id: str,
        current_depth: int,
        subagent_name: str,
    ) -> tuple[bool, list[dict[str, Any]]]:
        """Check depth and concurrency hard limits before spawning a SubAgent.

        Returns:
            (allowed, event_dicts) -- If not allowed, event_dicts contains
            the refusal event for the caller to emit.
        """
        # Depth limit check
        max_depth = self.deps.max_subagent_delegation_depth
        if current_depth >= max_depth:
            event = SubAgentDepthLimitedEvent(
                subagent_name=subagent_name,
                current_depth=current_depth,
                max_depth=max_depth,
            )
            return (False, [dict(event.to_event_dict())])

        # Concurrency limit check
        active_count = await registry_call_v2(
            self.deps.subagent_run_registry,
            "count_active_runs",
            conversation_id,
        )
        max_active = self.deps.max_subagent_active_runs
        if active_count >= max_active:
            queued_event = SubAgentQueuedEvent(
                subagent_id="",
                subagent_name=subagent_name,
                reason="concurrency_limit",
            )
            return (False, [dict(queued_event.to_event_dict())])

        return (True, [])

    async def runner_mark_error(
        self,
        conversation_id: str,
        run_id: str,
        exc: Exception,
        started_at: float,
    ) -> None:
        """Handle generic Exception for a SubAgent runner."""
        current = await registry_call_v2(
            self.deps.subagent_run_registry,
            "get_run",
            conversation_id,
            run_id,
        )
        if current and current.status in {
            SubAgentRunStatus.PENDING,
            SubAgentRunStatus.RUNNING,
        }:
            await registry_call_v2(
                self.deps.subagent_run_registry,
                "mark_failed",
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

    async def runner_finalize(  # noqa: PLR0913
        self,
        *,
        conversation_id: str,
        run_id: str,
        project_id: str,
        tenant_id: str,
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
        final_run = await registry_call_v2(
            self.deps.subagent_run_registry,
            "get_run",
            conversation_id,
            run_id,
        )
        if final_run is not None:
            await self._maybe_apply_workspace_task_report_from_run(
                final_run=final_run,
                tenant_id=tenant_id,
                project_id=project_id,
                subagent=subagent,
            )
        await self.emit_subagent_lifecycle_hook(
            {
                "type": "subagent_ended",
                "conversation_id": conversation_id,
                "run_id": run_id,
                "project_id": project_id,
                "tenant_id": tenant_id,
                "subagent_name": subagent.name,
                "status": (final_run.status.value if final_run else "unknown"),
                "summary": ((final_run.summary if final_run else summary) or ""),
                "error": ((final_run.error if final_run else "") or ""),
                "spawn_mode": normalized_spawn_mode,
                "thread_requested": bool(thread_requested),
                "cleanup": normalized_cleanup,
            }
        )

    async def _maybe_apply_workspace_task_report_from_run(
        self,
        *,
        final_run: Any,
        tenant_id: str,
        project_id: str,
        subagent: SubAgent,
    ) -> None:
        metadata = final_run.metadata if isinstance(final_run.metadata, dict) else {}
        workspace_id = metadata.get("workspace_id")
        root_goal_task_id = metadata.get("root_goal_task_id")
        workspace_task_id = metadata.get("workspace_task_id")
        attempt_id = metadata.get("attempt_id")
        actor_user_id = metadata.get("actor_user_id")
        leader_agent_id = metadata.get("leader_agent_id")
        if not all(
            isinstance(value, str) and value
            for value in (workspace_id, root_goal_task_id, workspace_task_id, actor_user_id)
        ):
            return
        workspace_id_str = cast("str", workspace_id)
        root_goal_task_id_str = cast("str", root_goal_task_id)
        workspace_task_id_str = cast("str", workspace_task_id)
        actor_user_id_str = cast("str", actor_user_id)

        from src.infrastructure.agent.workspace.orchestrator import (
            WorkspaceAutonomyOrchestrator,
        )

        status_value = getattr(final_run.status, "value", str(final_run.status))
        report_type = "completed"
        if status_value in {"failed", "timed_out", "killed", "cancelled"}:
            report_type = "blocked"

        summary = final_run.summary or final_run.error or f"SubAgent {subagent.name} finished"
        artifacts_raw = metadata.get("artifacts")
        artifacts = (
            [str(item) for item in artifacts_raw if item]
            if isinstance(artifacts_raw, list)
            else None
        )
        try:
            await WorkspaceAutonomyOrchestrator().apply_worker_report(
                workspace_id=workspace_id_str,
                root_goal_task_id=root_goal_task_id_str,
                task_id=workspace_task_id_str,
                attempt_id=(attempt_id if isinstance(attempt_id, str) and attempt_id else None),
                conversation_id=final_run.conversation_id,
                actor_user_id=actor_user_id_str,
                worker_agent_id=None,
                report_type=report_type,
                summary=summary,
                artifacts=artifacts,
                leader_agent_id=(leader_agent_id if isinstance(leader_agent_id, str) else None),
                report_id=final_run.run_id,
            )
        except Exception:
            logger.warning(
                "Failed to apply workspace task report from subagent run",
                extra={
                    "conversation_id": final_run.conversation_id,
                    "run_id": final_run.run_id,
                    "workspace_id": workspace_id,
                    "task_id": workspace_task_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                },
                exc_info=True,
            )

    async def launch_emit_lifecycle_hooks(
        self,
        *,
        conversation_id: str,
        run_id: str,
        project_id: str,
        tenant_id: str,
        subagent: SubAgent,
        normalized_spawn_mode: str,
        thread_requested: bool,
        normalized_cleanup: str,
        requested_model_override: str | None,
        requested_thinking_override: str | None,
    ) -> None:
        """Emit spawning + spawned lifecycle hooks for a subagent session."""
        spawning_payload = dict(
            SubAgentSpawningEvent(
                conversation_id=conversation_id,
                run_id=run_id,
                subagent_name=subagent.name,
                spawn_mode=normalized_spawn_mode,
                thread_requested=bool(thread_requested),
                cleanup=normalized_cleanup,
                model_override=requested_model_override,
                thinking_override=requested_thinking_override,
            ).to_event_dict()
        )
        spawning_payload["project_id"] = project_id
        spawning_payload["tenant_id"] = tenant_id
        await self.emit_subagent_lifecycle_hook(spawning_payload)
        await self.emit_subagent_lifecycle_hook(
            {
                "type": "subagent_spawned",
                "conversation_id": conversation_id,
                "run_id": run_id,
                "project_id": project_id,
                "tenant_id": tenant_id,
                "subagent_name": subagent.name,
                "spawn_mode": normalized_spawn_mode,
                "thread_requested": bool(thread_requested),
                "cleanup": normalized_cleanup,
            }
        )

    @staticmethod
    async def _record_launch_failure(
        registry: SubAgentRunRegistry,
        *,
        conversation_id: str,
        run_id: str,
        error: BaseException,
    ) -> None:
        expected_statuses = [
            SubAgentRunStatus.PENDING,
            SubAgentRunStatus.RUNNING,
        ]
        launch_cancelled = isinstance(error, asyncio.CancelledError) or (
            isinstance(error, RuntimeV2Error) and error.code == "detached_subagent_launch_cancelled"
        )
        if launch_cancelled:
            _ = await registry_call_v2(
                registry,
                "mark_cancelled",
                conversation_id=conversation_id,
                run_id=run_id,
                reason="Detached SubAgent launch was cancelled",
                expected_statuses=expected_statuses,
            )
        elif isinstance(error, Exception):
            _ = await registry_call_v2(
                registry,
                "mark_failed",
                conversation_id=conversation_id,
                run_id=run_id,
                error=str(error),
                expected_statuses=expected_statuses,
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
        available_subagents: Sequence[SubAgent],
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        abort_signal: asyncio.Event | None,
        model_override: str | None,
        thinking_override: str | None,
        inherited_tool_set: InheritedToolSetV2,
        run_id: str | None = None,
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
            run_id=run_id,
            available_subagents=available_subagents,
            user_message=user_message,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            model_override=model_override,
            thinking_override=thinking_override,
            inherited_tool_set=inherited_tool_set,
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

    async def _check_spawn_rejected(
        self,
        subagent: SubAgent,
        run_id: str,
        conversation_id: str,
        project_id: str,
        tenant_id: str,
    ) -> bool:
        """Validate spawn and emit rejection event if denied. Returns True if rejected."""
        assert self.deps.spawn_validator is not None
        validation = await self.deps.spawn_validator.validate_async(
            subagent_name=subagent.display_name,
            current_depth=0,
            conversation_id=conversation_id,
            requester_session_id=run_id,
        )
        if validation.allowed:
            return False
        logger.warning(
            "[SubAgentRunner] Spawn rejected for %s (run=%s): %s",
            subagent.display_name,
            run_id,
            validation.rejection_reason,
        )
        event = SubAgentSpawnRejectedEvent(
            subagent_name=subagent.display_name,
            rejection_code=(validation.rejection_code.value if validation.rejection_code else ""),
            rejection_reason=validation.rejection_reason or "",
            context=validation.context,
        )
        payload = dict(event.to_event_dict())
        payload["project_id"] = project_id
        payload["tenant_id"] = tenant_id
        await self.emit_subagent_lifecycle_hook(payload)
        return True

    async def launch_subagent_session(  # noqa: C901,PLR0912,PLR0913,PLR0915
        self,
        run_id: str,
        subagent: SubAgent,
        available_subagents: Sequence[SubAgent],
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
        run_metadata: dict[str, str] | None = None,
        inherited_tool_set: InheritedToolSetV2 | None = None,
    ) -> None:
        """Launch a detached SubAgent session tied to a run_id."""
        if self.deps.detached_subagent_task_supervisor.task_for(run_id) is not None:
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

        if self.deps.spawn_validator is not None:
            rejected = await self._check_spawn_rejected(
                subagent,
                run_id,
                conversation_id,
                project_id,
                tenant_id,
            )
            if rejected:
                return

        parent_tool_set = self._resolve_inherited_tool_set(inherited_tool_set)
        session_registry = self.deps.subagent_run_registry
        if run_metadata:
            metadata: dict[str, object] = dict(run_metadata)
            try:
                await registry_call_v2(
                    session_registry,
                    "attach_metadata",
                    conversation_id=conversation_id,
                    run_id=run_id,
                    metadata=metadata,
                )
            except Exception:
                logger.warning(
                    "Failed to attach initial subagent run metadata",
                    extra={"conversation_id": conversation_id, "run_id": run_id},
                    exc_info=True,
                )

        from src.application.services.approved_run_tool_permission_v2 import (
            current_approved_run_guard_v2,
            inherit_approved_run_guard_v2,
        )
        from src.application.services.chat_run_tool_permission_v2 import (
            current_chat_run_guard_v2,
            inherit_chat_run_guard_v2,
        )

        parent_chat_guard = current_chat_run_guard_v2()
        if parent_chat_guard is not None:
            if await parent_chat_guard.decision("delegate", "", {}) != "allow":
                raise RuntimeV2Error("chat_tool_permission_denied", "Chat delegation is not valid")
            await registry_call_v2(
                session_registry, "bind_chat_permission_authority", conversation_id, run_id,
                chat_run_id=parent_chat_guard.run_id, mode=parent_chat_guard.mode,
            )
        parent_permission_guard = current_approved_run_guard_v2()
        if parent_permission_guard is not None:
            await parent_permission_guard.require("delegate")
            await registry_call_v2(
                session_registry, "bind_approved_plan_authority", conversation_id, run_id,
                approved_run_id=parent_permission_guard.run_id,
                ceiling=parent_permission_guard.profile,
            )
        reservation = await self.deps.operation_reserver()
        try:
            parent_tool_set.validate_generation(reservation.descriptor)
        except BaseException as exc:
            await reservation.release()
            await self._record_launch_failure(
                session_registry,
                conversation_id=conversation_id,
                run_id=run_id,
                error=exc,
            )
            raise
        generation_metadata: dict[str, object] = {
            "plugin_generation": reservation.descriptor.to_payload(),
            "inherited_tool_set_generation": parent_tool_set.generation_descriptor.to_payload(),
            "inherited_tool_set_owner_operation_id": parent_tool_set.owner_operation_id,
        }
        try:
            updated_run = await registry_call_v2(
                session_registry,
                "attach_metadata",
                conversation_id=conversation_id,
                run_id=run_id,
                metadata=generation_metadata,
            )
            if updated_run is None:
                raise RuntimeV2Error(
                    "subagent_generation_metadata_rejected",
                    "detached SubAgent run rejected its exact generation descriptor",
                )
        except BaseException as exc:
            await reservation.release()
            await self._record_launch_failure(
                session_registry,
                conversation_id=conversation_id,
                run_id=run_id,
                error=exc,
            )
            raise

        start_gate = asyncio.Event()
        admission: asyncio.Future[None] = asyncio.get_running_loop().create_future()

        owner_control: SubAgentOwnerControlV2 | None = None
        execution_owner: SubAgentExecutionOwnerV2 | None = None

        async def _run_admitted_session() -> None:
            started_at = time.time()
            cancelled_by_control = False
            resolved_model_override = requested_model_override
            resolved_thinking_override = requested_thinking_override
            configured_timeout = 0.0
            summary = ""
            tokens_used: int | None = None
            execution_time_ms: int | None = None
            result_success = True
            result_error: str | None = None

            try:
                await start_gate.wait()
                (
                    resolved_model_override,
                    resolved_thinking_override,
                    configured_timeout,
                ) = await self.runner_resolve_overrides(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    requested_model=requested_model_override,
                    requested_thinking=requested_thinking_override,
                    normalized_spawn_mode=normalized_spawn_mode,
                    thread_requested=thread_requested,
                    normalized_cleanup=normalized_cleanup,
                )
                queued_payload = dict(
                    SubAgentQueuedEvent(
                        subagent_id=subagent.id,
                        subagent_name=subagent.display_name,
                    ).to_event_dict(),
                )
                queued_payload["project_id"] = project_id
                queued_payload["tenant_id"] = tenant_id
                await self.emit_subagent_lifecycle_hook(queued_payload)
                lane_wait_start = time.time()
                async with self.deps.subagent_lane_semaphore:
                    lane_wait_ms = int(
                        (time.time() - lane_wait_start) * 1000,
                    )
                    if lane_wait_ms > 0:
                        await registry_call_v2(
                            self.deps.subagent_run_registry,
                            "attach_metadata",
                            conversation_id=conversation_id,
                            run_id=run_id,
                            metadata={"lane_wait_ms": lane_wait_ms},
                        )
                    consume_coro = self.runner_consume_and_extract(
                        run_id=run_id,
                        subagent=subagent,
                        available_subagents=available_subagents,
                        user_message=user_message,
                        conversation_context=conversation_context,
                        project_id=project_id,
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        abort_signal=abort_signal,
                        model_override=resolved_model_override,
                        thinking_override=resolved_thinking_override,
                        inherited_tool_set=parent_tool_set,
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

                await self.runner_mark_completion(
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
                await self.runner_mark_timeout(
                    conversation_id,
                    run_id,
                    configured_timeout,
                )
                timeout_payload = dict(
                    SubAgentKilledEvent(
                        run_id=run_id,
                        conversation_id=conversation_id,
                        subagent_id=subagent.id,
                        subagent_name=subagent.display_name,
                        kill_reason=f"Timed out after {configured_timeout}s",
                    ).to_event_dict(),
                )
                timeout_payload["project_id"] = project_id
                timeout_payload["tenant_id"] = tenant_id
                await self.emit_subagent_lifecycle_hook(timeout_payload)
            except asyncio.CancelledError:
                cancelled_by_control = await self._settle_owner_cancellation(
                    conversation_id,
                    run_id,
                    project_id,
                    tenant_id,
                    subagent,
                    started_at,
                    (execution_owner.failure if execution_owner else None)
                    or (owner_control.failure if owner_control else None),
                )
                raise
            except Exception as exc:
                await self.runner_mark_error(
                    conversation_id,
                    run_id,
                    exc,
                    started_at,
                )
            finally:
                await self.runner_finalize(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    project_id=project_id,
                    tenant_id=tenant_id,
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

        async def _runner() -> None:
            nonlocal owner_control, execution_owner
            try:
                operation_services: dict[str, object] = {}
                async with AsyncExitStack() as stack:
                    if self.deps.session_factory is not None:
                        child_db = await stack.enter_async_context(self.deps.session_factory())
                        operation_services[OPERATION_DB_SESSION_SERVICE_V2] = child_db
                    async with reservation.admit(
                        operation_id=f"detached-subagent:{run_id}",
                        metadata={
                            "kind": "detached-subagent",
                            "run_id": run_id,
                            "conversation_id": conversation_id,
                            "subagent_id": subagent.id,
                            "subagent_name": subagent.name,
                            "spawn_mode": normalized_spawn_mode,
                        },
                        services=operation_services,
                    ) as child_operation:
                        inherit_approved_run_guard_v2(parent_permission_guard, child_operation)
                        inherit_chat_run_guard_v2(parent_chat_guard, child_operation)
                        parent_tool_set.validate_generation(child_operation.descriptor)
                        child_registry = self.deps.subagent_run_registry
                        if child_registry is not session_registry:
                            raise RuntimeV2Error(
                                "subagent_registry_generation_mismatch",
                                "detached SubAgent resolved a different generation registry",
                            )
                        async with AsyncExitStack() as execution_stack:
                            if isinstance(child_registry, AsyncSubAgentRunRegistryV2):
                                execution_owner = await execution_stack.enter_async_context(
                                    child_registry.own_execution(conversation_id, run_id)
                                )
                            if not admission.done():
                                admission.set_result(None)
                            async with SubAgentOwnerControlV2(
                                lambda: self.deps.subagent_run_registry,
                                conversation_id,
                                run_id,
                                self.deps.factory.control_channel if self.deps.factory else None,
                            ) as owner_control:
                                await _run_admitted_session()
            except BaseException as exc:
                if not admission.done():
                    admission.set_exception(exc)
                raise

        def _settle_admission_from_task(completed: asyncio.Task[None]) -> None:
            if admission.done():
                return
            if completed.cancelled():
                admission.set_exception(
                    RuntimeV2Error(
                        "detached_subagent_launch_cancelled",
                        "detached SubAgent task was cancelled before generation admission",
                    )
                )
                return
            error = completed.exception()
            admission.set_exception(
                error
                or RuntimeV2Error(
                    "detached_subagent_launch_terminated",
                    "detached SubAgent task terminated before generation admission",
                )
            )

        task: asyncio.Task[None] | None = None
        try:
            task = self.deps.detached_subagent_task_supervisor.create_task(
                run_id=run_id,
                coroutine=_runner(),
                name=f"subagent-session-{run_id}",
                context=detached_operation_task_context_v2(),
            )
            task.add_done_callback(_settle_admission_from_task)
            await admission
            await self.launch_emit_lifecycle_hooks(
                conversation_id=conversation_id,
                run_id=run_id,
                project_id=project_id,
                tenant_id=tenant_id,
                subagent=subagent,
                normalized_spawn_mode=normalized_spawn_mode,
                thread_requested=thread_requested,
                normalized_cleanup=normalized_cleanup,
                requested_model_override=requested_model_override,
                requested_thinking_override=requested_thinking_override,
            )
            task_is_owned = self.deps.detached_subagent_task_supervisor.task_for(run_id) is task
            if task.cancelled() or task.cancelling() or task.done() or not task_is_owned:
                raise RuntimeV2Error(
                    "detached_subagent_launch_cancelled",
                    "detached SubAgent task stopped before its launch gate opened",
                )
        except BaseException as exc:
            await self._record_launch_failure(
                session_registry,
                conversation_id=conversation_id,
                run_id=run_id,
                error=exc,
            )
            if task is not None:
                _ = task.cancel()
                _ = await asyncio.gather(task, return_exceptions=True)
                self.deps.detached_subagent_task_supervisor.discard(run_id, task)
            await reservation.release()
            raise
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

            def deliver(
                memory: SubAgentRunRegistry,
                attempt: int = attempt,
                attempts_used: int = attempts_used,
                last_error: str = last_error,
            ) -> object:
                run = memory.get_run(
                    conversation_id,
                    run_id,
                )
                if not run or run.status not in terminal_statuses:
                    return True

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

                return memory.attach_metadata(
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

            try:
                updated_run = await registry_transaction_v2(
                    self.deps.subagent_run_registry, deliver, write=True
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
            last_error = last_error or "announce metadata update conflict"

            if attempt < max_retries:
                delay_seconds = (self.deps.subagent_announce_retry_delay_ms * (2**attempt)) / 1000.0
                await asyncio.sleep(delay_seconds)

        def giveup(memory: SubAgentRunRegistry) -> None:
            run = memory.get_run(
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
            memory.attach_metadata(
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

        await registry_transaction_v2(self.deps.subagent_run_registry, giveup, write=True)

    async def _settle_owner_cancellation(
        self,
        conversation_id: str,
        run_id: str,
        project_id: str,
        tenant_id: str,
        subagent: SubAgent,
        started_at: float,
        failure: Exception | None,
    ) -> bool:
        if failure is not None:
            await self.runner_mark_error(conversation_id, run_id, failure, started_at)
            return False
        await self.runner_mark_cancelled(conversation_id, run_id)
        payload = dict(
            SubAgentKilledEvent(
                run_id=run_id,
                conversation_id=conversation_id,
                subagent_id=subagent.id,
                subagent_name=subagent.display_name,
                kill_reason="Cancelled by control",
            ).to_event_dict()
        )
        payload["project_id"] = project_id
        payload["tenant_id"] = tenant_id
        await self.emit_subagent_lifecycle_hook(payload)
        return True

    async def cancel_subagent_session(self, run_id: str) -> bool:
        """Cancel a detached SubAgent session by run_id."""
        supervisor = self.deps.detached_subagent_task_supervisor
        task = supervisor.task_for(run_id)
        if task is None or not supervisor.cancel(run_id):
            return False
        done, _ = await asyncio.wait({task}, timeout=5)
        return task in done

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
