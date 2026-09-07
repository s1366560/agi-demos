"""Agent-first judgment and application seams for SubAgent selection."""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, cast, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.llm_providers.llm_types import LLMClient, Message as LLMMessage
from src.domain.model.agent.subagent import SubAgent
from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2

from .llm_client_service import TenantLlmClientFactoryProtocolV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .subagent_management_services import (
    SubAgentManagementResolverProtocolV2,
    SubAgentManagementServiceProtocolV2,
)

SUBAGENT_SELECTION_JUDGE_MODULE_V2 = "builtin://memstack/judgment/subagent-selection"
SUBAGENT_SELECTION_JUDGE_SERVICE_V2 = "service:judgment.subagent-selection"
SUBAGENT_SELECTION_APPLICATION_MODULE_V2 = "builtin://memstack/application/subagent-selection"
SUBAGENT_SELECTION_APPLICATION_SERVICE_V2 = "service:application.subagent-selection"
SUBAGENT_SELECTION_LLM_CLIENTS_INJECT_V2 = "llm_clients"
SUBAGENT_SELECTION_APPLICATION_JUDGE_INJECT_V2 = "judge"
SUBAGENT_SELECTION_APPLICATION_SUBAGENTS_INJECT_V2 = "subagents"
SUBAGENT_SELECTION_TOOL_V2 = "submit_subagent_selection_v2"

_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"
_OPERATION_IDENTITY_SERVICE_V2 = "service:operation.identity"
_MAX_TASK_CHARACTERS = 8000
_MAX_CANDIDATES = 100
_MAX_MODEL_INPUT_CHARACTERS = 64000

logger = logging.getLogger("agent_decision_audit")


@dataclass(frozen=True, kw_only=True)
class SubAgentSelectionAuditV2:
    agent_id: str
    tool_name: str
    input_json: Mapping[str, Any]
    output_json: Mapping[str, Any]
    rationale: str
    latency_ms: int


@dataclass(frozen=True, kw_only=True)
class SubAgentSelectionResultV2:
    selected: SubAgent | None
    confidence: float
    rationale: str
    audit: SubAgentSelectionAuditV2 | None


type SubAgentSelectionAuditSinkV2 = Callable[
    [SubAgentSelectionAuditV2],
    None | Awaitable[None],
]


@runtime_checkable
class SubAgentSelectionJudgeProtocolV2(Protocol):
    async def judge(
        self,
        *,
        task_description: str,
        candidates: Sequence[SubAgent],
    ) -> SubAgentSelectionResultV2: ...


@dataclass(frozen=True, kw_only=True)
class SubAgentSelectionJudgeServiceV2:
    """Operation-owned judge requiring one typed tool call and complete audit."""

    llm_clients: TenantLlmClientFactoryProtocolV2
    db: AsyncSession
    tenant_id: str
    user_id: str
    operation_id: str
    generation: PluginGenerationDescriptorV2
    audit_sink: SubAgentSelectionAuditSinkV2 | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    async def judge(
        self,
        *,
        task_description: str,
        candidates: Sequence[SubAgent],
    ) -> SubAgentSelectionResultV2:
        model_input = _judgment_input(
            task_description=task_description,
            candidates=candidates,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            operation_id=self.operation_id,
            generation=self.generation,
        )
        llm = await self.llm_clients.create(db=self.db, tenant_id=self.tenant_id)
        agent_id = _llm_agent_id(llm)
        started_at = time.perf_counter()
        try:
            response = await llm.generate(
                messages=_judgment_messages(model_input),
                tools=[_judgment_tool(candidates)],
                tool_choice={
                    "type": "function",
                    "function": {"name": SUBAGENT_SELECTION_TOOL_V2},
                },
                temperature=0.0,
                max_tokens=768,
            )
            output_json = _extract_tool_output(response)
            selected, confidence, rationale = _validated_output(candidates, output_json)
        except RuntimeV2Error:
            raise
        except Exception as exc:
            raise RuntimeV2Error(
                "subagent_selection_judge_failed",
                f"SubAgent selection judge failed with {type(exc).__name__}",
            ) from exc

        audit = SubAgentSelectionAuditV2(
            agent_id=agent_id,
            tool_name=SUBAGENT_SELECTION_TOOL_V2,
            input_json=model_input,
            output_json=output_json,
            rationale=rationale,
            latency_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
        )
        sink = self.audit_sink or _log_audit
        audit_result = sink(audit)
        if inspect.isawaitable(audit_result):
            await audit_result
        return SubAgentSelectionResultV2(
            selected=selected,
            confidence=confidence,
            rationale=rationale,
            audit=audit,
        )


