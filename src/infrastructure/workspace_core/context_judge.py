"""Agent-first Workspace Context selection for ambiguous Project memberships."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.llm_providers.llm_types import Message
from src.domain.llm_providers.models import ProviderConfig
from src.infrastructure.llm.model_pool import ModelPoolService, PoolFilter, get_model_pool_service

logger = logging.getLogger(__name__)

_CONTEXT_TOOL_NAME = "select_workspace_context"


class WorkspaceContextCandidate(BaseModel):
    """One normalized Project membership eligible for selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    membership_role: str = Field(min_length=1, max_length=64)


class WorkspaceContextCurrent(BaseModel):
    """Existing context supplied as continuity evidence, even when no longer accessible."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=0)


class WorkspaceContextJudgeRequest(BaseModel):
    """Complete structured evidence for one ambiguous context decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    current: WorkspaceContextCurrent | None = None
    candidates: list[WorkspaceContextCandidate] = Field(min_length=2, max_length=100)

    @model_validator(mode="after")
    def require_unique_candidates(self) -> WorkspaceContextJudgeRequest:
        scopes = {(candidate.tenant_id, candidate.project_id) for candidate in self.candidates}
        if len(scopes) != len(self.candidates):
            raise ValueError("Workspace Context candidates must be unique")
        return self


