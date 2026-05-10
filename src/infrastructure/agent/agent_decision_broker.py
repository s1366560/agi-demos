"""Agent-backed structured decision broker runtime."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol

from src.domain.ports.services.agent_decision_broker_port import (
    AgentDecisionBrokerPort,
    AgentDecisionRequest,
    AgentDecisionResult,
)
from src.infrastructure.agent.sisyphus.builtin_agent import (
    build_builtin_agent_decision_broker_agent,
)
from src.infrastructure.agent.tools.workspace_plan_contract_tools import (
    WORKSPACE_SUBMIT_AGENT_DECISION_TOOL_NAME,
)

if TYPE_CHECKING:
    from src.domain.model.agent.agent_definition import Agent

logger = logging.getLogger(__name__)


class AgentDecisionBrokerTurnRunner(Protocol):
    """Runs one builtin broker turn and returns the captured decision."""

    async def run_decision_turn(
        self,
        *,
        broker_agent: Agent,
        user_prompt: str,
        context_id: str,
    ) -> dict[str, Any] | None: ...


class RuntimeAgentDecisionBrokerTurnRunner:
    """Run the builtin decision broker through the project ReAct runtime."""

    def __init__(
        self,
        *,
        tenant_id: str,
        project_id: str,
        max_steps: int = 4,
        max_tokens: int = 8192,
    ) -> None:
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._max_steps = max_steps
        self._max_tokens = max_tokens
        self._last_diagnostics: dict[str, Any] = {}

    @property
    def last_diagnostics(self) -> dict[str, Any]:
        return dict(self._last_diagnostics)

    async def run_decision_turn(
        self,
        *,
        broker_agent: Agent,
        user_prompt: str,
        context_id: str,
    ) -> dict[str, Any] | None:
        from src.infrastructure.agent.core.project_react_agent import (
            ProjectAgentConfig,
            ProjectReActAgent,
        )
        from src.infrastructure.agent.workspace.runtime_role_contract import (
            WORKSPACE_ROLE_WORKER,
            WORKSPACE_SESSION_ROLE_KEY,
        )

        turn_id = uuid.uuid4().hex
        conversation_id = f"agent-decision-broker:{context_id}:{turn_id}"
        diagnostics: dict[str, Any] = {
            "conversation_id": conversation_id,
            "event_count": 0,
            "observed_tools": [],
            "decision_submitted": False,
        }
        agent = ProjectReActAgent(
            ProjectAgentConfig(
                tenant_id=self._tenant_id,
                project_id=self._project_id,
                agent_mode="agent-decision-broker",
                temperature=0.0,
                max_tokens=self._max_tokens,
                max_steps=self._max_steps,
                persistent=False,
                enable_subagents=False,
            )
        )
        if not await agent.initialize():
            self._last_diagnostics = diagnostics
            return None

        conversation_context = [
            {
                "role": "system",
                "content": "agent_decision_broker_runtime\n"
                + json.dumps(
                    {
                        "context_type": "agent_decision_broker_runtime",
                        WORKSPACE_SESSION_ROLE_KEY: WORKSPACE_ROLE_WORKER,
                        "selected_agent_id": broker_agent.id,
                    },
                    ensure_ascii=False,
                ),
            }
        ]
        try:
            async for event in agent.execute_chat(
                conversation_id=conversation_id,
                user_message=user_prompt,
                user_id="agent-decision-broker",
                tenant_id=self._tenant_id,
                message_id=f"agent-decision-broker-{turn_id}",
                conversation_context=conversation_context,
                agent_id=broker_agent.id,
            ):
                diagnostics["event_count"] += 1
                tool_name = _tool_name_from_event(event)
                if tool_name:
                    observed_tools = diagnostics["observed_tools"]
                    if tool_name not in observed_tools:
                        observed_tools.append(tool_name)
                payload = _agent_decision_from_event(event)
                if payload is not None:
                    diagnostics["decision_submitted"] = True
                    self._last_diagnostics = diagnostics
                    return payload
        finally:
            await agent.stop()
        self._last_diagnostics = diagnostics
        return None


class RuntimeAgentDecisionBroker(AgentDecisionBrokerPort):
    """Agent-First broker backed by the builtin decision-broker agent."""

    def __init__(
        self,
        *,
        tenant_id: str,
        project_id: str,
        turn_runner: AgentDecisionBrokerTurnRunner | None = None,
    ) -> None:
        self._broker_agent = build_builtin_agent_decision_broker_agent(
            tenant_id=tenant_id,
            project_id=project_id,
        )
        self._turn_runner = turn_runner or RuntimeAgentDecisionBrokerTurnRunner(
            tenant_id=tenant_id,
            project_id=project_id,
        )

    async def decide(self, request: AgentDecisionRequest) -> AgentDecisionResult:
        started = time.perf_counter()
        logger.info(
            "agent_decision_requested kind=%s context_id=%s candidates=%d verdicts=%s",
            request.decision_kind.value,
            request.context_id,
            len(request.candidates),
            list(request.allowed_verdicts),
        )
        try:
            payload = await self._turn_runner.run_decision_turn(
                broker_agent=self._broker_agent,
                user_prompt=_build_agent_user_prompt(request),
                context_id=request.context_id,
            )
            parsed = _parse_decision_payload(payload or {}, request)
            if parsed is None:
                diagnostics = getattr(self._turn_runner, "last_diagnostics", {})
                raise ValueError(
                    "builtin agent decision broker did not submit decision: "
                    f"{json.dumps(diagnostics, ensure_ascii=False, default=str)}"
                )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "agent_decision_completed kind=%s context_id=%s verdict=%s confidence=%.2f latency_ms=%d tool=%s",
                request.decision_kind.value,
                request.context_id,
                parsed.verdict,
                parsed.confidence,
                elapsed_ms,
                WORKSPACE_SUBMIT_AGENT_DECISION_TOOL_NAME,
            )
            return parsed
        except Exception:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.exception(
                "agent_decision_failed kind=%s context_id=%s latency_ms=%d",
                request.decision_kind.value,
                request.context_id,
                elapsed_ms,
            )
            raise


def _build_agent_user_prompt(request: AgentDecisionRequest) -> str:
    return (
        "Decide this semantic gate using only the structured AgentDecisionRequest.\n\n"
        f"{_request_payload(request)}\n\n"
        "Do not emit prose. Your final action must be exactly one "
        f"{WORKSPACE_SUBMIT_AGENT_DECISION_TOOL_NAME} call."
    )


def _request_payload(request: AgentDecisionRequest) -> str:
    payload = {
        "decision_kind": request.decision_kind.value,
        "context_id": request.context_id,
        "facts": request.facts,
        "candidates": [
            {"id": candidate.id, "label": candidate.label, "facts": candidate.facts}
            for candidate in request.candidates
        ],
        "allowed_verdicts": list(request.allowed_verdicts),
        "constraints": request.constraints,
        "contract": {
            "selected_ids": "May only contain ids from candidates.",
            "verdict": "Must be one value from allowed_verdicts.",
            "next_action_kind": "Use only a structured action kind supplied by the gate contract.",
            "repair_brief": "Use only for repair-like decisions with fresh evidence requirements.",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _agent_decision_from_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    if event.get("type") != "observe":
        return None
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    if data.get("tool_name") != WORKSPACE_SUBMIT_AGENT_DECISION_TOOL_NAME:
        return None
    observation = data.get("observation") or data.get("result")
    if not isinstance(observation, Mapping):
        return None
    payload = observation.get("agent_decision")
    return dict(payload) if isinstance(payload, Mapping) else None


def _tool_name_from_event(event: Mapping[str, Any]) -> str | None:
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    tool_name = data.get("tool_name") or data.get("name")
    return tool_name.strip() if isinstance(tool_name, str) and tool_name.strip() else None


def _parse_decision_payload(
    payload: Mapping[str, Any],
    request: AgentDecisionRequest,
) -> AgentDecisionResult | None:
    if payload.get("decision_kind") != request.decision_kind.value:
        return None
    verdict = str(payload.get("verdict") or "").strip()
    if not verdict or (request.allowed_verdicts and verdict not in request.allowed_verdicts):
        return None
    candidate_ids = {candidate.id for candidate in request.candidates}
    selected_ids = tuple(
        item
        for item in _string_tuple(payload.get("selected_ids"), limit=32)
        if not candidate_ids or item in candidate_ids
    )
    return AgentDecisionResult(
        verdict=verdict,
        rationale=str(payload.get("rationale") or "").strip() or verdict,
        confidence=_float_between(payload.get("confidence"), default=0.0),
        selected_ids=selected_ids,
        next_action_kind=str(payload.get("next_action_kind") or "").strip(),
        repair_brief=_mapping(payload.get("repair_brief")),
        payload=_mapping(payload.get("payload")),
    )


def _string_tuple(value: object, *, limit: int) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list | tuple):
        items = [str(item) for item in value]
    else:
        return ()
    cleaned = [item.strip() for item in items if item.strip()]
    return tuple(dict.fromkeys(cleaned))[:limit]


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _float_between(value: object, *, default: float) -> float:
    if not isinstance(value, int | float | str):
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(0.0, min(parsed, 1.0))


__all__ = [
    "AgentDecisionBrokerTurnRunner",
    "RuntimeAgentDecisionBroker",
    "RuntimeAgentDecisionBrokerTurnRunner",
]
