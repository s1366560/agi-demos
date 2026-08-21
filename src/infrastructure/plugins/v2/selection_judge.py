"""Agent-first structured selection authority for subjective plugin choices."""

from __future__ import annotations

import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

from src.domain.llm_providers.llm_types import Message
from src.domain.llm_providers.models import ProviderConfig
from src.domain.model.plugins.generated_v2 import ScopeV2
from src.infrastructure.llm.model_pool import ModelPoolService, PoolFilter, get_model_pool_service

from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

PLUGIN_SELECTION_JUDGE_MODULE_V2 = "builtin://memstack/plugins/selection-judge"
PLUGIN_SELECTION_JUDGE_SERVICE_V2 = "service:plugin-selection-judge"
_TOOL_NAME = "select_plugin_candidate_v2"
logger = logging.getLogger("plugin_audit")


@dataclass(frozen=True, kw_only=True)
class PluginSelectionCandidateV2:
    candidate_id: str
    plugin_id: str
    capability_id: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True, kw_only=True)
class PluginSelectionRequestV2:
    decision_type: str
    candidates: tuple[PluginSelectionCandidateV2, ...]
    scope: ScopeV2
    explicit_constraints: Mapping[str, Any]
    runtime_context: Mapping[str, Any]


@dataclass(frozen=True, kw_only=True)
class PluginSelectionAuditV2:
    agent_id: str
    tool_name: str
    input_json: Mapping[str, Any]
    output_json: Mapping[str, Any]
    rationale: str
    latency_ms: int


@dataclass(frozen=True, kw_only=True)
class PluginSelectionResultV2:
    selected: PluginSelectionCandidateV2
    source: str
    rationale: str
    confidence_explanation: str
    audit: PluginSelectionAuditV2 | None


class PluginSelectionJudgeV2(Protocol):
    async def select(self, request: PluginSelectionRequestV2) -> PluginSelectionResultV2: ...


class _CandidateModel(Protocol):
    @property
    def candidate_key(self) -> str: ...

    @property
    def provider_config(self) -> ProviderConfig: ...

    @property
    def model_name(self) -> str: ...


class _ModelPool(Protocol):
    async def list_candidates(
        self,
        tenant_id: str | None,
        pool_filter: PoolFilter | None = None,
    ) -> list[_CandidateModel]: ...


class _LlmClient(Protocol):
    async def generate(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any],
        temperature: float,
        max_tokens: int,
        model: str,
    ) -> dict[str, Any]: ...


type ClientFactoryV2 = Callable[[ProviderConfig], _LlmClient]
type SelectionAuditSinkV2 = Callable[[PluginSelectionAuditV2], None | Awaitable[None]]


class AgentPluginSelectionJudgeV2:
    """Require one structured Agent tool call for every ``auto`` selection."""

    def __init__(
        self,
        *,
        pool_service: ModelPoolService | _ModelPool | None = None,
        client_factory: ClientFactoryV2 | None = None,
        audit_sink: SelectionAuditSinkV2 | None = None,
    ) -> None:
        self._pool = pool_service or get_model_pool_service()
        self._client_factory = client_factory or _default_client_factory
        self._audit_sink = audit_sink or _log_audit

    async def select(self, request: PluginSelectionRequestV2) -> PluginSelectionResultV2:
        _validate_request(request)
        judge_candidates = await self._pool.list_candidates(
            tenant_id=request.scope.tenant_id,
            pool_filter=PoolFilter(require_tools=True),
        )
        if not judge_candidates:
            raise RuntimeV2Error(
                "plugin_selection_judge_unavailable",
                "no tool-capable plugin selection judge is available",
            )
        judge = judge_candidates[0]
        input_json = _selection_input(request)
        started_at = time.perf_counter()
        try:
            response = await self._client_factory(judge.provider_config).generate(
                messages=_selection_messages(input_json),
                tools=[_selection_tool(request.candidates)],
                tool_choice={"type": "function", "function": {"name": _TOOL_NAME}},
                temperature=0.0,
                max_tokens=384,
                model=judge.model_name,
            )
            output_json = _extract_tool_call(response)
            selected, rationale, confidence = _validate_output(request, output_json)
        except RuntimeV2Error:
            raise
        except Exception as exc:
            raise RuntimeV2Error(
                "plugin_selection_judge_failed",
                f"plugin selection judge failed with {type(exc).__name__}",
            ) from exc
        audit = PluginSelectionAuditV2(
            agent_id=judge.candidate_key,
            tool_name=_TOOL_NAME,
            input_json=input_json,
            output_json=cast("dict[str, Any]", output_json),
            rationale=rationale,
            latency_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
        )
        audit_result = self._audit_sink(audit)
        if inspect.isawaitable(audit_result):
            await audit_result
        return PluginSelectionResultV2(
            selected=selected,
            source="agent-judge",
            rationale=rationale,
            confidence_explanation=confidence,
            audit=audit,
        )


