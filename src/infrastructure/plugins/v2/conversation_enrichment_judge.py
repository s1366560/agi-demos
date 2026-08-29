"""Agent-first structured judgment for conversation title and summary enrichment."""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.llm_providers.llm_types import LLMClient, Message as LLMMessage
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2

from .llm_client_service import TenantLlmClientFactoryProtocolV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CONVERSATION_ENRICHMENT_JUDGE_MODULE_V2 = "builtin://memstack/judgment/conversation-enrichment"
CONVERSATION_ENRICHMENT_JUDGE_SERVICE_V2 = "service:judgment.conversation-enrichment"
CONVERSATION_ENRICHMENT_LLM_CLIENTS_INJECT_V2 = "llm_clients"
CONVERSATION_ENRICHMENT_TOOL_V2 = "submit_conversation_enrichment_v2"

_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"
_OPERATION_IDENTITY_SERVICE_V2 = "service:operation.identity"
_MODEL_ROLES = frozenset({"assistant", "user"})
_VALUE_LIMITS: Mapping[str, int] = {"title": 50, "summary": 500}
_INPUT_LIMITS: Mapping[str, int] = {"title": 500, "summary": 3000}

logger = logging.getLogger("agent_decision_audit")

ConversationEnrichmentPurposeV2 = Literal["title", "summary"]
ConversationEnrichmentRoleV2 = Literal["assistant", "user"]


@dataclass(frozen=True, kw_only=True)
class ConversationEnrichmentMessageV2:
    role: ConversationEnrichmentRoleV2
    content: str

    def __post_init__(self) -> None:
        if self.role not in _MODEL_ROLES or not self.content.strip():
            raise ValueError("conversation enrichment messages require a role and content")


@dataclass(frozen=True, kw_only=True)
class ConversationEnrichmentAuditV2:
    agent_id: str
    tool_name: str
    input_json: Mapping[str, Any]
    output_json: Mapping[str, Any]
    rationale: str
    latency_ms: int


@dataclass(frozen=True, kw_only=True)
class ConversationEnrichmentResultV2:
    value: str
    rationale: str
    audit: ConversationEnrichmentAuditV2


type ConversationEnrichmentAuditSinkV2 = Callable[
    [ConversationEnrichmentAuditV2],
    None | Awaitable[None],
]


@dataclass(frozen=True, kw_only=True)
class ConversationEnrichmentJudgeServiceV2:
    """Operation-owned judge requiring one typed tool call and complete audit."""

    llm_clients: TenantLlmClientFactoryProtocolV2
    db: AsyncSession
    tenant_id: str
    project_id: str
    user_id: str
    operation_id: str
    generation: PluginGenerationDescriptorV2
    audit_sink: ConversationEnrichmentAuditSinkV2 | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    async def judge(
        self,
        *,
        purpose: ConversationEnrichmentPurposeV2,
        conversation_id: str,
        messages: Sequence[ConversationEnrichmentMessageV2],
    ) -> ConversationEnrichmentResultV2:
        model_input = _judgment_input(
            purpose=purpose,
            conversation_id=conversation_id,
            messages=messages,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
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
                tools=[_judgment_tool(purpose)],
                tool_choice={
                    "type": "function",
                    "function": {"name": CONVERSATION_ENRICHMENT_TOOL_V2},
                },
                temperature=0.0,
                max_tokens=768,
            )
            output_json = _extract_tool_output(response)
            value, rationale = _validated_output(purpose, output_json)
        except RuntimeV2Error:
            raise
        except Exception as exc:
            raise RuntimeV2Error(
                "conversation_enrichment_judge_failed",
                f"conversation enrichment judge failed with {type(exc).__name__}",
            ) from exc

        audit = ConversationEnrichmentAuditV2(
            agent_id=agent_id,
            tool_name=CONVERSATION_ENRICHMENT_TOOL_V2,
            input_json=model_input,
            output_json=output_json,
            rationale=rationale,
            latency_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
        )
        sink = self.audit_sink or _log_audit
        audit_result = sink(audit)
        if inspect.isawaitable(audit_result):
            await audit_result
        return ConversationEnrichmentResultV2(
            value=value,
            rationale=rationale,
            audit=audit,
        )


@runtime_checkable
class ConversationEnrichmentJudgeProtocolV2(Protocol):
    async def judge(
        self,
        *,
        purpose: ConversationEnrichmentPurposeV2,
        conversation_id: str,
        messages: Sequence[ConversationEnrichmentMessageV2],
    ) -> object: ...


@runtime_checkable
class ConversationEnrichmentJudgeResolverProtocolV2(Protocol):
    def resolve(self, operation: OperationContextV2) -> ConversationEnrichmentJudgeProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class ConversationEnrichmentJudgeResolverV2:
    llm_clients: TenantLlmClientFactoryProtocolV2
    audit_sink: ConversationEnrichmentAuditSinkV2 | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def resolve(self, operation: OperationContextV2) -> ConversationEnrichmentJudgeServiceV2:
        db = _operation_db_session_v2(operation)
        tenant_id, project_id, user_id = _operation_identity_v2(operation)
        return ConversationEnrichmentJudgeServiceV2(
            llm_clients=self.llm_clients,
            db=db,
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            operation_id=operation.operation_id,
            generation=operation.descriptor,
            audit_sink=self.audit_sink,
        )


