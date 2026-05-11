"""Unit tests for workspace plan terminal contract tools."""

from __future__ import annotations

import json

import pytest

from src.infrastructure.agent.sisyphus.builtin_agent import (
    BUILTIN_AGENT_DECISION_BROKER_ID,
    BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID,
    BUILTIN_WORKSPACE_VERIFIER_ID,
)
from src.infrastructure.agent.tools import workspace_plan_contract_tools as plan_contract_tools
from src.infrastructure.agent.tools.context import ToolContext

pytestmark = pytest.mark.unit


def _ctx(*, selected_agent_id: str) -> ToolContext:
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
            "workspace_session_role": "worker",
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


async def test_verification_judgment_captures_structured_payload() -> None:
    result = await plan_contract_tools.workspace_submit_verification_judgment_tool.execute(
        _ctx(selected_agent_id=BUILTIN_WORKSPACE_VERIFIER_ID),
        verdict="needs_rework",
        rationale="A required test failed.",
        failed_criteria=["failed_test_evidence"],
        satisfied_guard_failures=["clean_worktree_after_commit"],
        required_next_action="fix failing tests",
        next_action_kind="create_repair_node",
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


async def test_agent_decision_rejects_non_broker_agent() -> None:
    result = await plan_contract_tools.workspace_submit_agent_decision_tool.execute(
        _ctx(selected_agent_id=BUILTIN_WORKSPACE_VERIFIER_ID),
        decision_kind="execution_route",
        verdict="route_to_worker",
        rationale="Route by structured facts.",
        confidence=0.8,
    )

    assert result.is_error is True
    assert BUILTIN_AGENT_DECISION_BROKER_ID in json.loads(result.output)["error"]


async def test_agent_decision_captures_structured_payload() -> None:
    result = await plan_contract_tools.workspace_submit_agent_decision_tool.execute(
        _ctx(selected_agent_id=BUILTIN_AGENT_DECISION_BROKER_ID),
        decision_kind="execution_route",
        verdict="route_to_worker",
        rationale="Route by structured facts.",
        confidence=0.8,
        selected_ids=["worker"],
        next_action_kind="dispatch",
        payload={"route": "worker"},
    )

    assert result.is_error is False
    assert result.metadata["agent_decision"] == {
        "decision_kind": "execution_route",
        "verdict": "route_to_worker",
        "rationale": "Route by structured facts.",
        "confidence": 0.8,
        "selected_ids": ["worker"],
        "next_action_kind": "dispatch",
        "payload": {"route": "worker"},
    }