async def resolve_plugin_selection_v2(
    request: PluginSelectionRequestV2,
    *,
    explicit_candidate_id: str | None,
    judge: PluginSelectionJudgeV2,
) -> PluginSelectionResultV2:
    """Resolve explicit bindings deterministically and delegate only ``auto`` choices."""
    _validate_request(request)
    if explicit_candidate_id is not None:
        selected = next(
            (
                candidate
                for candidate in request.candidates
                if candidate.candidate_id == explicit_candidate_id
            ),
            None,
        )
        if selected is None:
            raise RuntimeV2Error(
                "plugin_selection_explicit_candidate_missing",
                "explicit plugin selection is outside the candidate set",
            )
        return PluginSelectionResultV2(
            selected=selected,
            source="explicit-binding",
            rationale="explicit candidate binding",
            confidence_explanation="deterministic explicit binding",
            audit=None,
        )
    return await judge.select(request)


def _validate_request(request: PluginSelectionRequestV2) -> None:
    if not request.decision_type.strip():
        raise ValueError("decision_type must be non-empty")
    if not request.candidates:
        raise ValueError("plugin selection requires candidates")
    ids = [candidate.candidate_id for candidate in request.candidates]
    if any(not candidate_id.strip() for candidate_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("plugin selection candidate IDs must be non-empty and unique")


def _selection_input(request: PluginSelectionRequestV2) -> dict[str, Any]:
    return {
        "decision_type": request.decision_type,
        "candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "plugin_id": candidate.plugin_id,
                "capability_id": candidate.capability_id,
                "metadata": dict(candidate.metadata),
            }
            for candidate in request.candidates
        ],
        "scope": {
            "kind": request.scope.kind.value,
            "tenant_id": request.scope.tenant_id,
            "project_id": request.scope.project_id,
            "session_id": request.scope.session_id,
        },
        "explicit_constraints": dict(request.explicit_constraints),
        "runtime_context": dict(request.runtime_context),
    }


def _selection_messages(input_json: dict[str, Any]) -> list[Message]:
    return [
        Message.system(
            "Select exactly one supplied plugin candidate by calling "
            "select_plugin_candidate_v2 once. Use only structured candidate metadata, scope, "
            "constraints, and runtime context. Do not use keyword, regex, score-threshold, or "
            "hidden fallback rules."
        ),
        Message.user(json.dumps(input_json, sort_keys=True, separators=(",", ":"))),
    ]


def _selection_tool(candidates: Sequence[PluginSelectionCandidateV2]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": _TOOL_NAME,
            "description": "Select one supplied plugin candidate with auditable reasoning.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {
                        "type": "string",
                        "enum": [candidate.candidate_id for candidate in candidates],
                    },
                    "rationale": {"type": "string", "minLength": 1},
                    "confidence_explanation": {"type": "string", "minLength": 1},
                },
                "required": ["candidate_id", "rationale", "confidence_explanation"],
                "additionalProperties": False,
            },
        },
    }