def _judgment_input(
    *,
    purpose: ConversationEnrichmentPurposeV2,
    conversation_id: str,
    messages: Sequence[ConversationEnrichmentMessageV2],
    tenant_id: str,
    project_id: str,
    user_id: str,
    operation_id: str,
    generation: PluginGenerationDescriptorV2,
) -> dict[str, Any]:
    if purpose not in _VALUE_LIMITS:
        raise RuntimeV2Error(
            "conversation_enrichment_purpose_invalid",
            "conversation enrichment purpose is invalid",
        )
    if not conversation_id.strip() or not operation_id.strip():
        raise RuntimeV2Error(
            "conversation_enrichment_scope_invalid",
            "conversation enrichment requires conversation and operation identity",
        )
    bounded_messages = _bounded_messages(purpose, messages)
    return {
        "purpose": purpose,
        "conversation_id": conversation_id,
        "scope": {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "user_id": user_id,
        },
        "operation_id": operation_id,
        "generation": generation.to_payload(),
        "messages": bounded_messages,
    }


def _bounded_messages(
    purpose: ConversationEnrichmentPurposeV2,
    messages: Sequence[ConversationEnrichmentMessageV2],
) -> list[dict[str, str]]:
    if not messages:
        raise RuntimeV2Error(
            "conversation_enrichment_messages_required",
            "conversation enrichment requires model-visible messages",
        )
    if purpose == "title" and (len(messages) != 1 or messages[0].role != "user"):
        raise RuntimeV2Error(
            "conversation_enrichment_title_source_invalid",
            "conversation title enrichment requires exactly one user message",
        )
    remaining = _INPUT_LIMITS[purpose]
    bounded: list[dict[str, str]] = []
    for message in messages:
        if message.role not in _MODEL_ROLES or remaining <= 0:
            continue
        content = message.content[:remaining]
        if not content:
            continue
        bounded.append({"role": message.role, "content": content})
        remaining -= len(content)
    if not bounded:
        raise RuntimeV2Error(
            "conversation_enrichment_messages_required",
            "conversation enrichment requires model-visible messages",
        )
    return bounded


def _judgment_messages(input_json: Mapping[str, Any]) -> list[LLMMessage]:
    system_prompt = " ".join(
        (
            "Act as the conversation enrichment Agent. Call",
            f"{CONVERSATION_ENRICHMENT_TOOL_V2} exactly once and return no free text.",
            "Use only the supplied ordered model-visible messages. The tool rationale must",
            "explain the choice without repeating sensitive message content.",
        )
    )
    return [
        LLMMessage.system(system_prompt),
        LLMMessage.user(json.dumps(input_json, sort_keys=True, separators=(",", ":"))),
    ]


def _judgment_tool(purpose: ConversationEnrichmentPurposeV2) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": CONVERSATION_ENRICHMENT_TOOL_V2,
            "description": "Submit one audited conversation title or summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "purpose": {"const": purpose, "type": "string"},
                    "value": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": _VALUE_LIMITS[purpose],
                    },
                    "rationale": {"type": "string", "minLength": 1, "maxLength": 1000},
                },
                "required": ["purpose", "value", "rationale"],
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
            "conversation_enrichment_tool_call_required",
            "conversation enrichment judge omitted the required structured tool call",
        )
    if len(tool_calls) != 1:
        raise RuntimeV2Error(
            "conversation_enrichment_tool_call_count_invalid",
            "conversation enrichment judge must call exactly one tool",
        )
    call = _object_mapping(tool_calls[0])
    function = _object_mapping(call.get("function")) if call else None
    if function is None or function.get("name") != CONVERSATION_ENRICHMENT_TOOL_V2:
        raise RuntimeV2Error(
            "conversation_enrichment_tool_call_unauthorized",
            "conversation enrichment judge returned an unauthorized tool call",
        )
    arguments = function.get("arguments")
    output = _object_mapping(arguments)
    if output is None and isinstance(arguments, str):
        try:
            output = _object_mapping(json.loads(arguments))
        except json.JSONDecodeError:
            output = None
    if output is None or set(output) != {"purpose", "value", "rationale"}:
        raise RuntimeV2Error(
            "conversation_enrichment_tool_arguments_invalid",
            "conversation enrichment judge returned invalid tool arguments",
        )
    return dict(cast(Mapping[str, Any], output))


def _validated_output(
    purpose: ConversationEnrichmentPurposeV2,
    output: Mapping[str, Any],
) -> tuple[str, str]:
    if output.get("purpose") != purpose:
        raise RuntimeV2Error(
            "conversation_enrichment_purpose_mismatch",
            "conversation enrichment judge returned the wrong purpose",
        )
    value = output.get("value")
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip()) > _VALUE_LIMITS[purpose]
    ):
        raise RuntimeV2Error(
            "conversation_enrichment_value_invalid",
            "conversation enrichment judge returned an invalid value",
        )
    rationale = output.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise RuntimeV2Error(
            "conversation_enrichment_rationale_required",
            "conversation enrichment judge returned an empty rationale",
        )
    return value.strip(), rationale.strip()


