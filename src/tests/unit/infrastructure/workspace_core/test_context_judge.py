"""Structured Agent judgment contracts for Workspace Context selection."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.domain.llm_providers.llm_types import Message
from src.domain.llm_providers.models import ProviderConfig
from src.infrastructure.llm.model_pool import PoolFilter
from src.infrastructure.workspace_core.context_judge import (
    AgentWorkspaceContextJudge,
    WorkspaceContextCandidate,
    WorkspaceContextJudgeRequest,
    WorkspaceContextJudgeUnavailable,
)


class _FakePool:
    def __init__(self) -> None:
        self.tenant_ids: list[str | None] = []

    async def list_candidates(
        self,
        tenant_id: str | None,
        pool_filter: PoolFilter | None,
    ) -> list[object]:
        self.tenant_ids.append(tenant_id)
        assert pool_filter is not None
        assert pool_filter.require_tools is True
        return [
            SimpleNamespace(
                candidate_key="provider-judge:model-judge",
                provider_config=cast(ProviderConfig, object()),
                model_name="model-judge",
            )
        ]


class _FakeClient:
    def __init__(self, candidate_index: int) -> None:
        self.candidate_index = candidate_index
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any],
        temperature: float,
        max_tokens: int,
        model: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "model": model,
            }
        )
        return {
            "tool_calls": [
                {
                    "function": {
                        "name": "select_workspace_context",
                        "arguments": json.dumps(
                            {
                                "candidate_index": self.candidate_index,
                                "rationale": "The second candidate best preserves the work scope.",
                                "evidence": ["candidate index 1 is explicitly available"],
                            }
                        ),
                    }
                }
            ]
        }


def _request() -> WorkspaceContextJudgeRequest:
    return WorkspaceContextJudgeRequest(
        user_id="user-1",
        current=None,
        candidates=[
            WorkspaceContextCandidate(
                tenant_id="tenant-1",
                project_id="project-1",
                membership_role="member",
            ),
            WorkspaceContextCandidate(
                tenant_id="tenant-2",
                project_id="project-2",
                membership_role="owner",
            ),
        ],
    )


@pytest.mark.unit
async def test_context_judge_requires_structured_tool_call_and_maps_candidate_index() -> None:
    pool = _FakePool()
    client = _FakeClient(candidate_index=1)
    judge = AgentWorkspaceContextJudge(
        pool_service=pool,
        client_factory=lambda _provider: client,
    )

    verdict = await judge.select(_request())

    assert pool.tenant_ids == [None]
    assert verdict.selected.tenant_id == "tenant-2"
    assert verdict.selected.project_id == "project-2"
    assert verdict.agent_id == "provider-judge:model-judge"
    assert verdict.tool_name == "select_workspace_context"
    assert verdict.output_json["candidate_index"] == 1
    assert verdict.rationale.startswith("The second candidate")
    assert verdict.latency_ms >= 0
    assert client.calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "select_workspace_context"},
    }


@pytest.mark.unit
async def test_context_judge_rejects_candidate_index_outside_the_supplied_set() -> None:
    judge = AgentWorkspaceContextJudge(
        pool_service=_FakePool(),
        client_factory=lambda _provider: _FakeClient(candidate_index=7),
    )

    with pytest.raises(WorkspaceContextJudgeUnavailable, match="candidate index"):
        await judge.select(_request())