def _validate_output(
    request: PluginSelectionRequestV2,
    output: dict[str, Any] | None,
) -> tuple[PluginSelectionCandidateV2, str, str]:
    if output is None:
        raise RuntimeV2Error(
            "plugin_selection_tool_call_required",
            "plugin selection judge omitted the required structured tool call",
        )
    candidate_id = output.get("candidate_id")
    selected = next(
        (candidate for candidate in request.candidates if candidate.candidate_id == candidate_id),
        None,
    )
    rationale = output.get("rationale")
    confidence = output.get("confidence_explanation")
    if selected is None:
        raise RuntimeV2Error(
            "plugin_selection_candidate_invalid",
            "plugin selection judge selected a candidate outside the candidate set",
        )
    if not isinstance(rationale, str) or not rationale.strip():
        raise RuntimeV2Error(
            "plugin_selection_rationale_required",
            "plugin selection judge returned an empty rationale",
        )
    if not isinstance(confidence, str) or not confidence.strip():
        raise RuntimeV2Error(
            "plugin_selection_confidence_required",
            "plugin selection judge returned an empty confidence explanation",
        )
    return selected, rationale.strip(), confidence.strip()


def _extract_tool_call(response: Mapping[str, object]) -> dict[str, Any] | None:
    tool_calls = _object_list(response.get("tool_calls"))
    if not tool_calls:
        choices = _object_list(response.get("choices"))
        choice = _object_mapping(choices[0]) if choices else None
        message = _object_mapping(choice.get("message")) if choice else None
        tool_calls = _object_list(message.get("tool_calls")) if message else []
    for raw_call in tool_calls:
        call = _object_mapping(raw_call)
        function = _object_mapping(call.get("function")) if call else None
        if function is None or function.get("name") != _TOOL_NAME:
            continue
        arguments = function.get("arguments")
        mapping = _object_mapping(arguments)
        if mapping is not None:
            return dict(mapping)
        if isinstance(arguments, str):
            try:
                return dict(_object_mapping(json.loads(arguments)) or {}) or None
            except json.JSONDecodeError:
                return None
    return None


def _object_list(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


def _object_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, dict):
        return None
    candidate = cast("dict[object, object]", value)
    if not all(isinstance(key, str) for key in candidate):
        return None
    return cast("dict[str, object]", candidate)


def _default_client_factory(provider_config: ProviderConfig) -> _LlmClient:
    from src.infrastructure.llm.litellm.litellm_client import create_litellm_client
    from src.infrastructure.llm.model_catalog import get_model_catalog_service

    return cast(
        "_LlmClient",
        create_litellm_client(provider_config, catalog=get_model_catalog_service()),
    )


def _log_audit(audit: PluginSelectionAuditV2) -> None:
    logger.info(
        "Plugin selection judgment completed",
        extra={
            "agent_id": audit.agent_id,
            "tool_name": audit.tool_name,
            "input": dict(audit.input_json),
            "output": dict(audit.output_json),
            "rationale": audit.rationale,
            "latency_ms": audit.latency_ms,
        },
    )


def _apply_plugin_selection_judge_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "required-agent-tool-call":
        raise ValueError("plugin selection judge requires strategy required-agent-tool-call")
    context.provide(
        PLUGIN_SELECTION_JUDGE_SERVICE_V2,
        AgentPluginSelectionJudgeV2(),
        label="plugin-selection-judge",
    )


def builtin_plugin_selection_judge_definition_v2() -> PluginDefinitionV2:
    return PluginDefinitionV2(
        module_ref=PLUGIN_SELECTION_JUDGE_MODULE_V2,
        contract_digest=generated_contract_digest_v2(PLUGIN_SELECTION_JUDGE_MODULE_V2),
        apply=_apply_plugin_selection_judge_v2,
    )