@runtime_checkable
class SubAgentSelectionJudgeResolverProtocolV2(Protocol):
    def resolve(self, operation: OperationContextV2) -> SubAgentSelectionJudgeProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class SubAgentSelectionJudgeResolverV2:
    llm_clients: TenantLlmClientFactoryProtocolV2
    audit_sink: SubAgentSelectionAuditSinkV2 | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def resolve(self, operation: OperationContextV2) -> SubAgentSelectionJudgeServiceV2:
        db = _operation_db_session_v2(operation)
        tenant_id, user_id = _operation_identity_v2(operation)
        return SubAgentSelectionJudgeServiceV2(
            llm_clients=self.llm_clients,
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            operation_id=operation.operation_id,
            generation=operation.descriptor,
            audit_sink=self.audit_sink,
        )


@runtime_checkable
class SubAgentSelectionApplicationServiceProtocolV2(Protocol):
    async def match(self, task_description: str) -> SubAgentSelectionResultV2: ...


@dataclass(frozen=True, kw_only=True)
class SubAgentSelectionApplicationServiceV2:
    """Match against the complete accessible roster without deterministic semantics."""

    management: SubAgentManagementServiceProtocolV2
    judge: SubAgentSelectionJudgeProtocolV2

    async def match(self, task_description: str) -> SubAgentSelectionResultV2:
        candidates = await self.management.list_accessible(enabled_only=True)
        if not candidates:
            return SubAgentSelectionResultV2(
                selected=None,
                confidence=0.0,
                rationale="no enabled accessible SubAgent candidates",
                audit=None,
            )
        return await self.judge.judge(
            task_description=task_description,
            candidates=tuple(candidates),
        )


@runtime_checkable
class SubAgentSelectionApplicationResolverProtocolV2(Protocol):
    def resolve(
        self,
        operation: OperationContextV2,
    ) -> SubAgentSelectionApplicationServiceProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class SubAgentSelectionApplicationResolverV2:
    subagents: SubAgentManagementResolverProtocolV2
    judge: SubAgentSelectionJudgeResolverProtocolV2

    def resolve(self, operation: OperationContextV2) -> SubAgentSelectionApplicationServiceV2:
        management = self.subagents.resolve(operation)
        if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
            management, SubAgentManagementServiceProtocolV2
        ):
            raise RuntimeV2Error(
                "invalid_subagent_management_service",
                "SubAgent selection requires a valid management service",
            )
        judge = self.judge.resolve(operation)
        if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
            judge, SubAgentSelectionJudgeProtocolV2
        ):
            raise RuntimeV2Error(
                "invalid_subagent_selection_judge",
                "SubAgent selection requires a valid judgment service",
            )
        return SubAgentSelectionApplicationServiceV2(
            management=management,
            judge=judge,
        )


