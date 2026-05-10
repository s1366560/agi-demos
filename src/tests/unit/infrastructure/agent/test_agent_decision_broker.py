from __future__ import annotations

from typing import Any

import pytest

from src.domain.ports.services.agent_decision_broker_port import (
    AgentDecisionCandidate,
    AgentDecisionKind,
    AgentDecisionRequest,
)
from src.infrastructure.agent.agent_decision_broker import RuntimeAgentDecisionBroker


class FakeTurnRunner:
    def __init__(self, payload: dict[str, Any] | None) -> None:
        self.payload = payload
        self.last_diagnostics = {"decision_submitted": payload is not None}
        self.user_prompt = ""

    async def run_decision_turn(self, **kwargs: Any) -> dict[str, Any] | None:
        self.user_prompt = str(kwargs["user_prompt"])
        return self.payload


@pytest.mark.asyncio
async def test_runtime_agent_decision_broker_accepts_structured_tool_payload() -> None:
    runner = FakeTurnRunner(
        {
            "decision_kind": "execution_route",
            "verdict": "route_to_worker",
            "rationale": "The structured facts require execution.",
            "confidence": 0.82,
            "selected_ids": ["worker"],
            "next_action_kind": "dispatch",
            "payload": {"route": "worker"},
        }
    )
    broker = RuntimeAgentDecisionBroker(
        tenant_id="tenant",
        project_id="project",
        turn_runner=runner,
    )

    result = await broker.decide(
        AgentDecisionRequest(
            decision_kind=AgentDecisionKind.EXECUTION_ROUTE,
            context_id="ctx-1",
            facts={"message_id": "msg-1"},
            candidates=(AgentDecisionCandidate(id="worker", label="Worker"),),
            allowed_verdicts=("route_to_worker", "safe_default"),
            constraints={"no_keyword_fallback": True},
        )
    )

    assert result.verdict == "route_to_worker"
    assert result.selected_ids == ("worker",)
    assert result.next_action_kind == "dispatch"
    assert result.payload == {"route": "worker"}
    assert "execution_route" in runner.user_prompt
    assert "allowed_verdicts" in runner.user_prompt


@pytest.mark.asyncio
async def test_runtime_agent_decision_broker_rejects_wrong_kind_payload() -> None:
    broker = RuntimeAgentDecisionBroker(
        tenant_id="tenant",
        project_id="project",
        turn_runner=FakeTurnRunner(
            {
                "decision_kind": "tool_ranking",
                "verdict": "ranked",
                "rationale": "wrong gate",
                "confidence": 0.9,
            }
        ),
    )

    with pytest.raises(ValueError, match="did not submit decision"):
        await broker.decide(
            AgentDecisionRequest(
                decision_kind=AgentDecisionKind.EXECUTION_ROUTE,
                context_id="ctx-1",
                allowed_verdicts=("route_to_worker",),
            )
        )
