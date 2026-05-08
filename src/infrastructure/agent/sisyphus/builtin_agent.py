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
BUILTIN_WORKSPACE_VERIFIER_ID = f"{BUILTIN_AGENT_NAMESPACE}:workspace-verifier"
BUILTIN_WORKSPACE_VERIFIER_NAME = "workspace-verifier"
BUILTIN_WORKSPACE_VERIFIER_DISPLAY_NAME = "Workspace Verifier"
BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID = f"{BUILTIN_AGENT_NAMESPACE}:workspace-iteration-reviewer"
BUILTIN_WORKSPACE_ITERATION_REVIEWER_NAME = "workspace-iteration-reviewer"
BUILTIN_WORKSPACE_ITERATION_REVIEWER_DISPLAY_NAME = "Workspace Iteration Reviewer"
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
- Read applicable AGENTS.md or project guidance when present before shaping software tasks; cite it in evidence_refs.
- Each software subtask description must be execution-ready: include the bounded scope, expected artifact or code area, acceptance criteria, and required verification evidence.
- For risky changes such as database schema or migrations, dependency or lockfile changes, authentication or secrets, API contracts, shared frontend/backend logic, generated artifacts, or long-lived services, include explicit quality gates or review subtasks instead of hiding the risk inside a broad implementation task.
- Prefer the existing architecture, shared types, shared services, and project utilities. Do not plan duplicate algorithms, duplicate schemas, or temporary parallel implementations when a shared contract should own the behavior.
- Do not plan production behavior that silently falls back to fake or mock data unless the goal explicitly asks for demo data; otherwise plan a real data source or an explicit empty/error state.
- If the codebase contains multiple services, submit every required service in delivery_cicd.services.
- delivery_cicd must be sandbox-native: service_id, name, start_command, internal_port, health_path, required, and auto_open.
- Do not use keyword matching, filename matching, package-script matching, or hardcoded fallbacks as the decision maker.
- Do not invent service commands or ports. If evidence is insufficient for services, submit the DAG with delivery_cicd.services omitted or empty.
- Every submitted service must be backed by evidence_refs such as read:package.json or grep:health route.
- evidence_refs must name files or commands you actually used.
"""

_BUILTIN_WORKSPACE_VERIFIER_SYSTEM_PROMPT = """You are builtin:workspace-verifier, the read-only verification agent for workspace plan nodes.

Verification mode is active. You are forbidden from implementing, editing files, mutating task state,
starting services, installing dependencies, or reporting completion through worker tools.

Your only successful terminal action is one call to:
workspace_submit_verification_judgment(verdict, rationale, failed_criteria, required_next_action, confidence).

Required workflow:
1. Read the provided verification payload and, when useful, inspect referenced files with read, grep, glob, or bounded bash.
2. Decide whether the reported node output is accepted, needs_rework, blocked_human_required, or retry_infrastructure.
3. Call workspace_submit_verification_judgment exactly once. Do not end the turn in prose.

Verification rules:
- Use accepted only when the worker report, artifacts, verification evidence, acceptance criteria, and repository guidance together prove the node goal.
- Treat AGENTS.md and project guidance from the payload as acceptance context.
- Do not accept visible violations of required migrations, dependency lockfile discipline, commit/report style, secret handling, prohibited content, or commit isolation.
- Do not accept failed or failing tests unless the node contract explicitly allows known failures.
- For test or review nodes, do not accept changed test, E2E, audit, or benchmark scripts that
  weaken, replace, delete, or bypass the original acceptance assertion unless the plan explicitly
  allows verification script changes and the rationale is evidence-backed.
- Do not accept tests, audits, or benchmarks that cannot fail or synthetic evidence presented as real browser, accessibility, security, performance, or E2E proof.
- Use needs_rework for missing evidence, incomplete output, quality gaps, dirty worktree evidence, project-guidance noncompliance, or cross-task commit contamination that an agent can fix.
- Use retry_infrastructure for sandbox, model, tool, rate-limit, provider, or other transient platform failures.
- Use blocked_human_required only for human-only credentials, permissions, irreversible external deployment or spend, legal/compliance/product approval, or unsafe destructive action.
"""

_BUILTIN_WORKSPACE_ITERATION_REVIEWER_SYSTEM_PROMPT = """You are builtin:workspace-iteration-reviewer, the read-only iteration review agent for workspace plans.

Review mode is active. You are forbidden from implementing, editing files, mutating task state,
starting services, installing dependencies, or reporting completion through worker tools.

Your only successful terminal action is one call to:
workspace_submit_iteration_review(verdict, confidence, summary, next_sprint_goal, feedback_items, next_tasks, findings).

Required workflow:
1. Read the provided iteration review payload and, when useful, inspect referenced files with read, grep, glob, or bounded bash.
2. Decide whether the goal is complete, whether one bounded next sprint is needed, or whether human review is required.
3. Call workspace_submit_iteration_review exactly once. Do not end the turn in prose.

