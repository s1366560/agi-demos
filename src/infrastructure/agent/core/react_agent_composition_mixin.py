# pyright: reportUninitializedInstanceVariable=false
"""Composition mixin extracted from ``react_agent.py``.

Hosts thin classmethod / staticmethod wrappers that delegate to the
``react_agent_tool_policy`` and ``react_agent_workspace_context`` helper
modules, plus the SubAgent tool-composition helpers that delegate to
``SubAgentToolBuilder`` and ``SubAgentSessionRunner``.

``ReActAgent`` composes this mixin via multiple inheritance — the move
is pure code relocation with zero behavior change.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol, cast

from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.tenant_agent_config import TenantAgentConfig

from .react_agent_profile import AgentRuntimeProfile
from .react_agent_tool_policy import (
    filter_tools_by_name_policy,
    filter_workspace_root_tools,
    with_workspace_leader_replan_tool_allowlist,
    with_workspace_worker_tool_allowlist,
)
from .react_agent_workspace_context import (
    has_workspace_runtime_context,
    is_workspace_leader_replan_context,
    normalize_workspace_binding,
    workspace_binding_from_context,
    workspace_binding_from_text,
    workspace_runtime_context,
)

if TYPE_CHECKING:
    from .processor import ToolDefinition

logger = logging.getLogger(__name__)


class _CompositionAgent(Protocol):
    """Subset of ``ReActAgent`` state used by :class:`CompositionMixin`."""

    model: str
    _session_runner: Any
    _tool_builder: Any

    def _get_current_tools(self, *args: Any, **kwargs: Any) -> tuple[dict[str, Any], list[Any]]: ...


class CompositionMixin:
    """Workspace policy + SubAgent tool-composition helpers."""

    @staticmethod
    def _with_workspace_worker_tool_allowlist(
        runtime_profile: AgentRuntimeProfile,
    ) -> AgentRuntimeProfile:
        """Ensure workspace workers can inspect/edit/report despite persona allowlists."""
        return with_workspace_worker_tool_allowlist(runtime_profile)

    @staticmethod
    def _with_workspace_leader_replan_tool_allowlist(
        runtime_profile: AgentRuntimeProfile,
    ) -> AgentRuntimeProfile:
        """Restrict leader remediation turns to task-ledger inspection and updates."""
        return with_workspace_leader_replan_tool_allowlist(runtime_profile)

    def _resolve_effective_model(
        self: _CompositionAgent,
        *,
        selected_agent: Agent | None,
        tenant_agent_config: TenantAgentConfig,
    ) -> str:
        """Resolve the request-scoped base model before per-turn overrides.

        When neither the selected agent nor the tenant config pins a specific
        model, fall back to the pool sentinel ``"auto"`` so that
        ``PooledLLMClient`` can spread traffic across every eligible provider
        in the tenant pool instead of being collapsed to the single model
        embedded in the resolved primary provider.
        """
        if selected_agent is not None and selected_agent.model.value != "inherit":
            return selected_agent.model.value
        tenant_model = tenant_agent_config.llm_model.strip()
        if tenant_model and tenant_model.lower() != "default":
            return tenant_model
        return "auto"

    @classmethod
    def _filter_workspace_root_tools(
        cls,
        tools_to_use: list[ToolDefinition],
        workspace_root_task: Any | None,
    ) -> list[ToolDefinition]:
        return filter_workspace_root_tools(tools_to_use, workspace_root_task)

    @staticmethod
    def _filter_tools_by_name_policy(
        tools_to_use: list[ToolDefinition],
        *,
        allow_tools: Sequence[str] | None,
        deny_tools: Sequence[str] | None,
    ) -> list[ToolDefinition]:
        """Apply final hard allow/deny filtering to the executable tool list."""
        return filter_tools_by_name_policy(
            tools_to_use,
            allow_tools=allow_tools,
            deny_tools=deny_tools,
        )

    @staticmethod
    def _workspace_runtime_context(
        conversation_context: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any] | None:
        """Return hidden workspace worker app context injected as system metadata."""
        return workspace_runtime_context(conversation_context)

    @staticmethod
    def _is_workspace_leader_replan_context(payload: Mapping[str, Any] | None) -> bool:
        """Detect task-ledger-only leader remediation turns from structured app context."""
        return is_workspace_leader_replan_context(payload)

    @classmethod
    def _has_workspace_runtime_context(
        cls, conversation_context: Sequence[Mapping[str, Any]]
    ) -> bool:
        """Detect hidden workspace worker app context injected as system metadata."""
        return has_workspace_runtime_context(conversation_context)

    @staticmethod
    def _normalize_workspace_binding(raw: Mapping[str, Any] | None) -> dict[str, str] | None:
        return normalize_workspace_binding(raw)

    @classmethod
    def _workspace_binding_from_context(
        cls,
        conversation_context: Sequence[Mapping[str, Any]],
    ) -> dict[str, str] | None:
        return workspace_binding_from_context(conversation_context)

    @classmethod
    def _workspace_binding_from_text(cls, text: str | None) -> dict[str, str] | None:
        """Parse the structural workspace binding block from worker task briefs."""
        return workspace_binding_from_text(text)

    async def _subagent_fetch_memory_context(
        self: _CompositionAgent,
        user_message: str,
        project_id: str,
    ) -> str:
        """Search for relevant memories to inject into SubAgent context."""
        context = await self._session_runner.fetch_memory_context(user_message, project_id)
        return cast(str, context)

    def _subagent_filter_tools(
        self: _CompositionAgent,
        subagent: SubAgent,
    ) -> tuple[list[ToolDefinition], set[str]]:
        """Filter tools for SubAgent permissions and return mutable collections."""
        filtered = self._tool_builder.filter_tools(subagent)
        return cast("tuple[list[ToolDefinition], set[str]]", filtered)

    def _subagent_inject_nested_tools(
        self: _CompositionAgent,
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
        """Inject SubAgent delegation tools for nested orchestration (bounded depth)."""
        self._tool_builder.inject_nested_tools(
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

    def _build_nested_subagent_callbacks(
        self: _CompositionAgent,
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
        """Build nested delegate, spawn and cancel callbacks."""
        callbacks = self._tool_builder.build_nested_subagent_callbacks(
            nested_map=nested_map,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            delegation_depth=delegation_depth,
        )
        return cast(
            tuple[
                Callable[..., Coroutine[Any, Any, str]],
                Callable[..., Coroutine[Any, Any, str]],
                Callable[..., Coroutine[Any, Any, bool]],
            ],
            callbacks,
        )

    def _append_nested_session_tools(
        self: _CompositionAgent,
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
        """Append session management tools."""
        for td in self._tool_builder.make_nested_session_tool_defs(
            conversation_id=conversation_id,
            nested_depth=nested_depth,
            max_delegation_depth=max_delegation_depth,
            nested_map=nested_map,
            nested_descriptions=nested_descriptions,
            cancel_callback=cancel_callback,
            restart_callback=restart_callback,
        ):
            append_fn(td)

    def _append_nested_delegate_tools(
        self: _CompositionAgent,
        *,
        append_fn: Callable[[Any], None],
        nested_candidates: list[SubAgent],
        nested_map: dict[str, Any],
        nested_descriptions: dict[str, str],
        delegate_callback: Callable[..., Coroutine[Any, Any, str]],
        conversation_id: str,
        nested_depth: int,
    ) -> None:
        """Append delegate and parallel-delegate tools."""
        for td in self._tool_builder.make_nested_delegate_tool_defs(
            nested_candidates=nested_candidates,
            nested_map=nested_map,
            nested_descriptions=nested_descriptions,
            delegate_callback=delegate_callback,
            conversation_id=conversation_id,
            nested_depth=nested_depth,
        ):
            append_fn(td)

    def _extract_sandbox_id_from_tools(self: _CompositionAgent) -> str | None:
        """Extract sandbox_id from any available sandbox tool wrapper."""
        current_tools, _ = self._get_current_tools()
        for tool in current_tools.values():
            if hasattr(tool, "sandbox_id") and tool.sandbox_id:
                return cast(str | None, tool.sandbox_id)
        return None
