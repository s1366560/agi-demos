"""Unit tests for workspace plan terminal contract tools."""

from __future__ import annotations

import json

import pytest

from src.infrastructure.agent.sisyphus.builtin_agent import (
    BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID,
    BUILTIN_WORKSPACE_SUPERVISOR_ID,
    BUILTIN_WORKSPACE_VERIFIER_ID,
)
from src.infrastructure.agent.tools import workspace_plan_contract_tools as plan_contract_tools
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_CONTRACT,
    WORKSPACE_ROLE_WORKER,
)

pytestmark = pytest.mark.unit


def _ctx(
    *,
    selected_agent_id: str,
    workspace_session_role: str = WORKSPACE_ROLE_CONTRACT,
) -> ToolContext:
    return ToolContext(
        session_id="workspace-plan-session",
        message_id="msg-1",
        call_id="call-1",
        agent_name="workspace-plan-agent",
        conversation_id="conv-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="system",
        runtime_context={
            "selected_agent_id": selected_agent_id,
            "workspace_id": "ws-1",
            "workspace_session_role": workspace_session_role,
        },
    )


async def test_verification_judgment_rejects_non_verifier_agent() -> None:
    result = await plan_contract_tools.workspace_submit_verification_judgment_tool.execute(
        _ctx(selected_agent_id="builtin:workspace-planner"),
        verdict="accepted",
        rationale="Evidence is sufficient.",
        failed_criteria=[],
        required_next_action="",
        confidence=0.9,
    )

    assert result.is_error is True
    assert BUILTIN_WORKSPACE_VERIFIER_ID in json.loads(result.output)["error"]


async def test_verification_judgment_rejects_legacy_worker_role() -> None:
    result = await plan_contract_tools.workspace_submit_verification_judgment_tool.execute(
        _ctx(
            selected_agent_id=BUILTIN_WORKSPACE_VERIFIER_ID,
            workspace_session_role=WORKSPACE_ROLE_WORKER,
        ),
        verdict="accepted",
        rationale="Evidence is sufficient.",
        failed_criteria=[],
        required_next_action="",
        confidence=0.9,
    )

    assert result.is_error is True
    assert "workspace contract session" in json.loads(result.output)["error"]


async def test_verification_judgment_captures_structured_payload() -> None:
    result = await plan_contract_tools.workspace_submit_verification_judgment_tool.execute(
        _ctx(selected_agent_id=BUILTIN_WORKSPACE_VERIFIER_ID),
        verdict="needs_rework",
        rationale="A required test failed.",
        failed_criteria=["failed_test_evidence"],
        satisfied_guard_failures=["clean_worktree_after_commit"],
        required_next_action="fix failing tests",
        next_action_kind="create_repair_node",
        feedback_items=[
            {
                "target_layer": "planner",
                "feedback_kind": "test_policy_conflict",
                "severity": "blocking",
                "recommended_action": "create_repair_node",
                "summary": "Protected review script needs an authorized infra repair.",
                "evidence_refs": ["guard:verification_script_mutation"],
                "failure_signature": "review-script-path-guard",
            }
        ],
        confidence=0.82,
    )

    assert result.is_error is False
    assert result.metadata["verification_judgment"] == {
        "verdict": "needs_rework",
        "rationale": "A required test failed.",
        "failed_criteria": ["failed_test_evidence"],
        "satisfied_guard_failures": ["clean_worktree_after_commit"],
        "required_next_action": "fix failing tests",
        "next_action_kind": "create_repair_node",
        "confidence": 0.82,
        "feedback_items": [
            {
                "target_layer": "planner",
                "feedback_kind": "test_policy_conflict",
                "severity": "blocking",
                "recommended_action": "create_repair_node",
                "summary": "Protected review script needs an authorized infra repair.",
                "evidence_refs": ["guard:verification_script_mutation"],
                "failure_signature": "review-script-path-guard",
            }
        ],
    }


async def test_verification_judgment_defaults_accepted_next_action_to_none() -> None:
    result = await plan_contract_tools.workspace_submit_verification_judgment_tool.execute(
        _ctx(selected_agent_id=BUILTIN_WORKSPACE_VERIFIER_ID),
        verdict="accepted",
        rationale="Fresh evidence satisfies the node.",
        failed_criteria=[],
        required_next_action="",
        confidence=0.93,
    )

    assert result.is_error is False
    assert result.metadata["verification_judgment"]["next_action_kind"] == "none"


