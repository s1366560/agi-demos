"""LLM-backed Agent-First decisions for durable workspace supervisor ticks."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, Protocol

from src.domain.ports.services.workspace_supervisor_decision_port import (
    WorkspaceSupervisorDecisionAction,
    WorkspaceSupervisorDecisionRequest,
    WorkspaceSupervisorDecisionResult,
)
from src.infrastructure.agent.sisyphus.builtin_agent import (
    build_builtin_workspace_supervisor_agent,
)
from src.infrastructure.agent.tools.workspace_plan_contract_tools import (
    WORKSPACE_SUBMIT_SUPERVISOR_DECISION_TOOL_NAME,
)
from src.infrastructure.agent.workspace.contract_agent_runtime import (
    contract_tool_payload_from_event,
    workspace_contract_input_fingerprint,
)

if TYPE_CHECKING:
    from src.domain.model.agent.agent_definition import Agent

logger = logging.getLogger(__name__)

_VALID_ACTIONS = {item.value for item in WorkspaceSupervisorDecisionAction}
_MISSING_CONTRACT_RETRY_ATTEMPTS = 1
_DEFAULT_SUPERVISOR_DECISION_TURN_TIMEOUT_SECONDS = 300
_MAX_SUPERVISOR_DECISION_TURN_TIMEOUT_SECONDS = 1800


class WorkspaceSupervisorAgentTurnRunner(Protocol):
    """Runs one builtin workspace-supervisor turn."""

    async def run_decision_turn(
        self,
        *,
        supervisor_agent: Agent,
        user_prompt: str,
        workspace_id: str,
        plan_id: str,
        node_id: str,
        attempt_id: str | None,
        linked_workspace_task_id: str | None = None,
    ) -> dict[str, Any] | None: ...


class _WorkspaceContractAgentService(Protocol):
    def stream_chat_v2(  # noqa: PLR0913
        self,
        conversation_id: str,
        user_message: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
        preferred_language: str | None = None,
        attachment_ids: list[str] | None = None,
        file_metadata: list[dict[str, Any]] | None = None,
        forced_skill_name: str | None = None,
        app_model_context: dict[str, Any] | None = None,
        image_attachments: list[str] | None = None,
        agent_id: str | None = None,
        mentions: list[str] | None = None,
        api_auth_token: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]: ...


class RuntimeWorkspaceSupervisorAgentTurnRunner:
    """Run the builtin supervisor through the normal project ReAct runtime."""

    def __init__(
        self,
        *,
        tenant_id: str,
        project_id: str,
        max_steps: int = 8,
        max_tokens: int = 8192,
        turn_timeout_seconds: float | None = None,
    ) -> None:
        super().__init__()
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._max_steps = max_steps
        self._max_tokens = max_tokens
        self._turn_timeout_seconds = (
            turn_timeout_seconds
            if turn_timeout_seconds is not None
            else _supervisor_decision_turn_timeout_seconds()
        )
        self._last_diagnostics: dict[str, Any] = {}

    @property
    def last_diagnostics(self) -> dict[str, Any]:
        return dict(self._last_diagnostics)

    async def run_decision_turn(
        self,
        *,
        supervisor_agent: Agent,
        user_prompt: str,
        workspace_id: str,
        plan_id: str,
        node_id: str,
        attempt_id: str | None,
        linked_workspace_task_id: str | None = None,
    ) -> dict[str, Any] | None:
        from src.configuration.factories import create_llm_client
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.agent.workspace.contract_agent_runtime import (
            cancel_workspace_contract_chat,
            create_workspace_contract_agent_service,
            recover_workspace_contract_payload,
            resolve_workspace_actor_user_id,
            workspace_contract_conversation_id,
        )
        from src.infrastructure.agent.workspace.runtime_role_contract import (
            WORKSPACE_ROLE_CONTRACT,
            WORKSPACE_SESSION_ROLE_KEY,
        )
        from src.infrastructure.agent.workspace.session_conversations import (
            ensure_workspace_llm_conversation,
        )

        input_fingerprint = workspace_contract_input_fingerprint(
            user_prompt,
            workspace_id,
            plan_id,
            node_id,
            attempt_id or "",
            linked_workspace_task_id or "",
            supervisor_agent.id,
        )
        conversation_id = workspace_contract_conversation_id(
            "supervisor-decision",
            self._tenant_id,
            self._project_id,
            workspace_id,
            plan_id,
            node_id,
            attempt_id or "none",
            linked_workspace_task_id or "",
            input_fingerprint,
        )
        diagnostics: dict[str, Any] = {
            "conversation_id": conversation_id,
            "input_fingerprint": input_fingerprint,
            "event_count": 0,
            "observed_tools": [],
            "decision_submitted": False,
            "runtime_path": "agent_service.stream_chat_v2",
            "turn_timeout_seconds": self._turn_timeout_seconds,
        }
        recovered_payload = await recover_workspace_contract_payload(
            conversation_id=conversation_id,
            extract_payload=_supervisor_decision_from_event,
        )
        if recovered_payload is not None:
            diagnostics["recovered_from_events"] = True
            diagnostics["decision_submitted"] = True
            self._last_diagnostics = diagnostics
            return recovered_payload

        resolved_actor_user_id = await resolve_workspace_actor_user_id(workspace_id=workspace_id)
        diagnostics["actor_user_resolved"] = bool(resolved_actor_user_id)
        if not resolved_actor_user_id:
            self._last_diagnostics = diagnostics
            return None

        diagnostics["session_persisted"] = await ensure_workspace_llm_conversation(
            conversation_id=conversation_id,
            tenant_id=self._tenant_id,
            project_id=self._project_id,
            workspace_id=workspace_id,
            linked_workspace_task_id=linked_workspace_task_id,
            agent_id=supervisor_agent.id,
            actor_user_id=resolved_actor_user_id,
            title=f"Workspace Supervisor Decision - {node_id}",
            stage="supervisor_decision",
            metadata={
                "plan_id": plan_id,
                "current_plan_node_id": node_id,
                "current_attempt_id": attempt_id or "",
                "linked_workspace_task_id": linked_workspace_task_id or "",
                "conversation_scope": f"supervisor:{plan_id}:{node_id}:{attempt_id or 'none'}",
            },
        )
        if not diagnostics["session_persisted"]:
            self._last_diagnostics = diagnostics
            return None

        app_model_context = {
            "context_type": "workspace_worker_runtime",
            WORKSPACE_SESSION_ROLE_KEY: WORKSPACE_ROLE_CONTRACT,
            "workspace_binding": {
                "workspace_id": workspace_id,
                "linked_workspace_task_id": linked_workspace_task_id or "",
                "plan_id": plan_id,
                "current_plan_node_id": node_id,
                "current_attempt_id": attempt_id or "",
            },
            "supervisor_decision": {
                "plan_id": plan_id,
                "node_id": node_id,
                "attempt_id": attempt_id or "",
            },
            "runtime_limits": {
                "max_tokens": self._max_tokens,
            },
            "llm_overrides": {"max_tokens": self._max_tokens},
        }
        async with async_session_factory() as db:
            llm = await create_llm_client(self._tenant_id)
            agent_service = await create_workspace_contract_agent_service(db=db, llm=llm)
            payload = await self._stream_decision_payload(
                agent_service=agent_service,
                cancel_workspace_contract_chat=cancel_workspace_contract_chat,
                conversation_id=conversation_id,
                user_prompt=user_prompt,
                resolved_actor_user_id=resolved_actor_user_id,
                supervisor_agent_id=supervisor_agent.id,
                workspace_id=workspace_id,
                plan_id=plan_id,
                node_id=node_id,
                app_model_context=app_model_context,
                diagnostics=diagnostics,
            )
            if payload is not None:
                return payload
        recovered_payload = await recover_workspace_contract_payload(
            conversation_id=conversation_id,
            extract_payload=_supervisor_decision_from_event,
        )
        if recovered_payload is not None:
            diagnostics["recovered_from_events"] = True
            diagnostics["decision_submitted"] = True
            self._last_diagnostics = diagnostics
            return recovered_payload
        self._last_diagnostics = diagnostics
        return None

    async def _stream_decision_payload(
        self,
        *,
        agent_service: _WorkspaceContractAgentService,
        cancel_workspace_contract_chat: Callable[[str], Awaitable[None]],
        conversation_id: str,
        user_prompt: str,
        resolved_actor_user_id: str,
        supervisor_agent_id: str,
        workspace_id: str,
        plan_id: str,
        node_id: str,
        app_model_context: Mapping[str, Any],
        diagnostics: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            async with asyncio.timeout(self._turn_timeout_seconds):
                async for event in agent_service.stream_chat_v2(
                    conversation_id=conversation_id,
                    user_message=user_prompt,
                    user_id=resolved_actor_user_id,
                    project_id=self._project_id,
                    tenant_id=self._tenant_id,
                    agent_id=supervisor_agent_id,
                    app_model_context=dict(app_model_context),
                ):
                    diagnostics["event_count"] += 1
                    tool_name = _tool_name_from_event(event)
                    if tool_name:
                        observed_tools = diagnostics["observed_tools"]
                        if tool_name not in observed_tools:
                            observed_tools.append(tool_name)
                    payload = _supervisor_decision_from_event(event)
                    if payload is not None:
                        diagnostics["decision_submitted"] = True
                        self._last_diagnostics = diagnostics
                        await cancel_workspace_contract_chat(conversation_id)
                        return payload
        except TimeoutError:
            diagnostics["timed_out"] = True
            self._last_diagnostics = diagnostics
            await cancel_workspace_contract_chat(conversation_id)
            logger.warning(
                "Workspace supervisor decision contract turn timed out",
                extra={
                    "conversation_id": conversation_id,
                    "workspace_id": workspace_id,
                    "plan_id": plan_id,
                    "node_id": node_id,
                    "timeout_seconds": self._turn_timeout_seconds,
                },
            )
        except asyncio.CancelledError:
            await cancel_workspace_contract_chat(conversation_id)
            raise
        return None


class WorkspaceSupervisorAgentDecisionProvider:
    """Supervisor decision provider backed by the builtin supervisor agent."""

    def __init__(
        self,
        *,
        tenant_id: str,
        project_id: str,
        linked_workspace_task_id: str | None = None,
        missing_contract_retry_attempts: int = _MISSING_CONTRACT_RETRY_ATTEMPTS,
        turn_runner: WorkspaceSupervisorAgentTurnRunner | None = None,
    ) -> None:
        super().__init__()
        self._linked_workspace_task_id = linked_workspace_task_id
        self._missing_contract_retry_attempts = max(0, missing_contract_retry_attempts)
        self._supervisor_agent = build_builtin_workspace_supervisor_agent(
            tenant_id=tenant_id,
            project_id=project_id,
        )
        self._turn_runner = turn_runner or RuntimeWorkspaceSupervisorAgentTurnRunner(
            tenant_id=tenant_id,
            project_id=project_id,
        )

    async def decide(
        self,
        request: WorkspaceSupervisorDecisionRequest,
    ) -> WorkspaceSupervisorDecisionResult:
        linked_workspace_task_id = (
            request.linked_workspace_task_id or self._linked_workspace_task_id
        )
        resolved_request = (
            request
            if linked_workspace_task_id == request.linked_workspace_task_id
            else WorkspaceSupervisorDecisionRequest(
                workspace_id=request.workspace_id,
                plan_id=request.plan_id,
                node_id=request.node_id,
                attempt_id=request.attempt_id,
                linked_workspace_task_id=linked_workspace_task_id,
                node_snapshot=request.node_snapshot,
                verification_report=request.verification_report,
                structural_signals=request.structural_signals,
                allowed_actions=request.allowed_actions,
                recent_metadata=request.recent_metadata,
            )
        )
        prompt = _build_agent_user_prompt(resolved_request)
        payload = await self._turn_runner.run_decision_turn(
            supervisor_agent=self._supervisor_agent,
            user_prompt=prompt,
            workspace_id=request.workspace_id,
            plan_id=request.plan_id,
            node_id=request.node_id,
            attempt_id=request.attempt_id,
            linked_workspace_task_id=linked_workspace_task_id,
        )
        parsed = _parse_decision_payload(payload or {})
        retry_index = 0
        while parsed is None and retry_index < self._missing_contract_retry_attempts:
            retry_index += 1
            prompt = _build_agent_contract_retry_prompt(
                resolved_request,
                diagnostics=getattr(self._turn_runner, "last_diagnostics", {}),
                retry_index=retry_index,
            )
            payload = await self._turn_runner.run_decision_turn(
                supervisor_agent=self._supervisor_agent,
                user_prompt=prompt,
                workspace_id=request.workspace_id,
                plan_id=request.plan_id,
                node_id=request.node_id,
                attempt_id=request.attempt_id,
                linked_workspace_task_id=linked_workspace_task_id,
            )
            parsed = _parse_decision_payload(payload or {})
        if parsed is None:
            diagnostics = getattr(self._turn_runner, "last_diagnostics", {})
            logger.warning(
                "workspace_plan.supervisor_decision_missing_contract",
                extra={
                    "workspace_id": request.workspace_id,
                    "plan_id": request.plan_id,
                    "node_id": request.node_id,
                    "diagnostics": diagnostics,
                },
            )
            return WorkspaceSupervisorDecisionResult(
                action=WorkspaceSupervisorDecisionAction.RETRY_SAME_NODE,
                rationale="workspace supervisor decision agent did not submit a decision",
                confidence=0.3,
                feedback_items=(
                    {
                        "target_layer": "runtime",
                        "recommended_action": "retry_infra",
                        "summary": "supervisor decision contract was not submitted",
                        "failure_signature": "workspace_supervisor_decision_missing_contract",
                    },
                ),
            )
        return parsed


class UnavailableWorkspaceSupervisorDecisionProvider:
    """Return a retryable runtime decision when the supervisor agent is unavailable."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def decide(
        self,
        request: WorkspaceSupervisorDecisionRequest,
    ) -> WorkspaceSupervisorDecisionResult:
        _ = request
        return WorkspaceSupervisorDecisionResult(
            action=WorkspaceSupervisorDecisionAction.RETRY_SAME_NODE,
            rationale=self._reason,
            confidence=0.3,
            feedback_items=(
                {
                    "target_layer": "runtime",
                    "recommended_action": "retry_infra",
                    "summary": self._reason,
                    "failure_signature": "workspace_supervisor_decision_unavailable",
                },
            ),
        )