def _judgment_input(
    *,
    task_description: str,
    candidates: Sequence[SubAgent],
    tenant_id: str,
    user_id: str,
    operation_id: str,
    generation: PluginGenerationDescriptorV2,
) -> dict[str, Any]:
    task = task_description.strip()
    if not task:
        raise RuntimeV2Error(
            "subagent_selection_task_required",
            "SubAgent selection requires a task description",
        )
    if len(task) > _MAX_TASK_CHARACTERS:
        raise RuntimeV2Error(
            "subagent_selection_task_too_large",
            "SubAgent selection task exceeds the protocol limit",
        )
    if not candidates:
        raise RuntimeV2Error(
            "subagent_selection_candidates_required",
            "SubAgent selection judge requires candidates",
        )
    if len(candidates) > _MAX_CANDIDATES:
        raise RuntimeV2Error(
            "subagent_selection_roster_too_large",
            "SubAgent selection roster exceeds the protocol limit",
        )
    candidate_ids = [candidate.id for candidate in candidates]
    if (
        any(not candidate_id.strip() for candidate_id in candidate_ids)
        or len(candidate_ids) != len(set(candidate_ids))
        or any(
            candidate.tenant_id != tenant_id or not candidate.enabled for candidate in candidates
        )
    ):
        raise RuntimeV2Error(
            "subagent_selection_candidates_invalid",
            "SubAgent selection candidates violate tenant, identity, or enabled constraints",
        )
    model_input = {
        "task_description": task,
        "candidates": [_candidate_input(candidate) for candidate in candidates],
        "scope": {"tenant_id": tenant_id, "user_id": user_id},
        "operation_id": operation_id,
        "generation": generation.to_payload(),
    }
    serialized = json.dumps(model_input, sort_keys=True, separators=(",", ":"))
    if len(serialized) > _MAX_MODEL_INPUT_CHARACTERS:
        raise RuntimeV2Error(
            "subagent_selection_input_too_large",
            "SubAgent selection input exceeds the protocol limit",
        )
    return model_input


def _candidate_input(candidate: SubAgent) -> dict[str, Any]:
    return {
        "subagent_id": candidate.id,
        "name": candidate.name,
        "display_name": candidate.display_name,
        "project_id": candidate.project_id,
        "trigger": {
            "description": candidate.trigger.description,
            "keywords": list(candidate.trigger.keywords),
            "examples": list(candidate.trigger.examples),
        },
        "model": candidate.model.value,
        "allowed_tools": list(candidate.allowed_tools),
        "allowed_skills": list(candidate.allowed_skills),
        "allowed_mcp_servers": list(candidate.allowed_mcp_servers),
    }


def _judgment_messages(input_json: Mapping[str, Any]) -> list[LLMMessage]:
    system_prompt = " ".join(
        (
            "Act as the SubAgent selection Agent.",
            f"Call {SUBAGENT_SELECTION_TOOL_V2} exactly once and return no free text.",
            "Use the complete supplied candidate roster and task as structured data.",
            "Do not use keyword, regex, fixed confidence, threshold, or hidden fallback rules.",
            "Return null only when no supplied candidate is semantically appropriate.",
            "The rationale must not repeat sensitive task or candidate text.",
        )
    )
    return [
        LLMMessage.system(system_prompt),
        LLMMessage.user(json.dumps(input_json, sort_keys=True, separators=(",", ":"))),
    ]


def _judgment_tool(candidates: Sequence[SubAgent]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": SUBAGENT_SELECTION_TOOL_V2,
            "description": "Submit one audited SubAgent selection or an explicit no-match.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selected_subagent_id": {
                        "type": ["string", "null"],
                        "enum": [None, *[candidate.id for candidate in candidates]],
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "rationale": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1000,
                    },
                },
                "required": ["selected_subagent_id", "confidence", "rationale"],
                "additionalProperties": False,
            },
        },
    }


def _extract_tool_output(response: Mapping[str, object]) -> dict[str, Any]:
    tool_calls = _object_list(response.get("tool_calls"))
    if not tool_calls:
        choices = _object_list(response.get("choices"))
        choice = _object_mapping(choices[0]) if choices else None
        message = _object_mapping(choice.get("message")) if choice else None
        tool_calls = _object_list(message.get("tool_calls")) if message else []
    if not tool_calls:
        raise RuntimeV2Error(
            "subagent_selection_tool_call_required",
            "SubAgent selection judge omitted the required structured tool call",
        )
    if len(tool_calls) != 1:
        raise RuntimeV2Error(
            "subagent_selection_tool_call_count_invalid",
            "SubAgent selection judge must call exactly one tool",
        )
    call = _object_mapping(tool_calls[0])
    function = _object_mapping(call.get("function")) if call else None
    if function is None or function.get("name") != SUBAGENT_SELECTION_TOOL_V2:
        raise RuntimeV2Error(
            "subagent_selection_tool_call_unauthorized",
            "SubAgent selection judge returned an unauthorized tool call",
        )
    arguments = function.get("arguments")
    output = _object_mapping(arguments)
    if output is None and isinstance(arguments, str):
        try:
            output = _object_mapping(json.loads(arguments))
        except json.JSONDecodeError:
            output = None
    if output is None or set(output) != {
        "selected_subagent_id",
        "confidence",
        "rationale",
    }:
        raise RuntimeV2Error(
            "subagent_selection_tool_arguments_invalid",
            "SubAgent selection judge returned invalid tool arguments",
        )
    return dict(cast(Mapping[str, Any], output))