def _llm_agent_id(llm: LLMClient) -> str:
    config = getattr(llm, "config", None)
    model = getattr(config, "model", None)
    if not isinstance(model, str) or not model.strip():
        raise RuntimeV2Error(
            "conversation_enrichment_agent_identity_missing",
            "conversation enrichment judge has no auditable model identity",
        )
    return f"tenant-llm:{model.strip()}"


def _object_list(value: object) -> list[object]:
    return cast(list[object], value) if isinstance(value, list) else []


def _object_mapping(value: object) -> Mapping[str, object] | None:
    candidate: Mapping[object, object] | None = None
    if isinstance(value, Mapping):
        candidate = cast(Mapping[object, object], value)
    else:
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, Mapping):
                candidate = cast(Mapping[object, object], dumped)
    if candidate is None:
        return None
    if not all(isinstance(key, str) for key in candidate):
        return None
    return cast(Mapping[str, object], candidate)


def _redacted_input(input_json: Mapping[str, Any]) -> dict[str, Any]:
    redacted = dict(input_json)
    messages = cast(Sequence[Mapping[str, object]], input_json.get("messages", ()))
    redacted["messages"] = [
        {
            "role": message.get("role"),
            "content_sha256": hashlib.sha256(
                str(message.get("content", "")).encode("utf-8")
            ).hexdigest(),
            "content_length": len(str(message.get("content", ""))),
        }
        for message in messages
    ]
    return redacted


def _redacted_output(output_json: Mapping[str, Any]) -> dict[str, Any]:
    value = str(output_json.get("value", ""))
    return {
        "purpose": output_json.get("purpose"),
        "value_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        "value_length": len(value),
        "rationale": output_json.get("rationale"),
    }


def _log_audit(audit: ConversationEnrichmentAuditV2) -> None:
    logger.info(
        "Conversation enrichment judgment completed",
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
            "conversation enrichment requires an AsyncSession operation service",
        )
    return db


def _operation_identity_v2(operation: OperationContextV2) -> tuple[str, str, str]:
    identity = operation.require(_OPERATION_IDENTITY_SERVICE_V2)
    if not isinstance(identity, Mapping):
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "conversation enrichment requires operation identity metadata",
        )
    values = cast(Mapping[str, object], identity)
    tenant_id = values.get("tenant_id")
    project_id = values.get("project_id")
    user_id = values.get("user_id")
    if not all(isinstance(value, str) and value for value in (tenant_id, project_id, user_id)):
        raise RuntimeV2Error(
            "invalid_operation_identity",
            "conversation enrichment requires tenant, project, and user identity",
        )
    tenant_id = cast(str, tenant_id)
    project_id = cast(str, project_id)
    user_id = cast(str, user_id)
    scope = operation.context.scope
    if scope.tenant_id != tenant_id or scope.project_id != project_id:
        raise RuntimeV2Error(
            "operation_identity_scope_mismatch",
            "conversation enrichment identity does not match its operation scope",
        )
    return tenant_id, project_id, user_id


def _apply_conversation_enrichment_judge_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "required-agent-tool-call":
        raise ValueError("conversation enrichment judge requires strategy required-agent-tool-call")
    llm_clients = context.require(CONVERSATION_ENRICHMENT_LLM_CLIENTS_INJECT_V2)
    if not isinstance(llm_clients, TenantLlmClientFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_conversation_enrichment_llm_clients",
            "conversation enrichment judge requires a tenant LLM client factory",
        )
    _ = context.provide(
        CONVERSATION_ENRICHMENT_JUDGE_SERVICE_V2,
        ConversationEnrichmentJudgeResolverV2(llm_clients=llm_clients),
        label="conversation-enrichment-judge",
    )


def conversation_enrichment_judge_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=CONVERSATION_ENRICHMENT_JUDGE_MODULE_V2,
        contract_digest=generated_contract_digest_v2(CONVERSATION_ENRICHMENT_JUDGE_MODULE_V2),
        apply=_apply_conversation_enrichment_judge_v2,
    )


__all__ = [
    "CONVERSATION_ENRICHMENT_JUDGE_MODULE_V2",
    "CONVERSATION_ENRICHMENT_JUDGE_SERVICE_V2",
    "CONVERSATION_ENRICHMENT_LLM_CLIENTS_INJECT_V2",
    "CONVERSATION_ENRICHMENT_TOOL_V2",
    "ConversationEnrichmentAuditV2",
    "ConversationEnrichmentJudgeProtocolV2",
    "ConversationEnrichmentJudgeResolverProtocolV2",
    "ConversationEnrichmentJudgeResolverV2",
    "ConversationEnrichmentJudgeServiceV2",
    "ConversationEnrichmentMessageV2",
    "ConversationEnrichmentPurposeV2",
    "ConversationEnrichmentResultV2",
    "conversation_enrichment_judge_definition_v2",
]
