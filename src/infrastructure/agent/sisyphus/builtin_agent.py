"""Built-in agent definitions and lookup helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.agent_source import AgentSource
from src.domain.model.agent.subagent import AgentModel, AgentTrigger

BUILTIN_AGENT_NAMESPACE = "builtin"
BUILTIN_SISYPHUS_ID = f"{BUILTIN_AGENT_NAMESPACE}:sisyphus"
BUILTIN_SISYPHUS_NAME = "sisyphus"
BUILTIN_SISYPHUS_DISPLAY_NAME = "Sisyphus"
BUILTIN_WORKSPACE_PLANNER_ID = f"{BUILTIN_AGENT_NAMESPACE}:workspace-planner"
BUILTIN_WORKSPACE_PLANNER_NAME = "workspace-planner"
BUILTIN_WORKSPACE_PLANNER_DISPLAY_NAME = "Workspace Planner"
DEFAULT_AGENT_TO_AGENT_ALLOWLIST = (
    BUILTIN_SISYPHUS_ID,
    BUILTIN_SISYPHUS_NAME,
)

_BUILTIN_SISYPHUS_SYSTEM_PROMPT = (
    "You are Sisyphus, the default orchestration agent. "
    "Drive work forward, use the available tools deliberately, and keep the user "
    "moving toward a concrete outcome."
)

_BUILTIN_WORKSPACE_PLANNER_SYSTEM_PROMPT = """You are builtin:workspace-planner, the read-only planning-stage agent for workspace kickoff.

Plan mode is active. You are forbidden from implementing, editing files, mutating task state,
starting services, installing dependencies, or reporting completion through any non-contract tool.

Your only successful terminal action is one call to:
workspace_submit_planning_contract(task_graph, delivery_cicd, reasoning, evidence_refs, confidence).

Required workflow:
1. Read the actual project code with read, grep, glob, or bounded bash.
2. Use that evidence to infer the current sprint DAG and sandbox-native delivery contract.
3. Call workspace_submit_planning_contract exactly once. Do not end the turn in prose.

Planning rules:
- Produce a sprint DAG in task_graph.subtasks with id, description, target_agent, depends_on, and priority.
- For software work, split separable research, planning, implementation, verification, deploy, and review work when evidence supports those phases.
- If the codebase contains multiple services, submit every required service in delivery_cicd.services.
- delivery_cicd must be sandbox-native: service_id, name, start_command, internal_port, health_path, required, and auto_open.
- Do not use keyword matching, filename matching, package-script matching, or hardcoded fallbacks as the decision maker.
- Do not invent service commands or ports. If evidence is insufficient for services, submit the DAG with delivery_cicd.services omitted or empty.
- Every submitted service must be backed by evidence_refs such as read:package.json or grep:health route.
- evidence_refs must name files or commands you actually used.
"""


def is_builtin_agent_id(agent_id: str | None) -> bool:
    """Return whether an agent id refers to a built-in agent."""
    return bool(agent_id and agent_id.startswith(f"{BUILTIN_AGENT_NAMESPACE}:"))


def is_builtin_agent_name(name: str | None) -> bool:
    """Return whether a name refers to a built-in agent."""
    normalized = (name or "").strip().lower()
    return normalized in {BUILTIN_SISYPHUS_NAME, BUILTIN_WORKSPACE_PLANNER_NAME}


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


def build_builtin_workspace_planner_agent(
    tenant_id: str,
    *,
    project_id: str | None = None,
) -> Agent:
    """Create the built-in workspace planner agent for planning-stage kickoff."""
    now = datetime.now(UTC)
    return Agent(
        id=BUILTIN_WORKSPACE_PLANNER_ID,
        tenant_id=tenant_id,
        project_id=project_id,
        name=BUILTIN_WORKSPACE_PLANNER_NAME,
        display_name=BUILTIN_WORKSPACE_PLANNER_DISPLAY_NAME,
        system_prompt=_BUILTIN_WORKSPACE_PLANNER_SYSTEM_PROMPT,
        trigger=AgentTrigger(
            description="Planning-stage workspace agent that submits DAG and delivery contract.",
            keywords=["workspace", "planner", "planning", "delivery"],
        ),
        model=AgentModel.INHERIT,
        temperature=0.0,
        max_tokens=8192,
        max_iterations=12,
        allowed_tools=[
            "read",
            "grep",
            "glob",
            "bash",
            "workspace_submit_planning_contract",
        ],
        allowed_skills=[],
        allowed_mcp_servers=[],
        can_spawn=False,
        max_spawn_depth=0,
        agent_to_agent_enabled=False,
        discoverable=False,
        source=AgentSource.BUILTIN,
        enabled=True,
        created_at=now,
        updated_at=now,
        metadata={
            "builtin_key": "workspace_planner",
            "prompt_builder": "workspace_planner",
            "runtime_plugin": "workspace_planner",
            "role": "workspace_planner",
            "contract_tool": "workspace_submit_planning_contract",
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
    if agent_id == BUILTIN_WORKSPACE_PLANNER_ID:
        return build_builtin_workspace_planner_agent(tenant_id=tenant_id, project_id=project_id)
    return None


def get_builtin_agent_by_name(
    name: str,
    tenant_id: str,
    *,
    project_id: str | None = None,
) -> Agent | None:
    """Resolve a built-in agent by name."""
    normalized = (name or "").strip().lower()
    if normalized == BUILTIN_SISYPHUS_NAME:
        return build_builtin_sisyphus_agent(tenant_id=tenant_id, project_id=project_id)
    if normalized == BUILTIN_WORKSPACE_PLANNER_NAME:
        return build_builtin_workspace_planner_agent(tenant_id=tenant_id, project_id=project_id)
    return None


def list_builtin_agents(
    tenant_id: str,
    *,
    project_id: str | None = None,
) -> list[Agent]:
    """Return the built-in agents available to a tenant."""
    return [
        build_builtin_sisyphus_agent(tenant_id=tenant_id, project_id=project_id),
        build_builtin_workspace_planner_agent(tenant_id=tenant_id, project_id=project_id),
    ]
