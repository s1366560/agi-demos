"""Agent-first judgments for Workspace Autonomy root-task selection."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any, Literal, Protocol, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.llm_providers.llm_types import Message
from src.domain.llm_providers.models import ProviderConfig
from src.infrastructure.llm.model_pool import ModelPoolService, PoolFilter, get_model_pool_service

logger = logging.getLogger(__name__)

_AUTONOMY_TOOL_NAME: Literal["judge_workspace_autonomy"] = "judge_workspace_autonomy"
WorkspaceAutonomyVerdict = Literal["continue", "block", "escalate"]


class WorkspaceAutonomyCandidate(BaseModel):
    """One structurally eligible root Task supplied to the Agent judge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    root_task_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=1_000)
    description: str | None = Field(default=None, max_length=10_000)
    status: str = Field(min_length=1, max_length=64)
    metadata: dict[str, Any]


class WorkspaceAutonomyJudgeRequest(BaseModel):
    """Bounded structured evidence for one subjective Autonomy decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    actor_id: str = Field(min_length=1, max_length=256)
    workspace_revision: int = Field(ge=0)
    force: bool
    candidates: list[WorkspaceAutonomyCandidate] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_unique_candidates(self) -> WorkspaceAutonomyJudgeRequest:
        roots = {candidate.root_task_id for candidate in self.candidates}
        if len(roots) != len(self.candidates):
            raise ValueError("Workspace Autonomy root Task candidates must be unique")
        return self


class WorkspaceAutonomyJudgeVerdict(BaseModel):
    """Validated verdict plus the complete auditable structured tool call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: WorkspaceAutonomyVerdict
    selected_root_task_id: str | None = None
    rationale: str = Field(min_length=1)
    agent_id: str = Field(min_length=1, max_length=512)
    tool_name: Literal["judge_workspace_autonomy"]
    input_json: dict[str, Any]
    output_json: dict[str, Any]
    latency_ms: int = Field(ge=0)


class WorkspaceAutonomyJudgeUnavailable(RuntimeError):
    """No valid structured Autonomy judgment was available."""


@runtime_checkable
class WorkspaceAutonomyJudgePort(Protocol):
    """Structured judgment authority consumed by the authenticated adapter."""

    async def judge(
        self,
        request: WorkspaceAutonomyJudgeRequest,
    ) -> WorkspaceAutonomyJudgeVerdict: ...


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


