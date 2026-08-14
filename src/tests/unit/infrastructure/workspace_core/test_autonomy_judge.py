"""Structured Workspace Autonomy Agent judgment contracts."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.domain.llm_providers.models import ProviderConfig
from src.infrastructure.workspace_core.autonomy_judge import (
    AgentWorkspaceAutonomyJudge,
    WorkspaceAutonomyAgentCandidate,
    WorkspaceAutonomyCandidate,
    WorkspaceAutonomyJudgeRequest,
    WorkspaceAutonomyJudgeUnavailable,
)


class FakePool:
    def __init__(self, candidates: list[object]) -> None:
        self.candidates = candidates
        self.tenant_ids: list[str | None] = []

    async def list_candidates(self, tenant_id: str | None, pool_filter: object) -> list[object]:
        assert pool_filter is not None
        self.tenant_ids.append(tenant_id)
        return self.candidates


class FakeClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


def _request() -> WorkspaceAutonomyJudgeRequest:
    return WorkspaceAutonomyJudgeRequest(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        actor_id="user-1",
        workspace_revision=7,
        force=False,
        candidates=[
            WorkspaceAutonomyCandidate(
                root_task_id="task-1",
                title="First task",
                description=None,
                status="pending",
                metadata={"priority": 1},
            ),
            WorkspaceAutonomyCandidate(
                root_task_id="task-2",
                title="Second task",
                description="Ready for execution",
                status="pending",
                metadata={"priority": 2},
            ),
        ],
        agent_candidates=[
            WorkspaceAutonomyAgentCandidate(
                workspace_agent_binding_id="binding-1",
                agent_id="agent-1",
                display_name="Delivery Agent",
                description="Executes verified work",
                status="idle",
                config={},
            )
        ],
    )


def _candidate() -> object:
    return SimpleNamespace(
        candidate_key="provider-judge:model-1",
        provider_config=cast("ProviderConfig", object()),
        model_name="model-1",
    )


@pytest.mark.unit
async def test_autonomy_judge_requires_one_tenant_scoped_structured_tool_call() -> None:
    pool = FakePool([_candidate()])
    client = FakeClient(
        {
            "tool_calls": [
                {
                    "function": {
                        "name": "judge_workspace_autonomy",
                        "arguments": {
                            "verdict": "continue",
                            "selected_root_task_id": "task-2",
                            "next_action": {
                                "title": "Implement the next verified slice",
                                "description": "Advance the selected root goal",
                                "workspace_agent_binding_id": "binding-1",
                            },
                            "rationale": "The supplied evidence supports task-2.",
                        },
                    }
                }
            ]
        }
    )
    judge = AgentWorkspaceAutonomyJudge(
        pool_service=cast("Any", pool),
        client_factory=lambda _config: client,
    )

    verdict = await judge.judge(_request())

    assert pool.tenant_ids == ["tenant-1"]
    assert verdict.verdict == "continue"
    assert verdict.selected_root_task_id == "task-2"
    assert verdict.next_action is not None
    assert verdict.next_action.workspace_agent_binding_id == "binding-1"
    assert verdict.tool_name == "judge_workspace_autonomy"
    assert verdict.input_json["workspace_revision"] == 7
    assert len(client.calls) == 1
    assert client.calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "judge_workspace_autonomy"},
    }
    assert client.calls[0]["temperature"] == 0.0


@pytest.mark.unit
async def test_autonomy_judge_fails_closed_for_out_of_candidate_selection() -> None:
    client = FakeClient(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "judge_workspace_autonomy",
                                    "arguments": (
                                        '{"verdict":"continue",'
                                        '"selected_root_task_id":"outside",'
                                        '"rationale":"invalid"}'
                                    ),
                                }
                            }
                        ]
                    }
                }
            ]
        }
    )
    judge = AgentWorkspaceAutonomyJudge(
        pool_service=cast("Any", FakePool([_candidate()])),
        client_factory=lambda _config: client,
    )

    with pytest.raises(WorkspaceAutonomyJudgeUnavailable):
        await judge.judge(_request())


@pytest.mark.unit
@pytest.mark.parametrize(
    "next_action",
    [
        {
            "title": "Next",
            "description": "Continue",
            "workspace_agent_binding_id": "binding-1",
            "unexpected": True,
        },
        {
            "title": "Next",
            "description": "x" * 10_001,
            "workspace_agent_binding_id": "binding-1",
        },
    ],
)
async def test_autonomy_judge_rejects_invalid_nested_next_action(
    next_action: dict[str, Any],
) -> None:
    client = FakeClient(
        {
            "tool_calls": [
                {
                    "function": {
                        "name": "judge_workspace_autonomy",
                        "arguments": {
                            "verdict": "continue",
                            "selected_root_task_id": "task-1",
                            "next_action": next_action,
                            "rationale": "Continue",
                        },
                    }
                }
            ]
        }
    )
    judge = AgentWorkspaceAutonomyJudge(
        pool_service=cast("Any", FakePool([_candidate()])),
        client_factory=lambda _config: client,
    )

    with pytest.raises(WorkspaceAutonomyJudgeUnavailable):
        await judge.judge(_request())


@pytest.mark.unit
@pytest.mark.parametrize(
    ("verdict", "next_action", "rationale"),
    [
        ("continue", None, "Continue"),
        (
            "block",
            {
                "title": "Unexpected",
                "description": "Terminal verdicts cannot dispatch work",
                "workspace_agent_binding_id": "binding-1",
            },
            "Block",
        ),
        (
            "continue",
            {
                "title": "Outside",
                "description": "Do not dispatch outside the supplied roster",
                "workspace_agent_binding_id": "binding-outside",
            },
            "Continue",
        ),
        ("escalate", None, "   "),
    ],
)
async def test_autonomy_judge_rejects_inconsistent_structured_verdict(
    verdict: str,
    next_action: dict[str, Any] | None,
    rationale: str,
) -> None:
    client = FakeClient(
        {
            "tool_calls": [
                {
                    "function": {
                        "name": "judge_workspace_autonomy",
                        "arguments": {
                            "verdict": verdict,
                            "selected_root_task_id": "task-1",
                            "next_action": next_action,
                            "rationale": rationale,
                        },
                    }
                }
            ]
        }
    )
    judge = AgentWorkspaceAutonomyJudge(
        pool_service=cast("Any", FakePool([_candidate()])),
        client_factory=lambda _config: client,
    )

    with pytest.raises(WorkspaceAutonomyJudgeUnavailable):
        await judge.judge(_request())


@pytest.mark.unit
async def test_autonomy_judge_fails_closed_without_tool_capable_agent() -> None:
    judge = AgentWorkspaceAutonomyJudge(pool_service=cast("Any", FakePool([])))

    with pytest.raises(WorkspaceAutonomyJudgeUnavailable):
        await judge.judge(_request())
