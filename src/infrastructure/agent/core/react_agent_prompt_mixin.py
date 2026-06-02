# pyright: reportUninitializedInstanceVariable=false
"""Prompt mixin extracted from ``react_agent.py``.

Hosts the system-prompt / runtime-profile / agent-loading helpers without
changing any behavior. ``ReActAgent`` composes this mixin via multiple
inheritance.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.skill import Skill
from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.tenant_agent_config import TenantAgentConfig

from ..plugins.policy_context import PolicyContext
from ..plugins.selection_pipeline import ToolSelectionContext
from ..prompts import PromptContext, PromptMode, SystemPromptManager
from ..sisyphus.builtin_agent import BUILTIN_SISYPHUS_ID, get_builtin_agent_by_id
from ..sisyphus.prompt_builder import SisyphusPromptBuilder, SisyphusPromptContext
from .react_agent_profile import AgentRuntimeProfile

if TYPE_CHECKING:
    from .processor import ToolDefinition

logger = logging.getLogger(__name__)


class _PromptAgent(Protocol):
    """Subset of ``ReActAgent`` state used by :class:`PromptMixin`."""

    model: str
    skills: list[Skill]
    subagents: list[SubAgent]
    project_root: Path
    max_steps: int
    max_tokens: int
    agent_mode: str
    prompt_manager: Any
    _enable_subagent_as_tool: bool
    _workspace_manager: Any
    _session_factory: Any
    _sisyphus_prompt_builder: SisyphusPromptBuilder
    _tool_policy_layers: dict[str, dict[str, Any]]
    _tool_selection_max_tools: int
    _tool_selection_semantic_backend: str
    _stream_memory_context: Any

    def _get_current_tools(
        self,
        selection_context: ToolSelectionContext | None = None,
    ) -> tuple[dict[str, Any], list[ToolDefinition]]: ...

    def _load_tenant_agent_config(
        self,
        tenant_id: str,
        tenant_agent_config_data: dict[str, Any] | None,
    ) -> TenantAgentConfig: ...

    def _filter_skills_for_agent(self, selected_agent: Agent | None) -> list[Skill]: ...

    def _resolve_tool_policy(
        self,
        *,
        selected_agent: Agent | None,
        tenant_agent_config: TenantAgentConfig,
    ) -> tuple[list[str], list[str]]: ...

    def _resolve_effective_model(
        self,
        *,
        selected_agent: Agent | None,
        tenant_agent_config: TenantAgentConfig,
    ) -> str: ...


class PromptMixin:
    """Prompt-building helpers (system prompt, runtime profile, agent loading)."""

    def _build_tool_selection_context(
        self: _PromptAgent,
        *,
        tenant_id: str,
        project_id: str,
        user_message: str,
        conversation_context: list[dict[str, str]],
        effective_mode: str,
        routing_metadata: Mapping[str, Any] | None = None,
        allow_tools: list[str] | None = None,
        deny_tools: list[str] | None = None,
    ) -> ToolSelectionContext:
        """Build selection context for context/intent/semantic/policy pipeline."""
        policy_context = PolicyContext.from_metadata(
            {"policy_layers": dict(self._tool_policy_layers)},
        )
        effective_deny_tools = list(deny_tools or [])
        if effective_mode == "plan":
            effective_deny_tools.extend(["plugin_manager", "skill_installer", "skill_sync"])
        effective_deny_tools = sorted({tool for tool in effective_deny_tools if tool})
        metadata: dict[str, Any] = {
            "user_message": user_message,
            "conversation_history": conversation_context,
            "effective_mode": effective_mode,
            "agent_mode": self.agent_mode,
            "max_tools": self._tool_selection_max_tools,
            "semantic_backend": self._tool_selection_semantic_backend,
            "deny_tools": effective_deny_tools,
            "allow_tools": list(allow_tools or []),
            "policy_agent": (
                {
                    "allow_tools": list(allow_tools or []),
                    "deny_tools": effective_deny_tools,
                }
                if allow_tools or effective_deny_tools
                else {}
            ),
        }
        if routing_metadata:
            domain_lane = routing_metadata.get("domain_lane")
            if isinstance(domain_lane, str) and domain_lane:
                metadata["domain_lane"] = domain_lane
            route_id = routing_metadata.get("route_id")
            if isinstance(route_id, str) and route_id:
                metadata["route_id"] = route_id
            trace_id = routing_metadata.get("trace_id")
            if isinstance(trace_id, str) and trace_id:
                metadata["trace_id"] = trace_id
            metadata["routing_metadata"] = dict(routing_metadata)
        if self._tool_policy_layers:
            metadata["policy_layers"] = policy_context.to_mapping()
        return ToolSelectionContext(
            tenant_id=tenant_id,
            project_id=project_id,
            metadata=metadata,
            policy_context=policy_context,
        )

    async def _build_system_prompt(  # noqa: PLR0913
        self: _PromptAgent,
        user_query: str,
        conversation_context: list[dict[str, str]],
        matched_skill: Skill | None = None,
        subagent: SubAgent | None = None,
        mode: str = "build",
        current_step: int = 1,
        project_id: str = "",
        tenant_id: str = "",
        force_execution: bool = False,
        memory_context: str | None = None,
        selection_context: ToolSelectionContext | None = None,
        heartbeat_prompt: str | None = None,
        agent_definition_prompt: str | None = None,
        primary_agent_prompt: str | None = None,
        available_skills: list[Skill] | None = None,
        model_name: str | None = None,
        max_steps_override: int | None = None,
        workspace_manager: Any | None = None,
        selected_agent_name: str | None = None,
        is_workspace_conversation: bool = False,
    ) -> str:
        """
        Build system prompt for the agent using SystemPromptManager.

        Args:
            user_query: User's query
            conversation_context: Conversation history
            matched_skill: Optional matched skill to highlight
            subagent: Optional SubAgent (uses its system prompt if provided)
            mode: Agent mode ("build" or "plan")
            current_step: Current execution step number
            project_id: Project ID for context
            tenant_id: Tenant ID for context
            force_execution: If True, skill injection uses mandatory wording

        Returns:
            System prompt string
        """
        # Detect model provider from model name
        model_provider = SystemPromptManager.detect_model_provider(model_name or self.model)

        # Convert skills to dict format for PromptContext
        skills_data = None
        effective_skills = available_skills if available_skills is not None else self.skills
        # Strip workspace-scoped skills from non-workspace conversations.
        if effective_skills and not is_workspace_conversation:
            effective_skills = [s for s in effective_skills if not s.name.startswith("workspace-")]
        if effective_skills:
            skills_data = [
                {
                    "name": s.name,
                    "description": s.description,
                    "tools": s.tools,
                    "status": s.status.value,
                    "prompt_template": s.full_content,
                }
                for s in effective_skills
            ]

        # Convert matched skill to dict format
        matched_skill_data = None
        if matched_skill:
            matched_skill_data = {
                "name": matched_skill.name,
                "description": matched_skill.description,
                "tools": matched_skill.tools,
                "prompt_template": matched_skill.full_content,
                "force_execution": force_execution,
            }

        # Convert tool definitions to dict format - use current tools (hot-plug support)
        _, current_tool_definitions = self._get_current_tools(selection_context=selection_context)
        # Strip workspace-scoped tools from non-workspace conversations so the
        # system prompt does not advertise tools that will be filtered out at
        # execution time anyway.
        if not is_workspace_conversation:
            current_tool_definitions = [
                t for t in current_tool_definitions if not t.name.startswith("workspace_")
            ]
        # When a forced skill is active, exclude skill_loader from tool list
        # to prevent the LLM from calling it and loading a different skill.
        if force_execution and matched_skill:
            tool_defs = [
                {"name": t.name, "description": t.description}
                for t in current_tool_definitions
                if t.name != "skill_loader"
            ]
        else:
            tool_defs = [
                {"name": t.name, "description": t.description} for t in current_tool_definitions
            ]

        # Convert SubAgents to dict format for PromptContext (SubAgent-as-Tool mode)
        subagents_data = None
        if self.subagents and self._enable_subagent_as_tool:
            subagents_data = [
                {
                    "name": sa.name,
                    "display_name": sa.display_name,
                    "description": sa.system_prompt[:200] if sa.system_prompt else "",
                    "trigger_description": (
                        sa.trigger.description if sa.trigger else "general tasks"
                    ),
                }
                for sa in self.subagents
                if sa.enabled
            ]

        # Load workspace persona as first-class AgentPersona
        persona = None
        active_workspace_manager = workspace_manager or self._workspace_manager
        if active_workspace_manager:
            try:
                persona = await active_workspace_manager.build_persona()
            except Exception as e:
                logger.warning("Failed to load workspace persona: %s", e)

        # Fetch dynamic workspace context (members, agents, messages, blackboard).
        # Strict isolation: only inject into conversations that are actually
        # bound to a workspace turn (worker dispatch or leader/worker session
        # tagged via runtime_context). Project-scoped chats in projects that
        # happen to host a workspace must NOT see this content.
        workspace_context: str | None = None
        if is_workspace_conversation and project_id and tenant_id:
            from src.infrastructure.agent.workspace.workspace_context_builder import (
                build_workspace_context,
            )

            workspace_context = await build_workspace_context(project_id, tenant_id)

        # Build prompt context
        context = PromptContext(
            model_provider=model_provider,
            mode=PromptMode(mode),
            tool_definitions=tool_defs,
            skills=skills_data,
            subagents=subagents_data,
            matched_skill=matched_skill_data,
            project_id=project_id,
            tenant_id=tenant_id,
            working_directory=str(self.project_root),
            conversation_history_length=len(conversation_context),
            user_query=user_query,
            current_step=current_step,
            max_steps=max_steps_override or self.max_steps,
            memory_context=memory_context,
            persona=persona,
            heartbeat_prompt=heartbeat_prompt,
            workspace_context=workspace_context,
            workspace_authority_active=bool(
                active_workspace_manager
                and getattr(active_workspace_manager, "root_goal_task_id", None)
            ),
            agent_definition_prompt=agent_definition_prompt,
            primary_agent_prompt=primary_agent_prompt,
            selected_agent_name=selected_agent_name,
        )

        # Use SystemPromptManager to build the prompt
        return cast(
            str,
            await self.prompt_manager.build_system_prompt(
                context=context,
                subagent=subagent,
            ),
        )

    async def _load_selected_agent(
        self: _PromptAgent,
        *,
        agent_id: str,
        tenant_id: str,
        project_id: str,
    ) -> Agent | None:
        """Load the selected runtime agent from built-ins, orchestrator, or DB."""
        builtin_agent = get_builtin_agent_by_id(
            agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if builtin_agent is not None:
            return builtin_agent

        from src.infrastructure.agent.state.agent_worker_state import get_agent_orchestrator

        orchestrator = get_agent_orchestrator()
        if orchestrator is not None:
            try:
                agent_def = await orchestrator.get_agent(agent_id)
                if agent_def is not None:
                    return cast(Agent, agent_def)
            except Exception:
                logger.exception("[ReActAgent] Failed orchestrator lookup for agent %s", agent_id)

        session_factory = self._session_factory
        if session_factory is None:
            logger.debug("[ReActAgent] No session_factory available for agent lookup: %s", agent_id)
            return None

        from src.infrastructure.adapters.secondary.persistence.sql_agent_registry import (
            SqlAgentRegistryRepository,
        )

        session = session_factory()
        try:
            repository = SqlAgentRegistryRepository(session)
            agent_def = await repository.get_by_id(
                agent_id,
                tenant_id=tenant_id,
                project_id=project_id,
            )
            if agent_def is None:
                logger.warning("[ReActAgent] Agent definition not found: %s", agent_id)
            return agent_def
        except Exception:
            logger.exception("[ReActAgent] Failed DB lookup for agent definition: %s", agent_id)
            return None
        finally:
            with contextlib.suppress(Exception):
                await session.rollback()
            await session.close()

    def _build_runtime_profile(
        self: _PromptAgent,
        *,
        tenant_id: str,
        tenant_agent_config_data: dict[str, Any] | None,
        selected_agent: Agent | None,
        is_workspace_worker_runtime: bool = False,
    ) -> AgentRuntimeProfile:
        """Build the request-scoped runtime profile."""
        tenant_agent_config = self._load_tenant_agent_config(tenant_id, tenant_agent_config_data)
        available_skills = self._filter_skills_for_agent(selected_agent)
        allow_tools, deny_tools = self._resolve_tool_policy(
            selected_agent=selected_agent,
            tenant_agent_config=tenant_agent_config,
        )
        effective_model = self._resolve_effective_model(
            selected_agent=selected_agent,
            tenant_agent_config=tenant_agent_config,
        )
        effective_temperature = (
            selected_agent.temperature
            if selected_agent is not None and selected_agent.has_explicit_temperature()
            else tenant_agent_config.llm_temperature
        )
        effective_max_tokens = (
            selected_agent.max_tokens
            if selected_agent is not None and selected_agent.has_explicit_max_tokens()
            else self.max_tokens
        )
        agent_max_iterations_explicit = (
            selected_agent is not None
            and selected_agent.has_explicit_max_iterations()
            and not (
                is_workspace_worker_runtime
                and _is_workspace_plan_team_agent(selected_agent)
            )
        )
        effective_max_steps = (
            selected_agent.max_iterations
            if selected_agent is not None and agent_max_iterations_explicit
            else tenant_agent_config.max_work_plan_steps
        )
        if selected_agent is not None and not agent_max_iterations_explicit:
            logger.info(
                "[ReActAgent] Agent %s uses implicit max_iterations=%s; "
                "falling back to tenant max_work_plan_steps=%s",
                selected_agent.id,
                selected_agent.max_iterations,
                tenant_agent_config.max_work_plan_steps,
            )
        agent_definition_prompt = (
            selected_agent.system_prompt
            if selected_agent is not None and selected_agent.id != BUILTIN_SISYPHUS_ID
            else None
        )

        return AgentRuntimeProfile(
            selected_agent=selected_agent,
            tenant_agent_config=tenant_agent_config,
            available_skills=available_skills,
            allow_tools=allow_tools,
            deny_tools=deny_tools,
            effective_model=effective_model,
            effective_temperature=effective_temperature,
            effective_max_tokens=effective_max_tokens,
            effective_max_steps=effective_max_steps,
            primary_agent_prompt=None,
            agent_definition_prompt=agent_definition_prompt,
        )

    def _build_primary_agent_prompt(
        self: _PromptAgent,
        *,
        runtime_profile: AgentRuntimeProfile,
        selection_context: ToolSelectionContext,
    ) -> str | None:
        """Build a dynamic primary prompt when the selected agent is built-in Sisyphus."""
        selected_agent = runtime_profile.selected_agent
        if selected_agent is None or selected_agent.id != BUILTIN_SISYPHUS_ID:
            return None
        _, current_tool_definitions = self._get_current_tools(selection_context=selection_context)
        return self._sisyphus_prompt_builder.build(
            SisyphusPromptContext(
                model_name=runtime_profile.effective_model,
                max_steps=runtime_profile.effective_max_steps,
                tools=current_tool_definitions,
                skills=runtime_profile.available_skills,
                subagents=list(self.subagents or []),
            )
        )


def _is_workspace_plan_team_agent(agent: Agent) -> bool:
    metadata = dict(agent.metadata or {})
    return metadata.get("created_by") == "workspace_plan_team_setup"
