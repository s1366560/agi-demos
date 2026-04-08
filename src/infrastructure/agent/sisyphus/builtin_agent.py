"""Built-in Sisyphus agent definition and lookup helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.agent_source import AgentSource
from src.domain.model.agent.subagent import AgentModel, AgentTrigger

BUILTIN_AGENT_NAMESPACE = "builtin"
BUILTIN_SISYPHUS_ID = f"{BUILTIN_AGENT_NAMESPACE}:sisyphus"
BUILTIN_SISYPHUS_NAME = "sisyphus"
BUILTIN_SISYPHUS_DISPLAY_NAME = "Sisyphus"

_BUILTIN_SISYPHUS_SYSTEM_PROMPT = (
    "You are Sisyphus, the default orchestration agent. "
    "Drive work forward, use the available tools deliberately, and keep the user "
    "moving toward a concrete outcome."
)


def is_builtin_agent_id(agent_id: str | None) -> bool:
    """Return whether an agent id refers to a built-in agent."""
    return bool(agent_id and agent_id.startswith(f"{BUILTIN_AGENT_NAMESPACE}:"))


def is_builtin_agent_name(name: str | None) -> bool:
    """Return whether a name refers to a built-in agent."""
    normalized = (name or "").strip().lower()
    return normalized == BUILTIN_SISYPHUS_NAME


def build_builtin_sisyphus_agent(
    tenant_id: str,
    *,
    project_id: str | None = None,
) -> Agent:
    """Create the built-in Sisyphus agent for a tenant/project context."""
    now = datetime.now(UTC)
    return Agent(
        id=BUILTIN_SISYPHUS_ID,
        tenant_id=tenant_id,
        project_id=project_id,
        name=BUILTIN_SISYPHUS_NAME,
        display_name=BUILTIN_SISYPHUS_DISPLAY_NAME,
        system_prompt=_BUILTIN_SISYPHUS_SYSTEM_PROMPT,
        trigger=AgentTrigger(
            description="Default orchestration agent for general-purpose work.",
            keywords=["default", "general", "sisyphus"],
        ),
        model=AgentModel.INHERIT,
        temperature=0.2,
        max_tokens=8192,
        max_iterations=20,
        allowed_tools=["*"],
        allowed_skills=[],
        allowed_mcp_servers=["*"],
        can_spawn=True,
        max_spawn_depth=6,
        agent_to_agent_enabled=True,
        discoverable=True,
        source=AgentSource.BUILTIN,
        enabled=True,
        created_at=now,
        updated_at=now,
        metadata={
            "builtin_key": "sisyphus",
            "prompt_builder": "sisyphus",
            "runtime_plugin": "sisyphus",
            "role": "primary_orchestrator",
        },
    )


def get_builtin_agent_by_id(
    agent_id: str,
    tenant_id: str,
    *,
    project_id: str | None = None,
) -> Agent | None:
    """Resolve a built-in agent by id."""
    if agent_id == BUILTIN_SISYPHUS_ID:
        return build_builtin_sisyphus_agent(tenant_id=tenant_id, project_id=project_id)
    return None


def get_builtin_agent_by_name(
    name: str,
    tenant_id: str,
    *,
    project_id: str | None = None,
) -> Agent | None:
    """Resolve a built-in agent by name."""
    if is_builtin_agent_name(name):
        return build_builtin_sisyphus_agent(tenant_id=tenant_id, project_id=project_id)
    return None


def list_builtin_agents(
    tenant_id: str,
    *,
    project_id: str | None = None,
) -> list[Agent]:
    """Return the built-in agents available to a tenant."""
    return [build_builtin_sisyphus_agent(tenant_id=tenant_id, project_id=project_id)]