def _validated_output(
    candidates: Sequence[SubAgent],
    output: Mapping[str, Any],
) -> tuple[SubAgent | None, float, str]:
    selected_id = output.get("selected_subagent_id")
    selected = next(
        (candidate for candidate in candidates if candidate.id == selected_id),
        None,
    )
    if selected_id is not None and selected is None:
        raise RuntimeV2Error(
            "subagent_selection_candidate_invalid",
            "SubAgent selection judge selected outside the candidate roster",
        )
    confidence = output.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0.0 <= float(confidence) <= 1.0
        or (selected is None and float(confidence) != 0.0)
        or (selected is not None and float(confidence) <= 0.0)
    ):
        raise RuntimeV2Error(
            "subagent_selection_confidence_invalid",
            "SubAgent selection judge returned inconsistent confidence",
        )
    rationale = output.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale.strip()) > 1000:
        raise RuntimeV2Error(
            "subagent_selection_rationale_required",
            "SubAgent selection judge returned an invalid rationale",
        )
    return selected, float(confidence), rationale.strip()


def _llm_agent_id(llm: LLMClient) -> str:
    config = getattr(llm, "config", None)
    model = getattr(config, "model", None)
    if not isinstance(model, str) or not model.strip():
        raise RuntimeV2Error(
            "subagent_selection_agent_identity_missing",
            "SubAgent selection judge has no auditable model identity",
        )
    return f"tenant-llm:{model.strip()}"


def _object_list(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


def _object_mapping(value: object) -> Mapping[str, object] | None:
    candidate: Mapping[object, object] | None = None
    if isinstance(value, Mapping):
        candidate = cast("Mapping[object, object]", value)
    else:
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, Mapping):
                candidate = cast("Mapping[object, object]", dumped)
    if candidate is None or not all(isinstance(key, str) for key in candidate):
        return None
    return cast("Mapping[str, object]", candidate)


def _redacted_input(input_json: Mapping[str, Any]) -> dict[str, Any]:
    task = str(input_json.get("task_description", ""))
    candidates = cast(Sequence[Mapping[str, object]], input_json.get("candidates", ()))
    return {
        "task_description_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
        "task_description_length": len(task),
        "candidate_ids": [candidate.get("subagent_id") for candidate in candidates],
        "scope": input_json.get("scope"),
        "operation_id": input_json.get("operation_id"),
        "generation": input_json.get("generation"),
    }


def _redacted_output(output_json: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "selected_subagent_id": output_json.get("selected_subagent_id"),
        "confidence": output_json.get("confidence"),
        "rationale_sha256": hashlib.sha256(
            str(output_json.get("rationale", "")).encode("utf-8")
        ).hexdigest(),
    }


def _log_audit(audit: SubAgentSelectionAuditV2) -> None:
    logger.info(
        "SubAgent selection judgment completed",
        extra={
            "agent_id": audit.agent_id,
            "tool_name": audit.tool_name,
            "input": _redacted_input(audit.input_json),
            "output": _redacted_output(audit.output_json),
            "rationale": audit.rationale,
            "latency_ms": audit.latency_ms,
        },
    )


def _operation_db_session_v2(operation: OperationContextV2) -> AsyncSession:
    db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
    if not isinstance(db, AsyncSession):
        raise RuntimeV2Error(
            "invalid_operation_db_session",
            "SubAgent selection requires an AsyncSession operation service",
        )
    return db