def _build_agent_user_prompt(request: WorkspaceSupervisorDecisionRequest) -> str:
    return (
        "Choose the next durable workspace plan supervisor action using the builtin "
        "workspace supervisor contract.\n\n"
        f"{_request_payload(request)}\n\n"
        "You are in read-only supervisor decision mode. Do not implement, edit files, "
        "mutate workspace state, or finish in prose. Your final action must be exactly "
        f"one {WORKSPACE_SUBMIT_SUPERVISOR_DECISION_TOOL_NAME} call."
    )


def _build_agent_contract_retry_prompt(
    request: WorkspaceSupervisorDecisionRequest,
    *,
    diagnostics: Mapping[str, Any],
    retry_index: int,
) -> str:
    return (
        f"Contract retry {retry_index}: the previous supervisor turn did not call "
        f"{WORKSPACE_SUBMIT_SUPERVISOR_DECISION_TOOL_NAME}.\n\n"
        f"Diagnostics from the failed turn:\n{json.dumps(diagnostics, ensure_ascii=False, default=str)}\n\n"
        "Use the same supervisor payload below. You may make at most one or two "
        "read-only checks only if essential. Your next and final action must be exactly "
        f"one {WORKSPACE_SUBMIT_SUPERVISOR_DECISION_TOOL_NAME} call; do not finish in prose.\n\n"
        f"{_request_payload(request)}"
    )


