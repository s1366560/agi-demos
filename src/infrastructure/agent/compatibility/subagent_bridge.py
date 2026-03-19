"""Bidirectional converter between Agent and SubAgent entities.

Enables gradual migration from SubAgent-only code to the new
multi-agent Agent entity while preserving backward compatibility.
"""

from __future__ import annotations

import logging

from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.agent_source import AgentSource
from src.domain.model.agent.subagent import (
    AgentTrigger,
    SubAgent,
)
from src.domain.model.agent.subagent_source import SubAgentSource
from src.domain.model.agent.workspace_config import WorkspaceConfig

logger = logging.getLogger(__name__)

_SOURCE_AGENT_TO_SUBAGENT: dict[AgentSource, SubAgentSource] = {
    AgentSource.FILESYSTEM: SubAgentSource.FILESYSTEM,
    AgentSource.DATABASE: SubAgentSource.DATABASE,
}

_SOURCE_SUBAGENT_TO_AGENT: dict[SubAgentSource, AgentSource] = {
    SubAgentSource.FILESYSTEM: AgentSource.FILESYSTEM,
    SubAgentSource.DATABASE: AgentSource.DATABASE,
}


def agent_to_subagent(agent: Agent) -> SubAgent:
    """Convert an Agent (L4) entity to a SubAgent (L3) entity.

    Shared fields are copied directly.  Agent-only fields
    (persona_files, bindings, workspace_*, can_spawn,
    max_spawn_depth, agent_to_agent_enabled, discoverable)
    are dropped because SubAgent has no place for them.

    Args:
        agent: The Agent entity to convert.

    Returns:
        A SubAgent entity with equivalent shared field values.
    """
    source = _SOURCE_AGENT_TO_SUBAGENT.get(agent.source, SubAgentSource.DATABASE)

    return SubAgent(
        id=agent.id,
        tenant_id=agent.tenant_id,
        project_id=agent.project_id,
        name=agent.name,
        display_name=agent.display_name,
        system_prompt=agent.system_prompt,
        trigger=AgentTrigger(
            description=agent.trigger.description,
            examples=list(agent.trigger.examples),
            keywords=list(agent.trigger.keywords),
        ),
        model=agent.model,
        color="blue",
        allowed_tools=list(agent.allowed_tools),
        allowed_skills=list(agent.allowed_skills),
        allowed_mcp_servers=list(agent.allowed_mcp_servers),
        max_tokens=agent.max_tokens,
        temperature=agent.temperature,
        max_iterations=agent.max_iterations,
        enabled=agent.enabled,
        total_invocations=agent.total_invocations,
        avg_execution_time_ms=agent.avg_execution_time_ms,
        success_rate=agent.success_rate,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        metadata=dict(agent.metadata) if agent.metadata else None,
        source=source,
        file_path=None,
        max_retries=agent.max_retries,
        fallback_models=list(agent.fallback_models),
    )


def subagent_to_agent(
    subagent: SubAgent,
    tenant_id: str,
) -> Agent:
    """Convert a SubAgent (L3) entity to an Agent (L4) entity.

    Shared fields are copied directly.  Agent-only fields are
    filled with safe defaults:
    - persona_files: empty
    - bindings: empty
    - workspace_config: default WorkspaceConfig
    - can_spawn / agent_to_agent_enabled: False
    - discoverable: True
    - source: mapped from SubAgentSource

    Args:
        subagent: The SubAgent entity to convert.
        tenant_id: Tenant ID to set on the Agent.  Typically the
            same as ``subagent.tenant_id``, but callers may
            override.

    Returns:
        An Agent entity with equivalent shared field values
        and safe defaults for Agent-only fields.
    """
    source = _SOURCE_SUBAGENT_TO_AGENT.get(subagent.source, AgentSource.DATABASE)

    return Agent(
        id=subagent.id,
        tenant_id=tenant_id,
        project_id=subagent.project_id,
        name=subagent.name,
        display_name=subagent.display_name,
        system_prompt=subagent.system_prompt,
        trigger=AgentTrigger(
            description=subagent.trigger.description,
            examples=list(subagent.trigger.examples),
            keywords=list(subagent.trigger.keywords),
        ),
        model=subagent.model,
        temperature=subagent.temperature,
        max_tokens=subagent.max_tokens,
        max_iterations=subagent.max_iterations,
        allowed_tools=list(subagent.allowed_tools),
        allowed_skills=list(subagent.allowed_skills),
        allowed_mcp_servers=list(subagent.allowed_mcp_servers),
        persona_files=[],
        bindings=[],
        workspace_dir=None,
        workspace_config=WorkspaceConfig(),
        can_spawn=False,
        max_spawn_depth=3,
        agent_to_agent_enabled=False,
        discoverable=True,
        source=source,
        enabled=subagent.enabled,
        max_retries=subagent.max_retries,
        fallback_models=list(subagent.fallback_models),
        total_invocations=subagent.total_invocations,
        avg_execution_time_ms=subagent.avg_execution_time_ms,
        success_rate=subagent.success_rate,
        created_at=subagent.created_at,
        updated_at=subagent.updated_at,
        metadata=(dict(subagent.metadata) if subagent.metadata else None),
    )
