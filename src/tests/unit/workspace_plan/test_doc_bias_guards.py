"""Regression tests locking in anti-doc-bias clauses across planner prompts.

Background: prior workspace iterations produced doc-only DAGs ("write SPEC.md",
"create release checklist", "reconcile reports") because several prompts
explicitly listed "documentation" as a canonical software-delivery phase. These
snapshot tests ensure that bias does not regress.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_task_decomposer_prompt_has_implementation_first_clause() -> None:
    from src.infrastructure.agent.subagent.task_decomposer import (
        _DECOMPOSITION_REPAIR_PROMPT,
        _DECOMPOSITION_SYSTEM_PROMPT,
    )

    # The canonical phase list must no longer include a standalone documentation phase.
    assert "documentation, and verification" not in _DECOMPOSITION_SYSTEM_PROMPT, (
        "decomposer system prompt regressed: documentation must not be a canonical phase"
    )
    assert "IMPLEMENTATION FIRST" in _DECOMPOSITION_SYSTEM_PROMPT
    # The repair prompt must mirror the same rule.
    assert "documentation, and verification" not in _DECOMPOSITION_REPAIR_PROMPT, (
        "decomposer repair prompt regressed: documentation must not be a canonical phase"
    )
    assert "Embed required documentation" in _DECOMPOSITION_REPAIR_PROMPT


def test_builtin_workspace_planner_prompt_has_anti_doc_clause() -> None:
    from src.infrastructure.agent.sisyphus import builtin_agent

    prompt = builtin_agent._BUILTIN_WORKSPACE_PLANNER_SYSTEM_PROMPT
    assert "IMPLEMENTATION FIRST" in prompt
    assert "Acceptance evidence" in prompt
    assert "BUILD-REPORT.md" in prompt or "INDEX.md" in prompt


def test_builtin_workspace_iteration_reviewer_prompt_has_anti_doc_clause() -> None:
    from src.infrastructure.agent.sisyphus import builtin_agent

    prompt = builtin_agent._BUILTIN_WORKSPACE_ITERATION_REVIEWER_SYSTEM_PROMPT
    assert "IMPLEMENTATION FIRST" in prompt
    assert "Repair verification blockers for" in prompt  # anti-loop clause
    assert "Acceptance/evidence artifacts" in prompt
    assert "sandbox Docker runtime is unavailable" in prompt
    assert "deployed container stack" in prompt


def test_iteration_review_payload_omits_documentation_capability() -> None:
    from src.domain.ports.services.iteration_review_port import IterationReviewContext
    from src.infrastructure.agent.workspace_plan.iteration_review import _user_payload

    ctx = IterationReviewContext(
        workspace_id="ws-1",
        plan_id="plan-1",
        iteration_index=1,
        goal_title="ship a webapp",
        goal_description="build code, tests, infra",
        completed_tasks=(),
        deliverables=(),
        feedback_items=(),
        max_next_tasks=5,
    )
    payload = _user_payload(ctx)
    assert "code, test, documentation, and sandbox-native release-readiness" not in payload, (
        "iteration_review payload regressed: documentation capability must be removed"
    )
    assert "implementation_first_rules" in payload


def test_iteration_review_payload_exposes_sandbox_docker_runtime_constraint() -> None:
    from src.domain.ports.services.iteration_review_port import IterationReviewContext
    from src.infrastructure.agent.workspace_plan.iteration_review import _user_payload

    ctx = IterationReviewContext(
        workspace_id="ws-1",
        plan_id="plan-1",
        iteration_index=1,
        goal_title="ship a webapp",
        goal_description="build code, tests, infra",
        completed_tasks=(
            {
                "id": "deploy",
                "title": "verify Drone docker deployment",
                "verification_summary": (
                    "Docker runtime is unavailable in the sandbox, but Drone pipeline "
                    "and registry manifest checks passed."
                ),
            },
        ),
        deliverables=(),
        feedback_items=(),
        max_next_tasks=5,
    )
    payload = _user_payload(ctx)

    assert '"runtime_constraints"' in payload
    assert '"sandbox_docker_runtime"' in payload
    assert '"available": false' in payload
    assert "Drone docker deploy-step success plus registry manifest/tag checks" in payload


def test_workspace_software_decomposition_context_forbids_doc_only_tasks() -> None:
    from src.infrastructure.agent.workspace.goal_runtime.v2_bridge import (
        _workspace_iteration_decomposition_context,
    )

    ctx = _workspace_iteration_decomposition_context(
        workspace_type="software_development",
        max_subtasks=8,
    )
    assert ctx is not None
    assert "IMPLEMENTATION FIRST" in ctx
    assert "No subtask may be purely documentation" in ctx
    assert "INDEX.md" in ctx


def test_workspace_non_software_decomposition_context_returns_none() -> None:
    from src.infrastructure.agent.workspace.goal_runtime.v2_bridge import (
        _workspace_iteration_decomposition_context,
    )

    assert (
        _workspace_iteration_decomposition_context(workspace_type="research", max_subtasks=8)
        is None
    )


def test_architect_role_no_longer_advertises_documentation_capability() -> None:
    from src.infrastructure.agent.workspace_plan.outbox_handlers import _AUTO_TEAM_ROLES

    architect = next(role for role in _AUTO_TEAM_ROLES if role["key"] == "architect")
    assert "documentation" not in architect["capabilities"], (
        "architect role regressed: 'documentation' capability biases routing toward doc tasks"
    )


def test_repair_title_does_not_nest_when_failing_node_is_already_repair() -> None:
    """Walk repair_for_node_id chain so we never produce 'Repair … Repair …' titles."""
    from src.domain.model.workspace_plan import (
        Plan,
        PlanNode,
        PlanNodeId,
        PlanNodeKind,
        PlanStatus,
    )
    from src.infrastructure.agent.workspace_plan.planner import _repair_title

    goal_id = PlanNodeId("goal-1")
    plan = Plan(
        id="plan-1",
        workspace_id="ws-1",
        goal_id=goal_id,
        status=PlanStatus.ACTIVE,
    )
    plan.add_node(
        PlanNode(
            id=goal_id.value,
            plan_id="plan-1",
            parent_id=None,
            kind=PlanNodeKind.GOAL,
            title="root",
            description="",
        )
    )
    original = PlanNode(
        id="orig-1",
        plan_id="plan-1",
        parent_id=goal_id,
        kind=PlanNodeKind.TASK,
        title="Re-run full test suite (203/203)",
        description="",
    )
    plan.add_node(original)
    first_repair = PlanNode(
        id="rep-1",
        plan_id="plan-1",
        parent_id=goal_id,
        kind=PlanNodeKind.TASK,
        title="Repair verification blockers for Re-run full test suite (203/203)",
        description="",
        metadata={"repair_for_node_id": "orig-1"},
    )
    plan.add_node(first_repair)

    title = _repair_title(first_repair, plan)
    assert title.count("Repair verification blockers for") == 1, title
    assert "Re-run full test suite" in title
