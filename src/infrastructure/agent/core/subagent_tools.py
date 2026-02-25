# pyright: reportUninitializedInstanceVariable=false
"""SubAgent tool builder extracted from ReActAgent.

Constructs ToolDefinition instances for SubAgent delegation, session management,
and nested orchestration. Uses an explicit deps dataclass (no back-references).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.domain.model.agent.subagent import SubAgent

from .processor import ToolDefinition

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class SubAgentToolBuilderDeps:
    """Dependencies injected into SubAgentToolBuilder.

    Holds references to shared registries, limits, and callback functions
    required for building SubAgent tool definitions.
    """

    # -- Shared registries --
    subagent_run_registry: Any

    # -- SubAgent config --
    subagents: list[SubAgent] = field(default_factory=list)
    enable_subagent_as_tool: bool = True
    max_subagent_delegation_depth: int = 2
    max_subagent_active_runs: int = 16
    max_subagent_active_runs_per_lineage: int = 8
    max_subagent_children_per_requester: int = 8

    # -- SubAgent router (optional) --
    subagent_router: Any = None

    # -- Callbacks to ReActAgent / Runner (set after init) --
    get_current_tools_fn: Callable[..., tuple[dict[str, Any], list[ToolDefinition]]] | None = None
    get_observability_stats_fn: Callable[[], dict[str, int]] | None = None
    execute_subagent_fn: Callable[..., Any] | None = None
    launch_session_fn: Callable[..., Coroutine[Any, Any, None]] | None = None
    cancel_session_fn: Callable[..., Coroutine[Any, Any, bool]] | None = None


class SubAgentToolBuilder:
    """Builds SubAgent-related ToolDefinition instances.

    Extracted from ReActAgent to reduce file size. Uses an explicit
    deps dataclass instead of back-references.
    """

    def __init__(self, deps: SubAgentToolBuilderDeps) -> None:
        self.deps = deps

    # ------------------------------------------------------------------
    # Tool filtering
    # ------------------------------------------------------------------

    def filter_tools(
        self,
        subagent: SubAgent,
    ) -> tuple[list[ToolDefinition], set[str]]:
        """Filter tools for SubAgent permissions and return mutable collections."""
        from .tool_converter import convert_tools

        assert self.deps.get_current_tools_fn is not None
        current_raw_tools, current_tool_definitions = self.deps.get_current_tools_fn()
        if self.deps.subagent_router:
            filtered_raw = self.deps.subagent_router.filter_tools(
                subagent,
                current_raw_tools,
            )
            filtered_tools = list(convert_tools(filtered_raw))
        else:
            filtered_tools = list(current_tool_definitions)
        existing_tool_names = {tool.name for tool in filtered_tools}
        return filtered_tools, existing_tool_names

    # ------------------------------------------------------------------
    # Nested tool injection
    # ------------------------------------------------------------------

    def inject_nested_tools(
        self,
        *,
        subagent: SubAgent,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        abort_signal: asyncio.Event | None,
        delegation_depth: int,
        filtered_tools: list[ToolDefinition],
        existing_tool_names: set[str],
    ) -> None:
        """Inject SubAgent delegation tools for nested orchestration (bounded depth).

        Modifies filtered_tools and existing_tool_names in-place.
        """
        max_delegation_depth = self.deps.max_subagent_delegation_depth
        if not (
            self.deps.subagents
            and self.deps.enable_subagent_as_tool
            and delegation_depth < max_delegation_depth
        ):
            return

        nested_candidates = [
            sa for sa in self.deps.subagents if sa.enabled and sa.id != subagent.id
        ]
        if not nested_candidates:
            return

        nested_map = {sa.name: sa for sa in nested_candidates}
        nested_descriptions = {
            sa.name: (sa.trigger.description if sa.trigger else sa.display_name)
            for sa in nested_candidates
        }
        nested_depth = delegation_depth + 1

        def _append_nested_tool(tool_instance: Any) -> None:
            if tool_instance.name in existing_tool_names:
                return
            filtered_tools.append(
                ToolDefinition(
                    name=tool_instance.name,
                    description=tool_instance.description,
                    parameters=tool_instance.get_parameters_schema(),
                    execute=tool_instance.execute,
                    _tool_instance=tool_instance,
                )
            )
            existing_tool_names.add(tool_instance.name)

        delegate_cb, spawn_cb, cancel_cb = self.build_nested_subagent_callbacks(
            nested_map=nested_map,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            delegation_depth=delegation_depth,
        )

        self.append_nested_session_tools(
            append_fn=_append_nested_tool,
            conversation_id=conversation_id,
            nested_depth=nested_depth,
            max_delegation_depth=max_delegation_depth,
            nested_map=nested_map,
            nested_descriptions=nested_descriptions,
            cancel_callback=cancel_cb,
            restart_callback=spawn_cb,
        )

        self.append_nested_delegate_tools(
            append_fn=_append_nested_tool,
            nested_candidates=nested_candidates,
            nested_map=nested_map,
            nested_descriptions=nested_descriptions,
            delegate_callback=delegate_cb,
            conversation_id=conversation_id,
            nested_depth=nested_depth,
        )

    # ------------------------------------------------------------------
    # Nested callback builders
    # ------------------------------------------------------------------

    def build_nested_subagent_callbacks(
        self,
        *,
        nested_map: dict[str, SubAgent],
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        abort_signal: asyncio.Event | None,
        delegation_depth: int,
    ) -> tuple[
        Callable[..., Coroutine[Any, Any, str]],
        Callable[..., Coroutine[Any, Any, str]],
        Callable[..., Coroutine[Any, Any, bool]],
    ]:
        """Build nested delegate, spawn and cancel callbacks for SubAgent tools."""

        execute_subagent_fn = self.deps.execute_subagent_fn
        launch_session_fn = self.deps.launch_session_fn
        cancel_session_fn = self.deps.cancel_session_fn

        async def _nested_delegate_callback(
            subagent_name: str,
            task: str,
            on_event: Callable[[dict[str, Any]], None] | None = None,
        ) -> str:
            target = nested_map.get(subagent_name)
            if not target:
                return f"SubAgent '{subagent_name}' not found"

            assert execute_subagent_fn is not None
            events: list[dict[str, Any]] = []
            async for evt in execute_subagent_fn(
                subagent=target,
                user_message=task,
                conversation_context=conversation_context,
                project_id=project_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                abort_signal=abort_signal,
                delegation_depth=delegation_depth + 1,
            ):
                if on_event:
                    event_type = evt.get("type")
                    if event_type not in {"complete", "error"}:
                        on_event(evt)
                events.append(evt)

            complete_evt = next(
                (event for event in events if event.get("type") == "complete"),
                None,
            )
            if not complete_evt:
                return "SubAgent execution completed but no result returned"

            data = complete_evt.get("data", {})
            content = data.get("content", "")
            subagent_result = data.get("subagent_result")
            if subagent_result:
                summary = subagent_result.get("summary", content)
                tokens = subagent_result.get("tokens_used", 0)
                return (
                    f"[SubAgent '{subagent_name}' completed]\n"
                    f"Result: {summary}\n"
                    f"Tokens used: {tokens}"
                )

            return content or "SubAgent completed with no output"

        async def _nested_spawn_callback(
            subagent_name: str,
            task: str,
            run_id: str,
            **spawn_options: Any,
        ) -> str:
            target = nested_map.get(subagent_name)
            if not target:
                raise ValueError(f"SubAgent '{subagent_name}' not found")
            assert launch_session_fn is not None
            await launch_session_fn(
                run_id=run_id,
                subagent=target,
                user_message=task,
                conversation_id=conversation_id,
                conversation_context=conversation_context,
                project_id=project_id,
                tenant_id=tenant_id,
                abort_signal=abort_signal,
                model_override=(str(spawn_options.get("model") or "").strip() or None),
                thinking_override=(str(spawn_options.get("thinking") or "").strip() or None),
                spawn_mode=str(spawn_options.get("spawn_mode") or "run"),
                thread_requested=bool(spawn_options.get("thread_requested")),
                cleanup=str(spawn_options.get("cleanup") or "keep"),
            )
            return run_id

        async def _nested_cancel_callback(run_id: str) -> bool:
            assert cancel_session_fn is not None
            return await cancel_session_fn(run_id)

        return (
            _nested_delegate_callback,
            _nested_spawn_callback,
            _nested_cancel_callback,
        )

    # ------------------------------------------------------------------
    # Session tool appenders
    # ------------------------------------------------------------------

    def append_nested_session_tools(
        self,
        *,
        append_fn: Callable[[Any], None],
        conversation_id: str,
        nested_depth: int,
        max_delegation_depth: int,
        nested_map: dict[str, Any],
        nested_descriptions: dict[str, str],
        cancel_callback: Callable[..., Coroutine[Any, Any, bool]],
        restart_callback: Callable[..., Coroutine[Any, Any, str]],
    ) -> None:
        """Append session management tools (list, history, wait, timeline, overview, control)."""
        from ..tools.subagent_sessions import (
            SessionsHistoryTool,
            SessionsListTool,
            SessionsOverviewTool,
            SessionsTimelineTool,
            SessionsWaitTool,
            SubAgentsControlTool,
        )

        nested_visibility = "tree" if nested_depth < max_delegation_depth else "self"
        append_fn(
            SessionsListTool(
                run_registry=self.deps.subagent_run_registry,
                conversation_id=conversation_id,
                requester_session_key=conversation_id,
                visibility_default=nested_visibility,
            )
        )
        append_fn(
            SessionsHistoryTool(
                run_registry=self.deps.subagent_run_registry,
                conversation_id=conversation_id,
                requester_session_key=conversation_id,
                visibility_default=nested_visibility,
            )
        )
        append_fn(
            SessionsWaitTool(
                run_registry=self.deps.subagent_run_registry,
                conversation_id=conversation_id,
            )
        )
        append_fn(
            SessionsTimelineTool(
                run_registry=self.deps.subagent_run_registry,
                conversation_id=conversation_id,
            )
        )
        append_fn(
            SessionsOverviewTool(
                run_registry=self.deps.subagent_run_registry,
                conversation_id=conversation_id,
                requester_session_key=conversation_id,
                visibility_default=nested_visibility,
                observability_stats_provider=(self.deps.get_observability_stats_fn),
            )
        )
        append_fn(
            SubAgentsControlTool(
                run_registry=self.deps.subagent_run_registry,
                conversation_id=conversation_id,
                subagent_names=list(nested_map.keys()),
                subagent_descriptions=nested_descriptions,
                cancel_callback=cancel_callback,
                restart_callback=restart_callback,
                max_active_runs=self.deps.max_subagent_active_runs,
                max_active_runs_per_lineage=(self.deps.max_subagent_active_runs_per_lineage),
                max_children_per_requester=(self.deps.max_subagent_children_per_requester),
                requester_session_key=conversation_id,
                delegation_depth=nested_depth,
                max_delegation_depth=(self.deps.max_subagent_delegation_depth),
            )
        )

    # ------------------------------------------------------------------
    # Delegate tool appenders
    # ------------------------------------------------------------------

    def append_nested_delegate_tools(
        self,
        *,
        append_fn: Callable[[Any], None],
        nested_candidates: list[SubAgent],
        nested_map: dict[str, Any],
        nested_descriptions: dict[str, str],
        delegate_callback: Callable[..., Coroutine[Any, Any, str]],
        conversation_id: str,
        nested_depth: int,
    ) -> None:
        """Append delegate and parallel-delegate tools for nested SubAgent invocation."""
        from ..tools.delegate_subagent import (
            DelegateSubAgentTool,
            ParallelDelegateSubAgentTool,
        )

        nested_delegate_tool = DelegateSubAgentTool(
            subagent_names=list(nested_map.keys()),
            subagent_descriptions=nested_descriptions,
            execute_callback=delegate_callback,
            run_registry=self.deps.subagent_run_registry,
            conversation_id=conversation_id,
            delegation_depth=nested_depth,
            max_active_runs=self.deps.max_subagent_active_runs,
        )
        append_fn(nested_delegate_tool)

        if len(nested_candidates) >= 2:
            nested_parallel_tool = ParallelDelegateSubAgentTool(
                subagent_names=list(nested_map.keys()),
                subagent_descriptions=nested_descriptions,
                execute_callback=delegate_callback,
                run_registry=self.deps.subagent_run_registry,
                conversation_id=conversation_id,
                delegation_depth=nested_depth,
                max_active_runs=self.deps.max_subagent_active_runs,
            )
            append_fn(nested_parallel_tool)

    # ------------------------------------------------------------------
    # Top-level tool definitions builder
    # ------------------------------------------------------------------

    def build_subagent_tool_definitions(
        self,
        *,
        subagent_map: dict[str, Any],
        subagent_descriptions: dict[str, str],
        enabled_subagents: list[Any],
        delegate_callback: Any,
        spawn_callback: Any,
        cancel_callback: Any,
        conversation_id: str,
        tools_to_use: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        """Build and append all SubAgent tool definitions to tools list."""
        from ..tools.delegate_subagent import (
            DelegateSubAgentTool,
            ParallelDelegateSubAgentTool,
        )
        from ..tools.subagent_sessions import (
            SessionsAckTool,
            SessionsHistoryTool,
            SessionsListTool,
            SessionsOverviewTool,
            SessionsSendTool,
            SessionsSpawnTool,
            SessionsTimelineTool,
            SessionsWaitTool,
            SubAgentsControlTool,
        )

        def _to_td(tool_instance: Any) -> ToolDefinition:
            return ToolDefinition(
                name=tool_instance.name,
                description=tool_instance.description,
                parameters=tool_instance.get_parameters_schema(),
                execute=tool_instance.execute,
                _tool_instance=tool_instance,
            )

        delegate_tool = DelegateSubAgentTool(
            subagent_names=list(subagent_map.keys()),
            subagent_descriptions=subagent_descriptions,
            execute_callback=delegate_callback,
            run_registry=self.deps.subagent_run_registry,
            conversation_id=conversation_id,
            delegation_depth=0,
            max_active_runs=self.deps.max_subagent_active_runs,
        )
        tools_to_use.append(_to_td(delegate_tool))

        sessions_spawn_tool = SessionsSpawnTool(
            subagent_names=list(subagent_map.keys()),
            subagent_descriptions=subagent_descriptions,
            spawn_callback=spawn_callback,
            run_registry=self.deps.subagent_run_registry,
            conversation_id=conversation_id,
            max_active_runs=self.deps.max_subagent_active_runs,
            max_active_runs_per_lineage=(self.deps.max_subagent_active_runs_per_lineage),
            max_children_per_requester=(self.deps.max_subagent_children_per_requester),
            requester_session_key=conversation_id,
            delegation_depth=0,
            max_delegation_depth=(self.deps.max_subagent_delegation_depth),
        )
        tools_to_use.append(_to_td(sessions_spawn_tool))

        sessions_send_tool = SessionsSendTool(
            run_registry=self.deps.subagent_run_registry,
            conversation_id=conversation_id,
            spawn_callback=spawn_callback,
            max_active_runs=self.deps.max_subagent_active_runs,
            max_active_runs_per_lineage=(self.deps.max_subagent_active_runs_per_lineage),
            max_children_per_requester=(self.deps.max_subagent_children_per_requester),
            requester_session_key=conversation_id,
            delegation_depth=0,
            max_delegation_depth=(self.deps.max_subagent_delegation_depth),
        )
        tools_to_use.append(_to_td(sessions_send_tool))

        tools_to_use.append(
            _to_td(
                SessionsListTool(
                    run_registry=self.deps.subagent_run_registry,
                    conversation_id=conversation_id,
                    requester_session_key=conversation_id,
                    visibility_default="tree",
                )
            )
        )

        tools_to_use.append(
            _to_td(
                SessionsHistoryTool(
                    run_registry=self.deps.subagent_run_registry,
                    conversation_id=conversation_id,
                    requester_session_key=conversation_id,
                    visibility_default="tree",
                )
            )
        )

        tools_to_use.append(
            _to_td(
                SessionsWaitTool(
                    run_registry=self.deps.subagent_run_registry,
                    conversation_id=conversation_id,
                )
            )
        )

        tools_to_use.append(
            _to_td(
                SessionsAckTool(
                    run_registry=self.deps.subagent_run_registry,
                    conversation_id=conversation_id,
                    requester_session_key=conversation_id,
                )
            )
        )

        tools_to_use.append(
            _to_td(
                SessionsTimelineTool(
                    run_registry=self.deps.subagent_run_registry,
                    conversation_id=conversation_id,
                )
            )
        )

        tools_to_use.append(
            _to_td(
                SessionsOverviewTool(
                    run_registry=self.deps.subagent_run_registry,
                    conversation_id=conversation_id,
                    requester_session_key=conversation_id,
                    visibility_default="tree",
                    observability_stats_provider=(self.deps.get_observability_stats_fn),
                )
            )
        )

        subagents_control_tool = SubAgentsControlTool(
            run_registry=self.deps.subagent_run_registry,
            conversation_id=conversation_id,
            subagent_names=list(subagent_map.keys()),
            subagent_descriptions=subagent_descriptions,
            cancel_callback=cancel_callback,
            restart_callback=spawn_callback,
            max_active_runs=self.deps.max_subagent_active_runs,
            max_active_runs_per_lineage=(self.deps.max_subagent_active_runs_per_lineage),
            max_children_per_requester=(self.deps.max_subagent_children_per_requester),
            requester_session_key=conversation_id,
            delegation_depth=0,
            max_delegation_depth=(self.deps.max_subagent_delegation_depth),
        )
        tools_to_use.append(_to_td(subagents_control_tool))

        # Inject parallel delegation tool when 2+ SubAgents available
        if len(enabled_subagents) >= 2:
            parallel_tool = ParallelDelegateSubAgentTool(
                subagent_names=list(subagent_map.keys()),
                subagent_descriptions=subagent_descriptions,
                execute_callback=delegate_callback,
                run_registry=self.deps.subagent_run_registry,
                conversation_id=conversation_id,
                delegation_depth=0,
                max_active_runs=self.deps.max_subagent_active_runs,
            )
            tools_to_use.append(_to_td(parallel_tool))

        return tools_to_use
