# pyright: reportUninitializedInstanceVariable=false
"""SubAgent tool builder extracted from ReActAgent.

Constructs ToolDefinition instances for SubAgent delegation, session management,
and nested orchestration. Uses an explicit deps dataclass (no back-references).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.domain.model.agent.agent_role import (
    ROLE_DEFAULTS,
    AgentRole,
)
from src.domain.model.agent.subagent import SubAgent
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

from .processor import ToolDefinition
from .subagent_registry_authority import (
    SubAgentRunRegistryResolverV2,
    require_subagent_run_registry_v2,
)
from .subagent_router import subagent_allows_tool
from .subagent_tool_set_v2 import InheritedToolSetV2, SubAgentToolSetBindingV2

if TYPE_CHECKING:
    pass


@dataclass
class SubAgentToolBuilderDeps:
    """Dependencies injected into SubAgentToolBuilder.

    Holds references to shared registries, limits, and callback functions
    required for building SubAgent tool definitions.
    """

    # -- Shared registries --
    subagent_run_registry_resolver: SubAgentRunRegistryResolverV2

    # -- SubAgent config --
    enable_subagent_as_tool: bool = True
    max_subagent_delegation_depth: int = 2
    max_subagent_active_runs: int = 16
    max_subagent_active_runs_per_lineage: int = 8
    max_subagent_children_per_requester: int = 8

    # -- Spawn validation (optional, Phase 1 lifecycle hardening) --
    spawn_validator: Any = None

    # -- SubAgent router (optional) --
    subagent_router: Any = None

    # -- Role-based capabilities (optional, set by orchestrator) --
    agent_role: AgentRole | None = None

    # -- Callbacks to ReActAgent / Runner (set after init) --
    get_observability_stats_fn: Callable[[], dict[str, int]] | None = None
    execute_subagent_fn: Callable[..., Any] | None = None
    launch_session_fn: Callable[..., Coroutine[Any, Any, None]] | None = None
    cancel_session_fn: Callable[..., Coroutine[Any, Any, bool]] | None = None

    @property
    def subagent_run_registry(self) -> SubAgentRunRegistry:
        """Resolve the registry from the exact V2 operation on every access."""
        return require_subagent_run_registry_v2(self.subagent_run_registry_resolver)


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
        *,
        inherited_tool_set: InheritedToolSetV2,
    ) -> tuple[list[ToolDefinition], set[str]]:
        """Apply child policy as a strict subset of one inherited parent ToolSet."""
        parent_tool_set = inherited_tool_set.tool_set
        parent_tools = parent_tool_set.tools
        allowed_names = set(parent_tools)
        if self.deps.subagent_router:
            filtered_raw = self.deps.subagent_router.filter_tools(
                subagent,
                dict(parent_tools),
            )
            if not isinstance(filtered_raw, Mapping):
                raise RuntimeV2Error(
                    "invalid_subagent_tool_filter",
                    "SubAgent router must return a mapping subset of the parent ToolSet",
                )
            for name, tool in filtered_raw.items():
                if (
                    not isinstance(name, str)
                    or name not in parent_tools
                    or parent_tools[name] is not tool
                ):
                    raise RuntimeV2Error(
                        "subagent_tool_set_expansion",
                        "SubAgent router cannot add or replace parent ToolSet entries",
                    )
            allowed_names = set(filtered_raw)

        role_denied = self._get_role_denied_tools()
        allowed_names.difference_update(role_denied)
        known_tool_names = set(parent_tools)
        filtered_tools = [
            tool
            for tool in parent_tool_set.definitions
            if tool.name in allowed_names
            and subagent_allows_tool(subagent, tool.name, known_tool_names)
        ]

        existing_tool_names = {tool.name for tool in filtered_tools}
        return filtered_tools, existing_tool_names

    # ------------------------------------------------------------------
    # Role-based capability helpers
    # ------------------------------------------------------------------

    def _get_role_denied_tools(self) -> frozenset[str]:
        """Return denied tools for the current agent role, or empty frozenset."""
        role = self.deps.agent_role
        if role is None:
            return frozenset()
        capabilities = ROLE_DEFAULTS.get(role)
        if capabilities is None:
            return frozenset()
        return capabilities.denied_tools

    def _role_can_spawn(self) -> bool:
        """Check if the current agent role allows spawning sub-agents."""
        role = self.deps.agent_role
        if role is None:
            return True
        capabilities = ROLE_DEFAULTS.get(role)
        if capabilities is None:
            return True
        return capabilities.can_spawn

    # ------------------------------------------------------------------
    # Nested tool injection
    # ------------------------------------------------------------------

    def inject_nested_tools(
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
        tool_set_binding: SubAgentToolSetBindingV2,
        allowed_tool_names: frozenset[str],
        filtered_tools: list[ToolDefinition],
        existing_tool_names: set[str],
    ) -> None:
        """Inject SubAgent delegation tools for nested orchestration (bounded depth).

        Modifies filtered_tools and existing_tool_names in-place.
        """
        max_delegation_depth = self.deps.max_subagent_delegation_depth
        if not (
            available_subagents
            and self.deps.enable_subagent_as_tool
            and delegation_depth < max_delegation_depth
            and self._role_can_spawn()
        ):
            return

        nested_candidates = [
            sa for sa in available_subagents if sa.enabled and sa.id != subagent.id
        ]
        if not nested_candidates:
            return

        nested_map = {sa.name: sa for sa in nested_candidates}
        nested_descriptions = {
            sa.name: (sa.trigger.description if sa.trigger else sa.display_name)
            for sa in nested_candidates
        }
        nested_depth = delegation_depth + 1

        def _append_tool_def(td: ToolDefinition) -> None:
            if td.name not in allowed_tool_names or td.name in existing_tool_names:
                return
            filtered_tools.append(td)
            existing_tool_names.add(td.name)

        delegate_cb, spawn_cb, cancel_cb = self.build_nested_subagent_callbacks(
            nested_map=nested_map,
            available_subagents=available_subagents,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            delegation_depth=delegation_depth,
            tool_set_binding=tool_set_binding,
        )

        for td in self.make_nested_session_tool_defs(
            conversation_id=conversation_id,
            nested_depth=nested_depth,
            max_delegation_depth=max_delegation_depth,
            nested_map=nested_map,
            nested_descriptions=nested_descriptions,
            cancel_callback=cancel_cb,
            restart_callback=spawn_cb,
        ):
            _append_tool_def(td)

        for td in self.make_nested_delegate_tool_defs(
            nested_candidates=nested_candidates,
            nested_map=nested_map,
            nested_descriptions=nested_descriptions,
            delegate_callback=delegate_cb,
            conversation_id=conversation_id,
            nested_depth=nested_depth,
        ):
            _append_tool_def(td)

    # ------------------------------------------------------------------
    # Nested callback builders
    # ------------------------------------------------------------------

    def build_nested_subagent_callbacks(
        self,
        *,
        nested_map: dict[str, SubAgent],
        available_subagents: Sequence[SubAgent],
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        abort_signal: asyncio.Event | None,
        delegation_depth: int,
        tool_set_binding: SubAgentToolSetBindingV2,
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
            workspace_task_id: str | None = None,
            on_event: Callable[[dict[str, Any]], None] | None = None,
        ) -> str:
            del workspace_task_id
            target = nested_map.get(subagent_name)
            if not target:
                return f"SubAgent '{subagent_name}' not found"

            assert execute_subagent_fn is not None
            events: list[dict[str, Any]] = []
            async for evt in execute_subagent_fn(
                subagent=target,
                available_subagents=available_subagents,
                user_message=task,
                conversation_context=conversation_context,
                project_id=project_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                abort_signal=abort_signal,
                delegation_depth=delegation_depth + 1,
                inherited_tool_set=tool_set_binding.require(),
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
                available_subagents=available_subagents,
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
                inherited_tool_set=tool_set_binding.require(),
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

    def make_nested_session_tool_defs(
        self,
        *,
        conversation_id: str,
        nested_depth: int,
        max_delegation_depth: int,
        nested_map: dict[str, Any],
        nested_descriptions: dict[str, str],
        cancel_callback: Callable[..., Coroutine[Any, Any, bool]],
        restart_callback: Callable[..., Coroutine[Any, Any, str]],
    ) -> list[ToolDefinition]:
        """Build nested session ToolDefinitions with captured dependencies."""
        from ..tools.subagent_sessions import make_nested_session_tool_defs

        nested_visibility = "tree" if nested_depth < max_delegation_depth else "self"
        return make_nested_session_tool_defs(
            run_registry=self.deps.subagent_run_registry,
            conversation_id=conversation_id,
            requester_session_key=conversation_id,
            visibility_default=nested_visibility,
            observability_stats_provider=self.deps.get_observability_stats_fn,
            subagent_names=list(nested_map.keys()),
            subagent_descriptions=nested_descriptions,
            cancel_callback=cancel_callback,
            restart_callback=restart_callback,
            max_active_runs=self.deps.max_subagent_active_runs,
            max_active_runs_per_lineage=self.deps.max_subagent_active_runs_per_lineage,
            max_children_per_requester=self.deps.max_subagent_children_per_requester,
            delegation_depth=nested_depth,
            max_delegation_depth=self.deps.max_subagent_delegation_depth,
        )

    # ------------------------------------------------------------------
    # Delegate tool appenders
    # ------------------------------------------------------------------

    def make_nested_delegate_tool_defs(
        self,
        *,
        nested_candidates: list[SubAgent],
        nested_map: dict[str, Any],
        nested_descriptions: dict[str, str],
        delegate_callback: Callable[..., Coroutine[Any, Any, str]],
        conversation_id: str,
        nested_depth: int,
    ) -> list[ToolDefinition]:
        """Build nested delegate ToolDefinitions with captured dependencies."""
        from ..tools.delegate_subagent import make_nested_delegate_tool_defs

        return make_nested_delegate_tool_defs(
            subagent_names=list(nested_map.keys()),
            subagent_descriptions=nested_descriptions,
            execute_callback=delegate_callback,
            run_registry=self.deps.subagent_run_registry,
            conversation_id=conversation_id,
            delegation_depth=nested_depth,
            max_active_runs=self.deps.max_subagent_active_runs,
            include_parallel=(len(nested_candidates) >= 2),
        )

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
        max_delegation_depth: int | None = None,
        max_active_runs: int | None = None,
        max_active_runs_per_lineage: int | None = None,
        max_children_per_requester: int | None = None,
    ) -> list[ToolDefinition]:
        """Build and append all SubAgent tool definitions to tools list."""
        from ..tools.delegate_subagent import (
            make_delegate_tool_defs,
        )
        from ..tools.subagent_sessions import (
            make_session_tool_defs,
        )

        effective_max_delegation_depth = (
            max_delegation_depth
            if max_delegation_depth is not None
            else self.deps.max_subagent_delegation_depth
        )
        effective_max_active_runs = (
            max_active_runs if max_active_runs is not None else self.deps.max_subagent_active_runs
        )
        effective_max_active_runs_per_lineage = (
            max_active_runs_per_lineage
            if max_active_runs_per_lineage is not None
            else self.deps.max_subagent_active_runs_per_lineage
        )
        effective_max_children_per_requester = (
            max_children_per_requester
            if max_children_per_requester is not None
            else self.deps.max_subagent_children_per_requester
        )

        delegate_definitions = make_delegate_tool_defs(
            execute_callback=delegate_callback,
            run_registry=self.deps.subagent_run_registry,
            conversation_id=conversation_id,
            subagent_names=list(subagent_map.keys()),
            subagent_descriptions=subagent_descriptions,
            delegation_depth=0,
            max_active_runs=effective_max_active_runs,
            include_parallel=len(enabled_subagents) >= 2,
        )
        tools_to_use.append(delegate_definitions[0])
        tools_to_use.extend(
            make_session_tool_defs(
                run_registry=self.deps.subagent_run_registry,
                conversation_id=conversation_id,
                requester_session_key=conversation_id,
                visibility_default="tree",
                observability_stats_provider=self.deps.get_observability_stats_fn,
                subagent_names=list(subagent_map.keys()),
                subagent_descriptions=subagent_descriptions,
                spawn_callback=spawn_callback,
                cancel_callback=cancel_callback,
                max_active_runs=effective_max_active_runs,
                max_active_runs_per_lineage=effective_max_active_runs_per_lineage,
                max_children_per_requester=effective_max_children_per_requester,
                delegation_depth=0,
                max_delegation_depth=effective_max_delegation_depth,
            )
        )
        if len(delegate_definitions) > 1:
            tools_to_use.append(delegate_definitions[1])

        return tools_to_use