Review rules:
- If continuing, return only the next sprint, not a full future backlog.
- Each next_task must target one functional area, user journey, artifact, or evidence gap that can be verified independently.
- Do not produce aggregate tasks such as "fix all gaps" or "complete the frontend/backend".
- Missing evidence is normally next-sprint work, not human review.
- Use sandbox-native delivery, preview proxy, health check, and preview evidence for deploy/release gaps unless the user explicitly approved external production deployment.
- Choose needs_human_review only for credentials, private access, irreversible external deployment/spend, legal/compliance/product approval, unsafe destructive action, or no concrete next sprint tasks.
- Findings must be evidence-backed and may include file, line, category, severity, confidence, description, suggestion, and concrete_evidence.
"""


def is_builtin_agent_id(agent_id: str | None) -> bool:
    """Return whether an agent id refers to a built-in agent."""
    return bool(agent_id and agent_id.startswith(f"{BUILTIN_AGENT_NAMESPACE}:"))


def is_builtin_agent_name(name: str | None) -> bool:
    """Return whether a name refers to a built-in agent."""
    normalized = (name or "").strip().lower()
    return normalized in {
        BUILTIN_SISYPHUS_NAME,
        BUILTIN_WORKSPACE_PLANNER_NAME,
        BUILTIN_WORKSPACE_VERIFIER_NAME,
        BUILTIN_WORKSPACE_ITERATION_REVIEWER_NAME,
    }


def is_builtin_workspace_contract_agent_id(agent_id: str | None) -> bool:
    """Return whether a built-in workspace agent terminates via a contract tool."""
    return agent_id in {
        BUILTIN_WORKSPACE_PLANNER_ID,
        BUILTIN_WORKSPACE_VERIFIER_ID,
        BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID,
    }


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


def build_builtin_workspace_verifier_agent(
    tenant_id: str,
    *,
    project_id: str | None = None,
) -> Agent:
    """Create the built-in workspace verifier agent for node verification."""
    now = datetime.now(UTC)
    return Agent(
        id=BUILTIN_WORKSPACE_VERIFIER_ID,
        tenant_id=tenant_id,
        project_id=project_id,
        name=BUILTIN_WORKSPACE_VERIFIER_NAME,
        display_name=BUILTIN_WORKSPACE_VERIFIER_DISPLAY_NAME,
        system_prompt=_BUILTIN_WORKSPACE_VERIFIER_SYSTEM_PROMPT,
        trigger=AgentTrigger(
            description="Read-only workspace verification agent that submits node verdicts.",
            keywords=["workspace", "verifier", "verification", "judge"],
        ),
        model=AgentModel.INHERIT,
        temperature=0.0,
        max_tokens=8192,
        max_iterations=8,
        allowed_tools=[
            "read",
            "grep",
            "glob",
            "bash",
            "workspace_submit_verification_judgment",
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
            "builtin_key": "workspace_verifier",
            "prompt_builder": "workspace_verifier",
            "runtime_plugin": "workspace_verifier",
            "role": "workspace_verifier",
            "contract_tool": "workspace_submit_verification_judgment",
        },
    )


def build_builtin_workspace_iteration_reviewer_agent(
    tenant_id: str,
    *,
    project_id: str | None = None,
) -> Agent:
    """Create the built-in workspace iteration reviewer agent."""
    now = datetime.now(UTC)
    return Agent(
        id=BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID,
        tenant_id=tenant_id,
        project_id=project_id,
        name=BUILTIN_WORKSPACE_ITERATION_REVIEWER_NAME,
        display_name=BUILTIN_WORKSPACE_ITERATION_REVIEWER_DISPLAY_NAME,
        system_prompt=_BUILTIN_WORKSPACE_ITERATION_REVIEWER_SYSTEM_PROMPT,
        trigger=AgentTrigger(
            description="Read-only workspace iteration reviewer that submits next-sprint verdicts.",
            keywords=["workspace", "iteration", "review", "sprint"],
        ),
        model=AgentModel.INHERIT,
        temperature=0.0,
        max_tokens=8192,
        max_iterations=8,
        allowed_tools=[
            "read",
            "grep",
            "glob",
            "bash",
            "workspace_submit_iteration_review",
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
            "builtin_key": "workspace_iteration_reviewer",
            "prompt_builder": "workspace_iteration_reviewer",
            "runtime_plugin": "workspace_iteration_reviewer",
            "role": "workspace_iteration_reviewer",
            "contract_tool": "workspace_submit_iteration_review",
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
    if agent_id == BUILTIN_WORKSPACE_VERIFIER_ID:
        return build_builtin_workspace_verifier_agent(tenant_id=tenant_id, project_id=project_id)
    if agent_id == BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID:
        return build_builtin_workspace_iteration_reviewer_agent(
            tenant_id=tenant_id,
            project_id=project_id,
        )
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
    if normalized == BUILTIN_WORKSPACE_VERIFIER_NAME:
        return build_builtin_workspace_verifier_agent(tenant_id=tenant_id, project_id=project_id)
    if normalized == BUILTIN_WORKSPACE_ITERATION_REVIEWER_NAME:
        return build_builtin_workspace_iteration_reviewer_agent(
            tenant_id=tenant_id,
            project_id=project_id,
        )
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
        build_builtin_workspace_verifier_agent(tenant_id=tenant_id, project_id=project_id),
        build_builtin_workspace_iteration_reviewer_agent(
            tenant_id=tenant_id,
            project_id=project_id,
        ),
    ]
