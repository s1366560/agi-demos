"""Structured Workspace Plan Agent judgment contracts."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.domain.llm_providers.models import ProviderConfig
from src.infrastructure.workspace_core.plan_judge import (
    AgentWorkspacePlanJudge,
    WorkspacePlanJudgeRequest,
    WorkspacePlanJudgeUnavailable,
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


def _request() -> WorkspacePlanJudgeRequest:
    return WorkspacePlanJudgeRequest(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        actor_id="user-1",
        plan_id="plan-1",
        plan_revision=4,
        kind="select_pipeline_target",
        candidate_node_ids=["node-1", "node-2"],
        evidence={"nodes": [{"id": "node-1"}, {"id": "node-2"}]},
    )


def _candidate() -> object:
    return SimpleNamespace(
        candidate_key="provider-judge:model-1",
        provider_config=cast("ProviderConfig", object()),
        model_name="model-1",
    )


@pytest.mark.unit
async def test_plan_judge_requires_one_tenant_scoped_structured_tool_call() -> None:
    pool = FakePool([_candidate()])
    client = FakeClient(
        {
            "tool_calls": [
                {
                    "function": {
                        "name": "judge_workspace_plan",
                        "arguments": {
                            "proceed": True,
                            "selected_node_id": "node-2",
                            "rationale": "The supplied node evidence supports node-2.",
                        },
                    }
                }
            ]
        }
    )
    judge = AgentWorkspacePlanJudge(
        pool_service=cast("Any", pool),
        client_factory=lambda _config: client,
    )

    verdict = await judge.judge(_request())

    assert pool.tenant_ids == ["tenant-1"]
    assert verdict.proceed is True
    assert verdict.selected_node_id == "node-2"
    assert verdict.tool_name == "judge_workspace_plan"
    assert verdict.input_json["plan_revision"] == 4
    assert verdict.output_json["selected_node_id"] == "node-2"
    assert len(client.calls) == 1
    assert client.calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "judge_workspace_plan"},
    }
    assert client.calls[0]["temperature"] == 0.0


@pytest.mark.unit
async def test_plan_judge_fails_closed_for_out_of_candidate_selection() -> None:
    client = FakeClient(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "judge_workspace_plan",
                                    "arguments": (
                                        '{"proceed":true,"selected_node_id":"outside",'
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
    judge = AgentWorkspacePlanJudge(
        pool_service=cast("Any", FakePool([_candidate()])),
        client_factory=lambda _config: client,
    )

    with pytest.raises(WorkspacePlanJudgeUnavailable):
        await judge.judge(_request())


@pytest.mark.unit
async def test_plan_judge_fails_closed_without_tool_capable_agent() -> None:
    judge = AgentWorkspacePlanJudge(pool_service=cast("Any", FakePool([])))

    with pytest.raises(WorkspacePlanJudgeUnavailable):
        await judge.judge(_request())
