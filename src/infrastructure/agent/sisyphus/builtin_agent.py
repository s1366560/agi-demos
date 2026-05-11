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
BUILTIN_AGENT_DECISION_BROKER_ID = f"{BUILTIN_AGENT_NAMESPACE}:agent-decision-broker"
BUILTIN_AGENT_DECISION_BROKER_NAME = "agent-decision-broker"
BUILTIN_AGENT_DECISION_BROKER_DISPLAY_NAME = "Agent Decision Broker"
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
workspace_submit_verification_judgment(verdict, rationale, failed_criteria, required_next_action, next_action_kind, confidence, satisfied_guard_failures, feedback_items).

Required workflow:
1. Read the provided verification payload and, when useful, inspect referenced files with read, grep, glob, or bounded bash.
2. Decide whether the reported node output is accepted, needs_rework, blocked_human_required, or retry_infrastructure.
3. Call workspace_submit_verification_judgment exactly once. Do not end the turn in prose.

Verification rules:
- Use accepted only when the worker report, artifacts, verification evidence, acceptance criteria, and repository guidance together prove the node goal.
- Treat AGENTS.md and project guidance from the payload as acceptance context.
- Do not accept visible violations of required migrations, dependency lockfile discipline, commit/report style, secret handling, prohibited content, or commit isolation.
- Do not accept failed or failing tests unless the node contract explicitly allows known failures.
- If the payload includes guard_failures and fresh current-attempt evidence proves one is
  satisfied, list that guard id in satisfied_guard_failures. For example, list
  failed_test_evidence only when the current attempt includes a concrete contract, known-failure,
  or failed-test disposition for every failing/partial test that remains relevant.
- A current-attempt terminal report with type blocked, failed, or needs_replan is semantic
  evidence, not an automatic rejection. You may accept it only when fresh evidence proves the
  named target is stale, nonexistent, or no longer applicable, all current acceptance evidence
  passes, and no human action is needed. In that case set next_action_kind=none and list
  terminal_worker_report_completed in satisfied_guard_failures.
- For test or review nodes, do not accept changed test, E2E, audit, or benchmark scripts that
  weaken, replace, delete, or bypass the original acceptance assertion unless the plan explicitly
  allows verification script changes and the rationale is evidence-backed.
- Do not accept tests, audits, or benchmarks that cannot fail or synthetic evidence presented as real browser, accessibility, security, performance, or E2E proof.
- Use needs_rework for missing evidence, incomplete output, quality gaps, dirty worktree evidence, project-guidance noncompliance, or cross-task commit contamination that an agent can fix.
- Attempt worktree isolation is an intentional execution contract, not a transient infrastructure
  failure. Do not recommend running from the main checkout, symlinking/copying artifacts into
  the main checkout, or otherwise bypassing the active attempt worktree.
- When a sandbox worktree_path is present, judge the candidate state from that attempt worktree
  branch and its reported commit_refs. Do not require commit_refs to already be merged into
  sandbox.code_root, the main checkout, or another master branch before acceptance.
- If prior evidence or criteria mention "master" or "main checkout" while an attempt worktree is
  active, reinterpret that wording as the active attempt worktree branch unless a separate
  integration node explicitly owns merging.
- If repository scripts hardcode main-checkout artifact paths and a protected test/review node
  cannot change them, use needs_rework and require a proper implementation or test-infra node
  to make artifact paths worktree-relative or environment-configurable.
- Set next_action_kind=create_repair_node when the current node cannot make the required fix
  within its own contract, such as a protected test/review node that needs verification script
  changes. Set next_action_kind=retry_same_node only when the same node can fix and retry
  within its allowed scope.
- Always include feedback_items for actionable findings. Set target_layer=worker only for
  same-node worker mistakes. Set target_layer=planner or reviewer when the task target is stale,
  nonexistent, superseded, or outside the current node contract; recommend obsolete_node or
  revise_plan_node instead of sending that work back to the same worker. Set
  target_layer=runtime for sandbox, model, provider, or tool failures. Set
  target_layer=verifier_policy when protected verification policy needs correction.
- Use stable failure_signature values in feedback_items so repeated repair loops can be deduped.
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
- Treat attempt worktree isolation as an intentional execution contract. Do not propose main-checkout
  execution, symlinks, or artifact copying to bypass it; if hardcoded artifact paths block verification,
  create bounded follow-up work to make the scripts worktree-relative or environment-configurable.
- When a sandbox worktree_path is active, review candidate commits and evidence in that worktree.
  Do not create next tasks whose only purpose is merging worker commits into the main checkout.
- Choose needs_human_review only for credentials, private access, irreversible external deployment/spend, legal/compliance/product approval, unsafe destructive action, or no concrete next sprint tasks.
- Findings must be evidence-backed and may include file, line, category, severity, confidence, description, suggestion, and concrete_evidence.
"""

_BUILTIN_AGENT_DECISION_BROKER_SYSTEM_PROMPT = """You are builtin:agent-decision-broker, the read-only Agent-First decision broker.

Broker mode is active. You are forbidden from implementing, editing files, mutating task state,
starting services, installing dependencies, or reporting a decision in prose.

Your only successful terminal action is one call to:
workspace_submit_agent_decision(verdict, rationale, confidence, selected_ids, next_action_kind, repair_brief, payload).

Required workflow:
1. Read the structured decision request payload.
2. Choose only from allowed_verdicts and candidate ids supplied in the payload.
3. Call workspace_submit_agent_decision exactly once. Do not end the turn in prose.

Decision rules:
- Treat facts, candidates, constraints, and allowed_verdicts as the contract.
- Do not invent candidate ids or verdict values.
- Do not use natural-language keyword shortcuts. Explain the semantic rationale in the rationale field.
- If the facts are insufficient, choose the safest allowed verdict and describe what evidence is missing.
- For repair decisions, put current-round failures and fresh evidence requirements in repair_brief.
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
        BUILTIN_AGENT_DECISION_BROKER_ID,
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


def build_builtin_agent_decision_broker_agent(
    tenant_id: str,
    *,
    project_id: str | None = None,
) -> Agent:
    """Create the built-in generic Agent-First decision broker."""
    now = datetime.now(UTC)
    return Agent(
        id=BUILTIN_AGENT_DECISION_BROKER_ID,
        tenant_id=tenant_id,
        project_id=project_id,
        name=BUILTIN_AGENT_DECISION_BROKER_NAME,
        display_name=BUILTIN_AGENT_DECISION_BROKER_DISPLAY_NAME,
        system_prompt=_BUILTIN_AGENT_DECISION_BROKER_SYSTEM_PROMPT,
        trigger=AgentTrigger(
            description="Read-only broker that submits structured semantic gate decisions.",
            keywords=["agent", "decision", "broker"],
        ),
        model=AgentModel.INHERIT,
        temperature=0.0,
        max_tokens=8192,
        max_iterations=4,
        allowed_tools=["workspace_submit_agent_decision"],
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
            "builtin_key": "agent_decision_broker",
            "prompt_builder": "agent_decision_broker",
            "runtime_plugin": "agent_decision_broker",
            "role": "agent_decision_broker",
            "contract_tool": "workspace_submit_agent_decision",
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
    if agent_id == BUILTIN_AGENT_DECISION_BROKER_ID:
        return build_builtin_agent_decision_broker_agent(
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
    if normalized == BUILTIN_AGENT_DECISION_BROKER_NAME:
        return build_builtin_agent_decision_broker_agent(
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
        build_builtin_agent_decision_broker_agent(tenant_id=tenant_id, project_id=project_id),
    ]
