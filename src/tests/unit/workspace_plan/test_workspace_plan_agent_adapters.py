"""Tests for builtin-agent backed workspace plan adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.ports.services.iteration_review_port import IterationReviewContext
from src.domain.ports.services.workspace_verification_judge_port import (
    WorkspaceVerificationJudgeRequest,
)
from src.infrastructure.agent.sisyphus.builtin_agent import (
    BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID,
    BUILTIN_WORKSPACE_VERIFIER_ID,
)
from src.infrastructure.agent.workspace_plan.iteration_review import (
    RuntimeWorkspaceIterationReviewAgentTurnRunner,
    WorkspaceIterationReviewAgentProvider,
    _iteration_review_from_event,
)
from src.infrastructure.agent.workspace_plan.verification_judge import (
    RuntimeWorkspaceVerifierAgentTurnRunner,
    WorkspaceVerifierAgentJudge,
)

pytestmark = pytest.mark.unit


@dataclass
class _VerifierRunner:
    payload: dict[str, Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def run_verification_turn(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.payload


@dataclass
class _ReviewRunner:
    payload: dict[str, Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def run_review_turn(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.payload


async def test_workspace_verifier_agent_judge_uses_builtin_agent_turn_runner() -> None:
    runner = _VerifierRunner(
        {
            "verdict": "needs_rework",
            "rationale": "Falling tests remain.",
            "failed_criteria": ["failed_test_evidence"],
            "satisfied_guard_failures": ["clean_worktree_after_commit"],
            "required_next_action": "fix tests",
            "next_action_kind": "create_repair_node",
            "repair_brief": {
                "failed_items": ["failed_test_evidence"],
                "minimum_verifications": ["npm test"],
            },
            "feedback_items": [
                {
                    "target_layer": "planner",
                    "feedback_kind": "test_policy_conflict",
                    "severity": "blocking",
                    "recommended_action": "create_repair_node",
                    "failure_signature": "test-policy-conflict",
                }
            ],
            "confidence": 0.84,
        }
    )
    judge = WorkspaceVerifierAgentJudge(
        tenant_id="tenant-1",
        project_id="project-1",
        turn_runner=runner,
    )

    result = await judge.judge(
        WorkspaceVerificationJudgeRequest(
            workspace_id="ws-1",
            node_id="node-1",
            attempt_id="attempt-1",
            node_title="Run tests",
            node_description="Verify tests.",
            linked_workspace_task_id="task-1",
        )
    )

    assert runner.calls[0]["verifier_agent"].id == BUILTIN_WORKSPACE_VERIFIER_ID
    assert runner.calls[0]["linked_workspace_task_id"] == "task-1"
    assert "workspace_submit_verification_judgment" in runner.calls[0]["user_prompt"]
    assert result.verdict.value == "needs_rework"
    assert result.failed_criteria == ("failed_test_evidence",)
    assert result.satisfied_guard_failures == ("clean_worktree_after_commit",)
    assert result.next_action_kind.value == "create_repair_node"
    assert result.repair_brief == {
        "failed_items": ["failed_test_evidence"],
        "minimum_verifications": ["npm test"],
    }
    assert result.feedback_items[0].target_layer.value == "planner"
    assert result.feedback_items[0].failure_signature == "test-policy-conflict"


async def test_runtime_workspace_verifier_persists_linked_workspace_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persist_calls: list[dict[str, Any]] = []

    async def fake_ensure_workspace_llm_conversation(**kwargs: Any) -> bool:
        persist_calls.append(kwargs)
        return True

    class FakeProjectReActAgent:
        def __init__(self, config: Any) -> None:
            self.config = config

        async def initialize(self) -> bool:
            return True

        async def execute_chat(self, **kwargs: Any) -> Any:
            _ = kwargs
            yield {
                "type": "observe",
                "data": {
                    "tool_name": "workspace_submit_verification_judgment",
                    "observation": {
                        "verification_judgment": {
                            "verdict": "accepted",
                            "rationale": "Evidence passes.",
                        }
                    },
                },
            }

        async def stop(self) -> None:
            return None

    from src.infrastructure.agent.core import project_react_agent
    from src.infrastructure.agent.workspace import session_conversations

    monkeypatch.setattr(
        session_conversations,
        "ensure_workspace_llm_conversation",
        fake_ensure_workspace_llm_conversation,
    )
    monkeypatch.setattr(project_react_agent, "ProjectReActAgent", FakeProjectReActAgent)

    runner = RuntimeWorkspaceVerifierAgentTurnRunner(tenant_id="tenant-1", project_id="project-1")

    result = await runner.run_verification_turn(
        verifier_agent=SimpleNamespace(id=BUILTIN_WORKSPACE_VERIFIER_ID),
        user_prompt="judge",
        workspace_id="ws-1",
        node_id="node-1",
        attempt_id="attempt-1",
        linked_workspace_task_id="task-1",
    )

    assert result == {"verdict": "accepted", "rationale": "Evidence passes."}
    assert persist_calls[0]["linked_workspace_task_id"] == "task-1"
    assert persist_calls[0]["metadata"]["linked_workspace_task_id"] == "task-1"


async def test_iteration_review_agent_provider_uses_builtin_agent_turn_runner() -> None:
    runner = _ReviewRunner(
        {
            "verdict": "continue_next_iteration",
            "confidence": 0.91,
            "summary": "One proof sprint remains.",
            "next_sprint_goal": "Collect browser proof.",
            "feedback_items": ["Browser proof missing."],
            "next_tasks": [
                {
                    "id": "browser-proof",
                    "description": "Run browser parity verification.",
                    "phase": "test",
                }
            ],
        }
    )
    provider = WorkspaceIterationReviewAgentProvider(
        tenant_id="tenant-1",
        project_id="project-1",
        linked_workspace_task_id="root-task-1",
        max_next_tasks=6,
        turn_runner=runner,
    )

    result = await provider.review(
        IterationReviewContext(
            workspace_id="ws-1",
            plan_id="plan-1",
            iteration_index=7,
            goal_title="Goal",
            goal_description="Goal description.",
            max_next_tasks=6,
        )
    )

    assert runner.calls[0]["reviewer_agent"].id == BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID
    assert runner.calls[0]["linked_workspace_task_id"] == "root-task-1"
    assert "workspace_submit_iteration_review" in runner.calls[0]["user_prompt"]
    assert result.verdict == "continue_next_iteration"
    assert result.next_tasks[0].id == "browser-proof"


async def test_runtime_iteration_reviewer_persists_linked_workspace_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persist_calls: list[dict[str, Any]] = []

    async def fake_ensure_workspace_llm_conversation(**kwargs: Any) -> bool:
        persist_calls.append(kwargs)
        return True

    class FakeProjectReActAgent:
        def __init__(self, config: Any) -> None:
            self.config = config

        async def initialize(self) -> bool:
            return True

        async def execute_chat(self, **kwargs: Any) -> Any:
            _ = kwargs
            yield {
                "type": "tool_result",
                "data": {
                    "tool_name": "workspace_submit_iteration_review",
                    "result": {
                        "iteration_review": {
                            "verdict": "complete_goal",
                            "confidence": 0.9,
                            "summary": "Done.",
                        }
                    },
                },
            }

        async def stop(self) -> None:
            return None

    from src.infrastructure.agent.core import project_react_agent
    from src.infrastructure.agent.workspace import session_conversations

    monkeypatch.setattr(
        session_conversations,
        "ensure_workspace_llm_conversation",
        fake_ensure_workspace_llm_conversation,
    )
    monkeypatch.setattr(project_react_agent, "ProjectReActAgent", FakeProjectReActAgent)

    runner = RuntimeWorkspaceIterationReviewAgentTurnRunner(
        tenant_id="tenant-1",
        project_id="project-1",
    )

    result = await runner.run_review_turn(
        reviewer_agent=SimpleNamespace(id=BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID),
        user_prompt="review",
        workspace_id="ws-1",
        plan_id="plan-1",
        iteration_index=3,
        linked_workspace_task_id="root-task-1",
    )

    assert result == {"verdict": "complete_goal", "confidence": 0.9, "summary": "Done."}
    assert persist_calls[0]["linked_workspace_task_id"] == "root-task-1"
    assert persist_calls[0]["metadata"]["linked_workspace_task_id"] == "root-task-1"


def test_iteration_review_event_parser_accepts_tool_result_metadata() -> None:
    payload = {
        "verdict": "complete_goal",
        "confidence": 0.9,
        "summary": "Done.",
    }

    assert _iteration_review_from_event(
        {
            "type": "tool_result",
            "data": {
                "tool_name": "workspace_submit_iteration_review",
                "result": {"iteration_review": payload},
            },
        }
    ) == payload


def test_iteration_review_event_parser_accepts_json_observation() -> None:
    payload = {
        "verdict": "continue_next_iteration",
        "confidence": 0.82,
        "summary": "Need one proof sprint.",
    }

    assert _iteration_review_from_event(
        {
            "type": "observe",
            "data": {
                "tool_name": "workspace_submit_iteration_review",
                "observation": "{\"iteration_review\":{\"verdict\":\"continue_next_iteration\","
                "\"confidence\":0.82,\"summary\":\"Need one proof sprint.\"}}",
            },
        }
    ) == payload
