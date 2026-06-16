"""Manage agent definitions: create, update, delete, and get.

Gives the running agent the ability to autonomously define new agents
(or modify / remove existing ones) within the current tenant/project scope.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, cast

from src.domain.model.agent.agent_definition import (
    LEGACY_DEFAULT_MAX_ITERATIONS,
    MAX_ITERATIONS_EXPLICIT_METADATA_KEY,
    Agent,
)
from src.domain.model.agent.agent_source import AgentSource
from src.domain.model.agent.delegate_config import DelegateConfig
from src.domain.model.agent.session_policy import SessionPolicy
from src.domain.model.agent.subagent import AgentModel, AgentTrigger
from src.domain.model.agent.workspace_config import WorkspaceConfig
from src.infrastructure.agent.tools._agent_definition_policy import (
    normalize_new_agent_a2a,
    normalize_updated_agent_a2a,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

if TYPE_CHECKING:
    from src.infrastructure.agent.orchestration.orchestrator import (
        AgentOrchestrator,
    )

logger = logging.getLogger(__name__)

_orchestrator: AgentOrchestrator | None = None
_UNSET = object()


def configure_agent_definition_manage(orchestrator: AgentOrchestrator) -> None:
    """Inject orchestrator at agent startup."""
    global _orchestrator
    _orchestrator = orchestrator


def _parse_model(value: str | None) -> AgentModel:
    """Safely parse a model string into AgentModel enum."""
    if not value:
        return AgentModel.INHERIT
    try:
        return AgentModel(value)
    except ValueError:
        return AgentModel.INHERIT


def _resolve_bool(value: bool | object, *, default: bool) -> bool:
    return default if value is _UNSET else bool(value)


def _resolve_int(value: int | object, *, default: int) -> int:
    return default if value is _UNSET else int(cast(int, value))


def _resolve_float(value: float | object, *, default: float) -> float:
    return default if value is _UNSET else float(cast(float, value))


def _agent_summary(agent: Agent) -> dict[str, Any]:
    """Return a concise dict summary of an Agent for LLM consumption."""
    prompt_preview = agent.system_prompt[:200]
    if len(agent.system_prompt) > 200:
        prompt_preview += "..."
    return {
        "id": agent.id,
        "name": agent.name,
        "display_name": agent.display_name,
        "system_prompt": prompt_preview,
        "model": agent.model.value if isinstance(agent.model, AgentModel) else str(agent.model),
        "project_id": agent.project_id,
        "enabled": agent.enabled,
        "discoverable": agent.discoverable,
        "can_spawn": agent.can_spawn,
        "agent_to_agent_enabled": agent.agent_to_agent_enabled,
        "agent_to_agent_allowlist": agent.agent_to_agent_allowlist,
        "allowed_tools": agent.allowed_tools,
        "allowed_skills": agent.allowed_skills,
        "allowed_mcp_servers": agent.allowed_mcp_servers,
        "persona_files": agent.persona_files,
        "workspace_dir": agent.workspace_dir,
        "workspace_config": agent.workspace_config.to_dict(),
        "max_spawn_depth": agent.max_spawn_depth,
        "max_retries": agent.max_retries,
        "fallback_models": agent.fallback_models,
        "metadata": agent.metadata,
        "session_policy": (
            agent.session_policy.to_dict() if agent.session_policy is not None else None
        ),
        "delegate_config": (
            agent.delegate_config.to_dict() if agent.delegate_config is not None else None
        ),
        "trigger": {
            "description": agent.trigger.description,
            "keywords": list(agent.trigger.keywords),
            "examples": list(agent.trigger.examples),
        },
        "source": (
            agent.source.value if isinstance(agent.source, AgentSource) else str(agent.source)
        ),
    }


def _with_max_iterations_metadata(
    metadata: dict[str, Any] | None,
    *,
    explicit: bool | None,
) -> dict[str, Any] | None:
    if explicit is None:
        return metadata
    merged = dict(metadata or {})
    merged[MAX_ITERATIONS_EXPLICIT_METADATA_KEY] = explicit
    return merged


def _workspace_config_from_payload(value: dict[str, Any] | None) -> WorkspaceConfig | None:
    return WorkspaceConfig.from_dict(value) if value is not None else None


def _session_policy_from_payload(value: dict[str, Any] | None) -> SessionPolicy | None:
    return SessionPolicy.from_dict(value) if value is not None else None


def _delegate_config_from_payload(value: dict[str, Any] | None) -> DelegateConfig | None:
    return DelegateConfig.from_dict(value) if value is not None else None


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------


async def _handle_create(  # noqa: PLR0913
    ctx: ToolContext,
    *,
    name: str | None,
    display_name: str | None,
    system_prompt: str | None,
    trigger_description: str | None,
    trigger_keywords: list[str] | None,
    trigger_examples: list[str] | None,
    model: str | None,
    allowed_tools: list[str] | None,
    allowed_skills: list[str] | None,
    allowed_mcp_servers: list[str] | None,
    persona_files: list[str] | None,
    workspace_dir: str | None,
    workspace_config: dict[str, Any] | None,
    can_spawn: bool,
    max_spawn_depth: int,
    agent_to_agent_enabled: bool,
    agent_to_agent_allowlist: list[str] | None,
    discoverable: bool,
    max_iterations: int,
    temperature: float,
    max_tokens: int,
    max_retries: int,
    fallback_models: list[str] | None,
    metadata: dict[str, Any] | None,
    session_policy: dict[str, Any] | None,
    delegate_config: dict[str, Any] | None,
) -> ToolResult:
    """Handle the 'create' action."""
    assert _orchestrator is not None

    if not name:
        return ToolResult(
            output=json.dumps({"error": "Parameter 'name' is required for create"}),
            is_error=True,
        )
    if not system_prompt:
        return ToolResult(
            output=json.dumps({"error": "Parameter 'system_prompt' is required for create"}),
            is_error=True,
        )

    normalized_a2a_allowlist = normalize_new_agent_a2a(
        enabled=agent_to_agent_enabled,
        allowlist=agent_to_agent_allowlist,
    )

    agent = Agent.create(
        tenant_id=ctx.tenant_id,
        name=name,
        display_name=display_name or name,
        system_prompt=system_prompt,
        trigger_description=trigger_description or f"Agent for {display_name or name}",
        trigger_keywords=trigger_keywords,
        trigger_examples=trigger_examples,
        project_id=ctx.project_id or None,
        persona_files=persona_files,
        model=_parse_model(model),
        allowed_tools=allowed_tools or ["*"],
        allowed_skills=allowed_skills,
        allowed_mcp_servers=allowed_mcp_servers,
        workspace_dir=workspace_dir,
        workspace_config=_workspace_config_from_payload(workspace_config),
        can_spawn=can_spawn,
        max_spawn_depth=max_spawn_depth,
        agent_to_agent_enabled=agent_to_agent_enabled,
        agent_to_agent_allowlist=normalized_a2a_allowlist,
        discoverable=discoverable,
        max_iterations=max_iterations,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=max_retries,
        fallback_models=fallback_models,
        metadata=_with_max_iterations_metadata(
            metadata,
            explicit=max_iterations != LEGACY_DEFAULT_MAX_ITERATIONS,
        ),
        session_policy=_session_policy_from_payload(session_policy),
        delegate_config=_delegate_config_from_payload(delegate_config),
    )

    created = await _orchestrator.create_agent(agent)

    await ctx.emit(
        {
            "type": "agent_definition_created",
            "data": {"agent_id": created.id, "agent_name": created.name},
        }
    )

    return ToolResult(
        output=json.dumps(_agent_summary(created), indent=2),
        title=f"Created agent definition: {created.display_name}",
    )


def _apply_scalar_updates(  # noqa: PLR0913
    agent: Agent,
    *,
    name: str | None,
    display_name: str | None,
    system_prompt: str | None,
    model: str | None,
    allowed_tools: list[str] | None,
    allowed_skills: list[str] | None,
    allowed_mcp_servers: list[str] | None,
    persona_files: list[str] | None,
    workspace_dir: str | None,
    can_spawn: bool | None,
    max_spawn_depth: int | None,
    agent_to_agent_enabled: bool | None,
    discoverable: bool | None,
    max_iterations: int | None,
    temperature: float | None,
    max_tokens: int | None,
    max_retries: int | None,
    fallback_models: list[str] | None,
    metadata: dict[str, Any] | None,
) -> None:
    """Apply non-None scalar fields to an existing agent."""
    _fields: dict[str, Any] = {
        "name": name,
        "display_name": display_name,
        "system_prompt": system_prompt,
        "allowed_tools": allowed_tools,
        "allowed_skills": allowed_skills,
        "allowed_mcp_servers": allowed_mcp_servers,
        "persona_files": persona_files,
        "workspace_dir": workspace_dir,
        "fallback_models": fallback_models,
        "metadata": metadata,
    }
    for attr, value in _fields.items():
        if value is not None:
            setattr(agent, attr, value)
    if model is not None:
        agent.model = _parse_model(model)
    _bool_int_float: dict[str, bool | int | float | None] = {
        "can_spawn": can_spawn,
        "agent_to_agent_enabled": agent_to_agent_enabled,
        "discoverable": discoverable,
        "max_iterations": max_iterations,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "max_spawn_depth": max_spawn_depth,
        "max_retries": max_retries,
    }
    for attr, value in _bool_int_float.items():
        if value is not None:
            setattr(agent, attr, value)


def _apply_trigger_updates(
    agent: Agent,
    *,
    trigger_description: str | None,
    trigger_keywords: list[str] | None,
    trigger_examples: list[str] | None,
) -> None:
    """Apply trigger field updates if any are provided."""
    if not any(v is not None for v in (trigger_description, trigger_keywords, trigger_examples)):
        return
    agent.trigger = AgentTrigger(
        description=(
            trigger_description if trigger_description is not None else agent.trigger.description
        ),
        examples=(
            trigger_examples if trigger_examples is not None else list(agent.trigger.examples)
        ),
        keywords=(
            trigger_keywords if trigger_keywords is not None else list(agent.trigger.keywords)
        ),
    )


def _apply_a2a_update(
    agent: Agent,
    agent_to_agent_allowlist: list[str] | None,
    agent_to_agent_enabled: bool | None,
) -> None:
    """Apply A2A allowlist changes using shared policy logic."""
    updates: dict[str, Any] = {}
    if agent_to_agent_allowlist is not None or agent_to_agent_enabled is not None:
        if agent_to_agent_allowlist is not None:
            updates["agent_to_agent_allowlist"] = agent_to_agent_allowlist
        if agent_to_agent_enabled is not None:
            updates["agent_to_agent_enabled"] = agent_to_agent_enabled
        normalize_updated_agent_a2a(agent, updates)
        if "agent_to_agent_allowlist" in updates:
            agent.agent_to_agent_allowlist = updates["agent_to_agent_allowlist"]


def _apply_policy_updates(
    agent: Agent,
    *,
    workspace_config: dict[str, Any] | None | object,
    session_policy: dict[str, Any] | None | object,
    delegate_config: dict[str, Any] | None | object,
) -> None:
    """Apply nested policy/config updates where omitted and explicit null differ."""
    if workspace_config is not _UNSET:
        agent.workspace_config = (
            _workspace_config_from_payload(cast(dict[str, Any] | None, workspace_config))
            or WorkspaceConfig()
        )
    if session_policy is not _UNSET:
        agent.session_policy = _session_policy_from_payload(
            cast(dict[str, Any] | None, session_policy)
        )
    if delegate_config is not _UNSET:
        agent.delegate_config = _delegate_config_from_payload(
            cast(dict[str, Any] | None, delegate_config)
        )


async def _handle_update(  # noqa: PLR0913
    ctx: ToolContext,
    *,
    agent_id: str | None,
    name: str | None,
    display_name: str | None,
    system_prompt: str | None,
    trigger_description: str | None,
    trigger_keywords: list[str] | None,
    trigger_examples: list[str] | None,
    model: str | None,
    allowed_tools: list[str] | None,
    allowed_skills: list[str] | None,
    allowed_mcp_servers: list[str] | None,
    persona_files: list[str] | None,
    workspace_dir: str | None,
    workspace_config: dict[str, Any] | None | object,
    can_spawn: bool | None,
    max_spawn_depth: int | None,
    agent_to_agent_enabled: bool | None,
    agent_to_agent_allowlist: list[str] | None,
    discoverable: bool | None,
    max_iterations: int | None,
    temperature: float | None,
    max_tokens: int | None,
    max_retries: int | None,
    fallback_models: list[str] | None,
    metadata: dict[str, Any] | None,
    session_policy: dict[str, Any] | None | object,
    delegate_config: dict[str, Any] | None | object,
) -> ToolResult:
    """Handle the 'update' action."""
    assert _orchestrator is not None

    if not agent_id:
        return ToolResult(
            output=json.dumps({"error": "Parameter 'agent_id' is required for update"}),
            is_error=True,
        )

    existing = await _orchestrator.get_agent(
        agent_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id or None,
        exact_project=True,
    )
    if existing is None:
        return ToolResult(
            output=json.dumps({"error": f"Agent not found: {agent_id}"}),
            is_error=True,
        )

    _apply_scalar_updates(
        existing,
        name=name,
        display_name=display_name,
        system_prompt=system_prompt,
        model=model,
        allowed_tools=allowed_tools,
        allowed_skills=allowed_skills,
        allowed_mcp_servers=allowed_mcp_servers,
        persona_files=persona_files,
        workspace_dir=workspace_dir,
        can_spawn=can_spawn,
        max_spawn_depth=max_spawn_depth,
        agent_to_agent_enabled=agent_to_agent_enabled,
        discoverable=discoverable,
        max_iterations=max_iterations,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=max_retries,
        fallback_models=fallback_models,
        metadata=metadata,
    )
    if max_iterations is not None:
        existing.metadata = _with_max_iterations_metadata(existing.metadata, explicit=True)
    _apply_policy_updates(
        existing,
        workspace_config=workspace_config,
        session_policy=session_policy,
        delegate_config=delegate_config,
    )
    _apply_a2a_update(existing, agent_to_agent_allowlist, agent_to_agent_enabled)
    _apply_trigger_updates(
        existing,
        trigger_description=trigger_description,
        trigger_keywords=trigger_keywords,
        trigger_examples=trigger_examples,
    )

    updated = await _orchestrator.update_agent(
        existing,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id or None,
        exact_project=True,
    )

    await ctx.emit(
        {
            "type": "agent_definition_updated",
            "data": {"agent_id": updated.id, "agent_name": updated.name},
        }
    )

    return ToolResult(
        output=json.dumps(_agent_summary(updated), indent=2),
        title=f"Updated agent definition: {updated.display_name}",
    )


async def _handle_delete(
    ctx: ToolContext,
    *,
    agent_id: str | None,
) -> ToolResult:
    """Handle the 'delete' action."""
    assert _orchestrator is not None

    if not agent_id:
        return ToolResult(
            output=json.dumps({"error": "Parameter 'agent_id' is required for delete"}),
            is_error=True,
        )

    existing = await _orchestrator.get_agent(
        agent_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id or None,
        exact_project=True,
    )
    if existing is None:
        return ToolResult(
            output=json.dumps({"error": f"Agent not found: {agent_id}"}),
            is_error=True,
        )

    deleted = await _orchestrator.delete_agent(
        agent_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id or None,
        exact_project=True,
    )

    if deleted:
        await ctx.emit(
            {
                "type": "agent_definition_deleted",
                "data": {"agent_id": agent_id, "agent_name": existing.name},
            }
        )

    return ToolResult(
        output=json.dumps({"deleted": deleted, "id": agent_id, "name": existing.name}),
        title=f"Deleted agent definition: {existing.display_name}",
    )


async def _handle_get(
    ctx: ToolContext,
    *,
    agent_id: str | None,
) -> ToolResult:
    """Handle the 'get' action."""
    assert _orchestrator is not None

    if not agent_id:
        return ToolResult(
            output=json.dumps({"error": "Parameter 'agent_id' is required for get"}),
            is_error=True,
        )

    agent = await _orchestrator.get_agent(
        agent_id,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id or None,
        exact_project=True,
    )
    if agent is None:
        return ToolResult(
            output=json.dumps({"error": f"Agent not found: {agent_id}"}),
            is_error=True,
        )

    return ToolResult(
        output=json.dumps(_agent_summary(agent), indent=2),
        title=f"Agent definition: {agent.display_name}",
    )


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool_define(
    name="agent_definition_manage",
    description=(
        "Create, update, delete, or get agent definitions. "
        "Use 'create' to define a new specialized agent with a system prompt and capabilities. "
        "Use 'update' to modify an existing agent definition. "
        "Use 'delete' to remove an agent definition. "
        "Use 'get' to retrieve details of a specific agent definition."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "The operation to perform",
                "enum": ["create", "update", "delete", "get"],
            },
            "agent_id": {
                "type": "string",
                "description": "Agent definition ID (required for update/delete/get)",
            },
            "name": {
                "type": "string",
                "description": (
                    "Unique agent name identifier (required for create, "
                    "use lowercase-with-hyphens, e.g. 'code-reviewer')"
                ),
            },
            "display_name": {
                "type": "string",
                "description": "Human-readable display name (e.g. 'Code Reviewer')",
            },
            "system_prompt": {
                "type": "string",
                "description": (
                    "The system prompt that defines the agent's persona, "
                    "capabilities, and behavior (required for create)"
                ),
            },
            "trigger_description": {
                "type": "string",
                "description": "When this agent should be activated",
            },
            "trigger_keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keywords for quick-matching agent activation",
            },
            "trigger_examples": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Example queries that should route to this agent",
            },
            "model": {
                "type": "string",
                "description": (
                    "LLM model to use (e.g. 'inherit', 'gpt-4o', 'claude-3-5-sonnet', "
                    "'qwen-max', 'deepseek-chat'). Default: 'inherit'"
                ),
            },
            "allowed_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool names this agent can use. ['*'] means all tools.",
            },
            "allowed_skills": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Skill IDs or names this agent can use. Omit or [] for all skills.",
            },
            "allowed_mcp_servers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "MCP server names this agent can use. ['*'] means all MCP servers.",
            },
            "persona_files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Persona files to inject into this agent's prompt.",
            },
            "workspace_dir": {
                "type": "string",
                "description": "Optional workspace directory for this agent.",
            },
            "workspace_config": {
                "type": "object",
                "description": (
                    "Workspace configuration object. Supports base_path/base_dir, max_size_mb, "
                    "persona_files, shared_files, auto_cleanup, retention_days, and sandbox_scope/type."
                ),
            },
            "can_spawn": {
                "type": "boolean",
                "description": "Whether this agent can spawn sub-agents. Default: false",
            },
            "max_spawn_depth": {
                "type": "integer",
                "description": "Maximum depth for sub-agent spawning. Default: 3",
            },
            "agent_to_agent_enabled": {
                "type": "boolean",
                "description": "Whether this agent can send and receive direct agent messages.",
            },
            "agent_to_agent_allowlist": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Allowed sender agent IDs or names for inbound agent messages. "
                    "Use [] to deny all."
                ),
            },
            "discoverable": {
                "type": "boolean",
                "description": "Whether this agent appears in agent_list. Default: true",
            },
            "max_iterations": {
                "type": "integer",
                "description": "Max ReAct loop iterations. Default: 10",
            },
            "temperature": {
                "type": "number",
                "description": "LLM temperature (0.0-1.0). Default: 0.7",
            },
            "max_tokens": {
                "type": "integer",
                "description": "Max tokens for LLM response. Default: 4096",
            },
            "max_retries": {
                "type": "integer",
                "description": "Maximum retry attempts after failure. Default: 0",
            },
            "fallback_models": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Fallback model identifiers to try if the primary model fails.",
            },
            "metadata": {
                "type": "object",
                "description": "Additional metadata to persist on the agent definition.",
            },
            "session_policy": {
                "type": "object",
                "description": (
                    "Session policy object with dm_scope, max_messages, idle_reset_minutes, "
                    "daily_reset_hour, and session_ttl_hours."
                ),
            },
            "delegate_config": {
                "type": "object",
                "description": (
                    "Delegation policy object with capability_tier, max_delegation_depth, "
                    "allowed_tools, and budget_limit_tokens."
                ),
            },
        },
        "required": ["action"],
    },
    permission=None,
    category="multi_agent",
)
async def agent_definition_manage_tool(  # noqa: PLR0913
    ctx: ToolContext,
    *,
    action: str,
    agent_id: str | None = None,
    name: str | None = None,
    display_name: str | None = None,
    system_prompt: str | None = None,
    trigger_description: str | None = None,
    trigger_keywords: list[str] | None = None,
    trigger_examples: list[str] | None = None,
    model: str | None = None,
    allowed_tools: list[str] | None = None,
    allowed_skills: list[str] | None = None,
    allowed_mcp_servers: list[str] | None = None,
    persona_files: list[str] | None = None,
    workspace_dir: str | None = None,
    workspace_config: dict[str, Any] | None | object = _UNSET,
    can_spawn: bool | object = _UNSET,
    max_spawn_depth: int | object = _UNSET,
    agent_to_agent_enabled: bool | None = None,
    agent_to_agent_allowlist: list[str] | None = None,
    discoverable: bool | object = _UNSET,
    max_iterations: int | object = _UNSET,
    temperature: float | object = _UNSET,
    max_tokens: int | object = _UNSET,
    max_retries: int | object = _UNSET,
    fallback_models: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    session_policy: dict[str, Any] | None | object = _UNSET,
    delegate_config: dict[str, Any] | None | object = _UNSET,
) -> ToolResult:
    """Manage agent definitions: create, update, delete, or get."""
    if _orchestrator is None:
        return ToolResult(
            output=json.dumps({"error": "Multi-agent not configured"}),
            is_error=True,
        )

    try:
        result: ToolResult
        if action == "create":
            result = await _handle_create(
                ctx,
                name=name,
                display_name=display_name,
                system_prompt=system_prompt,
                trigger_description=trigger_description,
                trigger_keywords=trigger_keywords,
                trigger_examples=trigger_examples,
                model=model,
                allowed_tools=allowed_tools,
                allowed_skills=allowed_skills,
                allowed_mcp_servers=allowed_mcp_servers,
                persona_files=persona_files,
                workspace_dir=workspace_dir,
                workspace_config=(
                    None
                    if workspace_config is _UNSET
                    else cast(dict[str, Any] | None, workspace_config)
                ),
                can_spawn=_resolve_bool(can_spawn, default=False),
                max_spawn_depth=_resolve_int(max_spawn_depth, default=3),
                agent_to_agent_enabled=(
                    agent_to_agent_enabled if agent_to_agent_enabled is not None else False
                ),
                agent_to_agent_allowlist=agent_to_agent_allowlist,
                discoverable=_resolve_bool(discoverable, default=True),
                max_iterations=_resolve_int(max_iterations, default=10),
                temperature=_resolve_float(temperature, default=0.7),
                max_tokens=_resolve_int(max_tokens, default=4096),
                max_retries=_resolve_int(max_retries, default=0),
                fallback_models=fallback_models,
                metadata=metadata,
                session_policy=(
                    None
                    if session_policy is _UNSET
                    else cast(dict[str, Any] | None, session_policy)
                ),
                delegate_config=(
                    None
                    if delegate_config is _UNSET
                    else cast(dict[str, Any] | None, delegate_config)
                ),
            )
        elif action == "update":
            result = await _handle_update(
                ctx,
                agent_id=agent_id,
                name=name,
                display_name=display_name,
                system_prompt=system_prompt,
                trigger_description=trigger_description,
                trigger_keywords=trigger_keywords,
                trigger_examples=trigger_examples,
                model=model,
                allowed_tools=allowed_tools,
                allowed_skills=allowed_skills,
                allowed_mcp_servers=allowed_mcp_servers,
                persona_files=persona_files,
                workspace_dir=workspace_dir,
                workspace_config=workspace_config,
                can_spawn=None if can_spawn is _UNSET else _resolve_bool(can_spawn, default=False),
                max_spawn_depth=(
                    None if max_spawn_depth is _UNSET else _resolve_int(max_spawn_depth, default=3)
                ),
                agent_to_agent_enabled=agent_to_agent_enabled,
                agent_to_agent_allowlist=agent_to_agent_allowlist,
                discoverable=(
                    None if discoverable is _UNSET else _resolve_bool(discoverable, default=True)
                ),
                max_iterations=(
                    None if max_iterations is _UNSET else _resolve_int(max_iterations, default=10)
                ),
                temperature=(
                    None if temperature is _UNSET else _resolve_float(temperature, default=0.7)
                ),
                max_tokens=None if max_tokens is _UNSET else _resolve_int(max_tokens, default=4096),
                max_retries=None if max_retries is _UNSET else _resolve_int(max_retries, default=0),
                fallback_models=fallback_models,
                metadata=metadata,
                session_policy=session_policy,
                delegate_config=delegate_config,
            )
        elif action == "delete":
            result = await _handle_delete(ctx, agent_id=agent_id)
        elif action == "get":
            result = await _handle_get(ctx, agent_id=agent_id)
        else:
            result = ToolResult(
                output=json.dumps(
                    {"error": f"Unknown action: {action}. Use: create, update, delete, get"}
                ),
                is_error=True,
            )
        return result
    except ValueError as exc:
        return ToolResult(
            output=json.dumps({"error": str(exc)}),
            is_error=True,
        )
    except Exception:
        logger.exception("agent_definition_manage failed: action=%s", action)
        return ToolResult(
            output=json.dumps({"error": "Internal error in agent_definition_manage"}),
            is_error=True,
        )