class WorkspaceContextJudgeVerdict(BaseModel):
    """Validated selection and the complete auditable structured tool call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selected: WorkspaceContextCandidate
    rationale: str = Field(min_length=1)
    evidence: list[str]
    agent_id: str = Field(min_length=1, max_length=512)
    tool_name: str = Field(min_length=1, max_length=128)
    input_json: dict[str, Any]
    output_json: dict[str, Any]
    latency_ms: int = Field(ge=0)


class WorkspaceContextJudgeUnavailable(RuntimeError):
    """No valid structured context-selection verdict was available."""


@runtime_checkable
class WorkspaceContextJudgePort(Protocol):
    """Structured judgment authority consumed by the authenticated HTTP adapter."""

    async def select(
        self,
        request: WorkspaceContextJudgeRequest,
    ) -> WorkspaceContextJudgeVerdict: ...


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


ClientFactory = Callable[[ProviderConfig], _LlmClient]


class AgentWorkspaceContextJudge:
    """Resolve only genuinely ambiguous candidate sets via a required Agent tool call."""

    def __init__(
        self,
        *,
        pool_service: ModelPoolService | _ModelPool | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        super().__init__()
        self._pool = pool_service or get_model_pool_service()
        self._client_factory = client_factory or _default_client_factory

    async def select(
        self,
        request: WorkspaceContextJudgeRequest,
    ) -> WorkspaceContextJudgeVerdict:
        judge_candidates = await self._pool.list_candidates(
            tenant_id=None,
            pool_filter=PoolFilter(require_tools=True),
        )
        if not judge_candidates:
            raise WorkspaceContextJudgeUnavailable(
                "no platform tool-capable Workspace Context judge is available"
            )
        judge_candidate = judge_candidates[0]
        input_json = _judgment_input(request)
        started_at = time.perf_counter()
        try:
            client = self._client_factory(judge_candidate.provider_config)
            response = await client.generate(
                messages=_judgment_messages(input_json),
                tools=[_selection_tool(len(request.candidates))],
                tool_choice={"type": "function", "function": {"name": _CONTEXT_TOOL_NAME}},
                temperature=0.0,
                max_tokens=384,
                model=judge_candidate.model_name,
            )
            output_json = _extract_context_tool_call(response)
            if output_json is None:
                raise WorkspaceContextJudgeUnavailable(
                    "Workspace Context judge omitted the required structured tool call"
                )
            candidate_index = output_json.get("candidate_index")
            if (
                isinstance(candidate_index, bool)
                or not isinstance(candidate_index, int)
                or candidate_index < 0
                or candidate_index >= len(request.candidates)
            ):
                raise WorkspaceContextJudgeUnavailable(
                    "Workspace Context judge returned an invalid candidate index"
                )
            rationale = output_json.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                raise WorkspaceContextJudgeUnavailable(
                    "Workspace Context judge returned an empty rationale"
                )
            evidence = output_json.get("evidence")
            if not isinstance(evidence, list) or not all(
                isinstance(item, str) for item in cast("list[object]", evidence)
            ):
                raise WorkspaceContextJudgeUnavailable(
                    "Workspace Context judge returned invalid evidence"
                )
        except WorkspaceContextJudgeUnavailable:
            raise
        except Exception as exc:
            raise WorkspaceContextJudgeUnavailable(
                f"Workspace Context judge failed with {type(exc).__name__}"
            ) from exc

        latency_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        selected = request.candidates[candidate_index]
        logger.info(
            "Workspace Context judgment completed",
            extra={
                "user_id": request.user_id,
                "tenant_id": selected.tenant_id,
                "project_id": selected.project_id,
                "agent_id": judge_candidate.candidate_key,
                "tool_name": _CONTEXT_TOOL_NAME,
                "latency_ms": latency_ms,
            },
        )
        return WorkspaceContextJudgeVerdict(
            selected=selected,
            rationale=rationale.strip(),
            evidence=cast("list[str]", evidence),
            agent_id=judge_candidate.candidate_key,
            tool_name=_CONTEXT_TOOL_NAME,
            input_json=input_json,
            output_json=output_json,
            latency_ms=latency_ms,
        )


def _judgment_input(request: WorkspaceContextJudgeRequest) -> dict[str, Any]:
    return {
        "user_id": request.user_id,
        "current": request.current.model_dump(mode="json") if request.current else None,
        "candidates": [
            {"candidate_index": index, **candidate.model_dump(mode="json")}
            for index, candidate in enumerate(request.candidates)
        ],
        "available_action": _CONTEXT_TOOL_NAME,
    }


def _judgment_messages(input_json: dict[str, Any]) -> list[Message]:
    return [
        Message.system(
            " ".join(
                (
                    "You are the Workspace Context selection judge.",
                    "Use only the supplied structured current context and membership candidates.",
                    "Call select_workspace_context exactly once with one supplied candidate index.",
                    "Do not infer from names, keywords, hidden priority, or unavailable data.",
                )
            )
        ),
        Message.user(json.dumps(input_json, sort_keys=True, separators=(",", ":"))),
    ]


def _selection_tool(candidate_count: int) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": _CONTEXT_TOOL_NAME,
            "description": "Select one supplied Workspace Context candidate with a rationale.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_index": {
                        "type": "integer",
                        "enum": list(range(candidate_count)),
                    },
                    "rationale": {"type": "string", "minLength": 1},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["candidate_index", "rationale", "evidence"],
                "additionalProperties": False,
            },
        },
    }


def _extract_context_tool_call(response: Mapping[str, object]) -> dict[str, Any] | None:
    tool_calls = _object_list(response.get("tool_calls"))
    if not tool_calls:
        choices = _object_list(response.get("choices"))
        first_choice = _object_mapping(choices[0]) if choices else None
        message = _object_mapping(first_choice.get("message")) if first_choice else None
        tool_calls = _object_list(message.get("tool_calls")) if message else []
    for raw_call in tool_calls:
        call = _object_mapping(raw_call)
        if call is None:
            continue
        function = _object_mapping(call.get("function"))
        if function is None or function.get("name") != _CONTEXT_TOOL_NAME:
            continue
        arguments = function.get("arguments")
        argument_mapping = _object_mapping(arguments)
        if argument_mapping is not None:
            return dict(argument_mapping)
        if isinstance(arguments, str):
            try:
                decoded: object = json.loads(arguments)
            except json.JSONDecodeError:
                return None
            decoded_mapping = _object_mapping(decoded)
            return dict(decoded_mapping) if decoded_mapping is not None else None
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


__all__ = [
    "AgentWorkspaceContextJudge",
    "WorkspaceContextCandidate",
    "WorkspaceContextCurrent",
    "WorkspaceContextJudgePort",
    "WorkspaceContextJudgeRequest",
    "WorkspaceContextJudgeUnavailable",
    "WorkspaceContextJudgeVerdict",
]