def _operation_identity_v2(operation: OperationContextV2) -> tuple[str, str]:
    scope = operation.context.scope
    if scope.kind is not ScopeKindV2.TENANT or scope.tenant_id is None:
        raise RuntimeV2Error(
            "invalid_subagent_selection_operation_scope",
            "SubAgent selection requires an exact tenant operation scope",
        )
    identity = operation.require(_OPERATION_IDENTITY_SERVICE_V2)
    if not isinstance(identity, Mapping):
        raise RuntimeV2Error(
            "invalid_subagent_selection_operation_identity",
            "SubAgent selection requires structured operation identity",
        )
    values = cast("Mapping[str, object]", identity)
    tenant_id = values.get("tenant_id")
    user_id = values.get("user_id")
    if (
        not isinstance(tenant_id, str)
        or tenant_id != scope.tenant_id
        or not isinstance(user_id, str)
        or not user_id.strip()
    ):
        raise RuntimeV2Error(
            "invalid_subagent_selection_operation_identity",
            "SubAgent selection identity does not match the operation scope",
        )
    return tenant_id, user_id


def _apply_subagent_selection_judge_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "required-agent-tool-call":
        raise ValueError("SubAgent selection judge requires strategy required-agent-tool-call")
    llm_clients = context.require(SUBAGENT_SELECTION_LLM_CLIENTS_INJECT_V2)
    if not isinstance(llm_clients, TenantLlmClientFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_subagent_selection_llm_clients",
            "SubAgent selection judge requires a tenant LLM client factory",
        )
    _ = context.provide(
        SUBAGENT_SELECTION_JUDGE_SERVICE_V2,
        SubAgentSelectionJudgeResolverV2(llm_clients=llm_clients),
        label="subagent-selection-judge",
    )


def _apply_subagent_selection_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("SubAgent selection requires strategy operation-scoped-provider")
    subagents = context.require(SUBAGENT_SELECTION_APPLICATION_SUBAGENTS_INJECT_V2)
    if not isinstance(subagents, SubAgentManagementResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_subagent_management_resolver",
            "SubAgent selection requires a management resolver",
        )
    judge = context.require(SUBAGENT_SELECTION_APPLICATION_JUDGE_INJECT_V2)
    if not isinstance(judge, SubAgentSelectionJudgeResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_subagent_selection_judge_resolver",
            "SubAgent selection requires a judgment resolver",
        )
    _ = context.provide(
        SUBAGENT_SELECTION_APPLICATION_SERVICE_V2,
        SubAgentSelectionApplicationResolverV2(
            subagents=subagents,
            judge=judge,
        ),
        label="subagent-selection",
    )


def subagent_selection_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    return (
        PluginDefinitionV2(
            module_ref=SUBAGENT_SELECTION_JUDGE_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SUBAGENT_SELECTION_JUDGE_MODULE_V2),
            apply=_apply_subagent_selection_judge_v2,
        ),
        PluginDefinitionV2(
            module_ref=SUBAGENT_SELECTION_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SUBAGENT_SELECTION_APPLICATION_MODULE_V2),
            apply=_apply_subagent_selection_application_v2,
        ),
    )


__all__ = [
    "SUBAGENT_SELECTION_APPLICATION_JUDGE_INJECT_V2",
    "SUBAGENT_SELECTION_APPLICATION_MODULE_V2",
    "SUBAGENT_SELECTION_APPLICATION_SERVICE_V2",
    "SUBAGENT_SELECTION_APPLICATION_SUBAGENTS_INJECT_V2",
    "SUBAGENT_SELECTION_JUDGE_MODULE_V2",
    "SUBAGENT_SELECTION_JUDGE_SERVICE_V2",
    "SUBAGENT_SELECTION_LLM_CLIENTS_INJECT_V2",
    "SUBAGENT_SELECTION_TOOL_V2",
    "SubAgentSelectionApplicationResolverProtocolV2",
    "SubAgentSelectionApplicationResolverV2",
    "SubAgentSelectionApplicationServiceProtocolV2",
    "SubAgentSelectionApplicationServiceV2",
    "SubAgentSelectionAuditV2",
    "SubAgentSelectionJudgeProtocolV2",
    "SubAgentSelectionJudgeResolverProtocolV2",
    "SubAgentSelectionJudgeResolverV2",
    "SubAgentSelectionJudgeServiceV2",
    "SubAgentSelectionResultV2",
    "subagent_selection_definitions_v2",
]