class AgentWorkspaceAutonomyJudge:
    """Require an Agent tool call for every semantic Autonomy verdict."""

    def __init__(
        self,
        *,
        pool_service: ModelPoolService | _ModelPool | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        super().__init__()
        self._pool = pool_service or get_model_pool_service()
        self._client_factory = client_factory or _default_client_factory

    async def judge(
        self,
        request: WorkspaceAutonomyJudgeRequest,
    ) -> WorkspaceAutonomyJudgeVerdict:
        judge_candidates = await self._pool.list_candidates(
            tenant_id=request.tenant_id,
            pool_filter=PoolFilter(require_tools=True),
        )
        if not judge_candidates:
            raise WorkspaceAutonomyJudgeUnavailable(
                "no tenant tool-capable Workspace Autonomy judge is available"
            )
        judge_candidate = judge_candidates[0]
        input_json = _judgment_input(request)
        started_at = time.perf_counter()
        try:
            client = self._client_factory(judge_candidate.provider_config)
            response = await client.generate(
                messages=_judgment_messages(input_json),
                tools=[_judgment_tool(request.candidates)],
                tool_choice={"type": "function", "function": {"name": _AUTONOMY_TOOL_NAME}},
                temperature=0.0,
                max_tokens=512,
                model=judge_candidate.model_name,
            )
            output_json = _extract_autonomy_tool_call(response)
            if output_json is None:
                raise WorkspaceAutonomyJudgeUnavailable(
                    "Workspace Autonomy judge omitted the required structured tool call"
                )
            verdict = output_json.get("verdict")
            if verdict not in {"continue", "block", "escalate"}:
                raise WorkspaceAutonomyJudgeUnavailable(
                    "Workspace Autonomy judge returned an invalid verdict"
                )
            selected_root_task_id = output_json.get("selected_root_task_id")
            candidate_ids = {candidate.root_task_id for candidate in request.candidates}
            if selected_root_task_id is not None and (
                not isinstance(selected_root_task_id, str)
                or selected_root_task_id not in candidate_ids
            ):
                raise WorkspaceAutonomyJudgeUnavailable(
                    "Workspace Autonomy judge selected a Task outside the candidates"
                )
            if verdict == "continue" and selected_root_task_id is None:
                raise WorkspaceAutonomyJudgeUnavailable(
                    "Workspace Autonomy judge omitted the required root Task"
                )
            rationale = output_json.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                raise WorkspaceAutonomyJudgeUnavailable(
                    "Workspace Autonomy judge returned an empty rationale"
                )
        except WorkspaceAutonomyJudgeUnavailable:
            raise
        except Exception as exc:
            raise WorkspaceAutonomyJudgeUnavailable(
                f"Workspace Autonomy judge failed with {type(exc).__name__}"
            ) from exc

        latency_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        logger.info(
            "Workspace Autonomy judgment completed",
            extra={
                "tenant_id": request.tenant_id,
                "project_id": request.project_id,
                "workspace_id": request.workspace_id,
                "workspace_revision": request.workspace_revision,
                "agent_id": judge_candidate.candidate_key,
                "tool_name": _AUTONOMY_TOOL_NAME,
                "verdict": verdict,
                "latency_ms": latency_ms,
            },
        )
        return WorkspaceAutonomyJudgeVerdict(
            verdict=cast("WorkspaceAutonomyVerdict", verdict),
            selected_root_task_id=selected_root_task_id,
            rationale=rationale.strip(),
            agent_id=judge_candidate.candidate_key,
            tool_name=_AUTONOMY_TOOL_NAME,
            input_json=input_json,
            output_json=output_json,
            latency_ms=latency_ms,
        )


def _judgment_input(request: WorkspaceAutonomyJudgeRequest) -> dict[str, Any]:
    return {
        **request.model_dump(mode="json"),
        "available_action": _AUTONOMY_TOOL_NAME,
    }


def _judgment_messages(input_json: dict[str, Any]) -> list[Message]:
    return [
        Message.system(
            " ".join(
                (
                    "You are the Workspace Autonomy judgment agent.",
                    "Use only the supplied structured Workspace revision and root Task evidence.",
                    "Call judge_workspace_autonomy exactly once with a verdict and rationale.",
                    "Select a root Task only from the supplied candidates when continuing.",
                    "Do not use keyword rules, hidden priority, or unavailable data.",
                )
            )
        ),
        Message.user(json.dumps(input_json, sort_keys=True, separators=(",", ":"))),
    ]


def _judgment_tool(candidates: list[WorkspaceAutonomyCandidate]) -> dict[str, Any]:
    candidate_ids = [candidate.root_task_id for candidate in candidates]
    return {
        "type": "function",
        "function": {
            "name": _AUTONOMY_TOOL_NAME,
            "description": "Judge one supplied Workspace Autonomy tick.",
            "parameters": {
                "type": "object",
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["continue", "block", "escalate"],
                    },
                    "selected_root_task_id": {
                        "type": ["string", "null"],
                        "enum": [*candidate_ids, None],
                    },
                    "rationale": {"type": "string", "minLength": 1},
                },
                "required": ["verdict", "selected_root_task_id", "rationale"],
                "additionalProperties": False,
            },
        },
    }


def _extract_autonomy_tool_call(response: Mapping[str, object]) -> dict[str, Any] | None:
    tool_calls = _object_list(response.get("tool_calls"))
    if not tool_calls:
        choices = _object_list(response.get("choices"))
        first_choice = _object_mapping(choices[0]) if choices else None
        message = _object_mapping(first_choice.get("message")) if first_choice else None
        tool_calls = _object_list(message.get("tool_calls")) if message else []
    for raw_call in tool_calls:
        call = _object_mapping(raw_call)
        function = _object_mapping(call.get("function")) if call else None
        if function is None or function.get("name") != _AUTONOMY_TOOL_NAME:
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
    "AgentWorkspaceAutonomyJudge",
    "WorkspaceAutonomyCandidate",
    "WorkspaceAutonomyJudgePort",
    "WorkspaceAutonomyJudgeRequest",
    "WorkspaceAutonomyJudgeUnavailable",
    "WorkspaceAutonomyJudgeVerdict",
]