async def test_iteration_review_rejects_non_reviewer_agent() -> None:
    result = await plan_contract_tools.workspace_submit_iteration_review_tool.execute(
        _ctx(selected_agent_id=BUILTIN_WORKSPACE_VERIFIER_ID),
        verdict="complete_goal",
        confidence=0.9,
        summary="Done.",
    )

    assert result.is_error is True
    assert BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID in json.loads(result.output)["error"]


async def test_iteration_review_captures_next_tasks_and_findings() -> None:
    result = await plan_contract_tools.workspace_submit_iteration_review_tool.execute(
        _ctx(selected_agent_id=BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID),
        verdict="continue_next_iteration",
        confidence=0.88,
        summary="Needs one more proof sprint.",
        next_sprint_goal="Collect browser proof.",
        feedback_items=["Browser evidence is missing."],
        next_tasks=[
            {
                "id": "browser-proof",
                "description": "Run browser parity verification.",
                "phase": "test",
                "expected_artifacts": ["screenshot"],
            }
        ],
        findings=[
            {
                "file": "src/app.py",
                "line": 10,
                "category": "contract drift",
                "severity": "WARNING",
                "raw_confidence": 80,
                "description": "Frontend and backend differ.",
                "suggestion": "Share the contract.",
                "concrete_evidence": True,
            }
        ],
    )

    assert result.is_error is False
    payload = result.metadata["iteration_review"]
    assert payload["verdict"] == "continue_next_iteration"
    assert payload["next_tasks"][0]["id"] == "browser-proof"
    assert payload["findings"][0]["severity"] == "WARNING"


async def test_supervisor_decision_rejects_non_supervisor_agent() -> None:
    result = await plan_contract_tools.workspace_submit_supervisor_decision_tool.execute(
        _ctx(selected_agent_id=BUILTIN_WORKSPACE_VERIFIER_ID),
        action="retry_same_node",
        rationale="Runtime decision must be retried.",
        confidence=0.7,
    )

    assert result.is_error is True
    assert BUILTIN_WORKSPACE_SUPERVISOR_ID in json.loads(result.output)["error"]


async def test_supervisor_decision_requires_rationale() -> None:
    result = await plan_contract_tools.workspace_submit_supervisor_decision_tool.execute(
        _ctx(selected_agent_id=BUILTIN_WORKSPACE_SUPERVISOR_ID),
        action="retry_same_node",
        rationale="",
        confidence=0.7,
    )

    assert result.is_error is True
    assert "rationale" in json.loads(result.output)["error"]


async def test_supervisor_decision_rejects_confidence_out_of_range() -> None:
    result = await plan_contract_tools.workspace_submit_supervisor_decision_tool.execute(
        _ctx(selected_agent_id=BUILTIN_WORKSPACE_SUPERVISOR_ID),
        action="retry_same_node",
        rationale="Runtime decision must be retried.",
        confidence=1.5,
    )

    assert result.is_error is True
    assert "confidence" in json.loads(result.output)["error"]


async def test_supervisor_decision_captures_structured_payload() -> None:
    result = await plan_contract_tools.workspace_submit_supervisor_decision_tool.execute(
        _ctx(selected_agent_id=BUILTIN_WORKSPACE_SUPERVISOR_ID),
        action="create_repair_node",
        rationale="Verifier feedback requires a separate repair node.",
        confidence=0.86,
        feedback_items=[
            {
                "target_layer": "planner",
                "recommended_action": "create_repair_node",
                "summary": "Protected test infrastructure needs a scoped repair.",
            }
        ],
        repair_brief={"failed_items": ["protected test path"]},
        event_payload={"disposition": "needs_separate_repair"},
    )

    assert result.is_error is False
    assert result.metadata["supervisor_decision"] == {
        "action": "create_repair_node",
        "rationale": "Verifier feedback requires a separate repair node.",
        "confidence": 0.86,
        "feedback_items": [
            {
                "target_layer": "planner",
                "recommended_action": "create_repair_node",
                "summary": "Protected test infrastructure needs a scoped repair.",
            }
        ],
        "repair_brief": {"failed_items": ["protected test path"]},
        "event_payload": {"disposition": "needs_separate_repair"},
    }