def _request_payload(request: WorkspaceSupervisorDecisionRequest) -> str:
    payload = {
        "workspace_id": request.workspace_id,
        "plan_id": request.plan_id,
        "linked_workspace_task_id": request.linked_workspace_task_id,
        "node": request.node_snapshot,
        "attempt": {
            "id": request.attempt_id,
        },
        "verification_report": request.verification_report,
        "structural_signals": request.structural_signals,
        "allowed_actions": [item.value for item in request.allowed_actions],
        "recent_metadata": request.recent_metadata,
        "policy": {
            "actions": sorted(_VALID_ACTIONS),
            "human_blocking": (
                "Use mark_blocked_human only for human-only credentials, permissions, "
                "irreversible external deployment/spend, legal/compliance/product approval, "
                "or unsafe destructive action."
            ),
            "single_writer": (
                "The agent chooses an action only; WorkspaceSupervisor applies mutations."
            ),
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _supervisor_decision_from_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    return contract_tool_payload_from_event(
        event,
        tool_name=WORKSPACE_SUBMIT_SUPERVISOR_DECISION_TOOL_NAME,
        payload_key="supervisor_decision",
    )


def _tool_name_from_event(event: Mapping[str, Any]) -> str | None:
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    tool_name = data.get("tool_name") or data.get("name")
    return tool_name.strip() if isinstance(tool_name, str) and tool_name.strip() else None


def _parse_decision_payload(
    payload: Mapping[str, Any],
) -> WorkspaceSupervisorDecisionResult | None:
    raw_action = str(payload.get("action") or "").strip()
    if raw_action not in _VALID_ACTIONS:
        return None
    rationale = str(payload.get("rationale") or "").strip()
    if not rationale:
        return None
    return WorkspaceSupervisorDecisionResult(
        action=WorkspaceSupervisorDecisionAction(raw_action),
        rationale=rationale,
        confidence=_float_between(payload.get("confidence"), default=0.0),
        feedback_items=tuple(_dict_items(payload.get("feedback_items"))),
        retry_not_before_seconds=_optional_nonnegative_int(
            payload.get("retry_not_before_seconds")
        ),
        repair_brief=_dict_payload(payload.get("repair_brief")),
        event_payload=_dict_payload(payload.get("event_payload")),
    )


def _dict_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value[:8] if isinstance(item, Mapping)]


def _dict_payload(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _float_between(value: object, *, default: float) -> float:
    if not isinstance(value, int | float | str):
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(0.0, min(parsed, 1.0))


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None or not isinstance(value, int | float | str):
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return max(0, parsed)


def _supervisor_decision_turn_timeout_seconds() -> int:
    raw_value = os.getenv("WORKSPACE_SUPERVISOR_DECISION_TIMEOUT_SECONDS")
    if raw_value is None:
        return _DEFAULT_SUPERVISOR_DECISION_TURN_TIMEOUT_SECONDS
    try:
        parsed = int(raw_value)
    except ValueError:
        return _DEFAULT_SUPERVISOR_DECISION_TURN_TIMEOUT_SECONDS
    if parsed <= 0:
        return _DEFAULT_SUPERVISOR_DECISION_TURN_TIMEOUT_SECONDS
    return min(parsed, _MAX_SUPERVISOR_DECISION_TURN_TIMEOUT_SECONDS)


__all__ = [
    "RuntimeWorkspaceSupervisorAgentTurnRunner",
    "UnavailableWorkspaceSupervisorDecisionProvider",
    "WorkspaceSupervisorAgentDecisionProvider",
    "WorkspaceSupervisorAgentTurnRunner",
]
