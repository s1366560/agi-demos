"""Manage agent definitions: create, update, delete, and get.

Gives the running agent the ability to autonomously define new agents
(or modify / remove existing ones) within the current tenant/project scope.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, cast

from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.agent_source import AgentSource
from src.domain.model.agent.subagent import AgentModel, AgentTrigger
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
        "trigger": {
            "description": agent.trigger.description,
            "keywords": list(agent.trigger.keywords),
            "examples": list(agent.trigger.examples),
        },
        "source": (
            agent.source.value if isinstance(agent.source, AgentSource) else str(agent.source)
        ),
    }


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
    can_spawn: bool,
    agent_to_agent_enabled: bool,
    agent_to_agent_allowlist: list[str] | None,
    discoverable: bool,
    max_iterations: int,
    temperature: float,
    max_tokens: int,
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
        model=_parse_model(model),
        allowed_tools=allowed_tools or ["*"],
        can_spawn=can_spawn,
        agent_to_agent_enabled=agent_to_agent_enabled,
        agent_to_agent_allowlist=normalized_a2a_allowlist,
        discoverable=discoverable,
        max_iterations=max_iterations,
        temperature=temperature,
        max_tokens=max_tokens,
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


def _apply_scalar_updates(
    agent: Agent,
    *,
    name: str | None,
    display_name: str | None,
    system_prompt: str | None,
    model: str | None,
    allowed_tools: list[str] | None,
    can_spawn: bool | None,
    agent_to_agent_enabled: bool | None,
    discoverable: bool | None,
    max_iterations: int | None,
    temperature: float | None,
    max_tokens: int | None,
) -> None:
    """Apply non-None scalar fields to an existing agent."""
    _fields: dict[str, Any] = {
        "name": name,
        "display_name": display_name,
        "system_prompt": system_prompt,
        "allowed_tools": allowed_tools,
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
    can_spawn: bool | None,
    agent_to_agent_enabled: bool | None,
    agent_to_agent_allowlist: list[str] | None,
    discoverable: bool | None,
    max_iterations: int | None,
    temperature: float | None,
    max_tokens: int | None,
) -> ToolResult:
    """Handle the 'update' action."""
    assert _orchestrator is not None

    if not agent_id:
        return ToolResult(
            output=json.dumps({"error": "Parameter 'agent_id' is required for update"}),
            is_error=True,
        )

    existing = await _orchestrator.get_agent(agent_id)
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
        can_spawn=can_spawn,
        agent_to_agent_enabled=agent_to_agent_enabled,
        discoverable=discoverable,
        max_iterations=max_iterations,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    _apply_a2a_update(existing, agent_to_agent_allowlist, agent_to_agent_enabled)
    _apply_trigger_updates(
        existing,
        trigger_description=trigger_description,
        trigger_keywords=trigger_keywords,
        trigger_examples=trigger_examples,
    )

    updated = await _orchestrator.update_agent(existing)

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

    existing = await _orchestrator.get_agent(agent_id)
    if existing is None:
        return ToolResult(
            output=json.dumps({"error": f"Agent not found: {agent_id}"}),
            is_error=True,
        )

    deleted = await _orchestrator.delete_agent(agent_id)

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
    agent_id: str | None,
) -> ToolResult:
    """Handle the 'get' action."""
    assert _orchestrator is not None

    if not agent_id:
        return ToolResult(
            output=json.dumps({"error": "Parameter 'agent_id' is required for get"}),
            is_error=True,
        )

    agent = await _orchestrator.get_agent(agent_id)
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
            "can_spawn": {
                "type": "boolean",
                "description": "Whether this agent can spawn sub-agents. Default: false",
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
    can_spawn: bool | object = _UNSET,
    agent_to_agent_enabled: bool | None = None,
    agent_to_agent_allowlist: list[str] | None = None,
    discoverable: bool | object = _UNSET,
    max_iterations: int | object = _UNSET,
    temperature: float | object = _UNSET,
    max_tokens: int | object = _UNSET,
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
                can_spawn=_resolve_bool(can_spawn, default=False),
                agent_to_agent_enabled=(
                    agent_to_agent_enabled if agent_to_agent_enabled is not None else False
                ),
                agent_to_agent_allowlist=agent_to_agent_allowlist,
                discoverable=_resolve_bool(discoverable, default=True),
                max_iterations=_resolve_int(max_iterations, default=10),
                temperature=_resolve_float(temperature, default=0.7),
                max_tokens=_resolve_int(max_tokens, default=4096),
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
                can_spawn=None if can_spawn is _UNSET else _resolve_bool(can_spawn, default=False),
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
            )
        elif action == "delete":
            result = await _handle_delete(ctx, agent_id=agent_id)
        elif action == "get":
            result = await _handle_get(agent_id=agent_id)
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
