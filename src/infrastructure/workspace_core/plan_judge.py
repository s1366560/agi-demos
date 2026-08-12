"""Agent-first judgments for subjective Workspace Plan transitions."""

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

_PLAN_TOOL_NAME = "judge_workspace_plan"
PlanJudgmentKind = Literal[
    "recover_stale_attempts",
    "trigger_next_iteration",
    "select_pipeline_target",
    "regenerate_delivery_contract",
    "request_node_replan",
    "accept_node_review",
]


class WorkspacePlanJudgeRequest(BaseModel):
    """Bounded structured evidence for one subjective Plan decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    actor_id: str = Field(min_length=1, max_length=256)
    plan_id: str = Field(min_length=1, max_length=128)
    plan_revision: int = Field(ge=0)
    kind: PlanJudgmentKind
    candidate_node_ids: list[str] = Field(max_length=500)
    evidence: dict[str, Any]

    @model_validator(mode="after")
    def validate_candidates(self) -> WorkspacePlanJudgeRequest:
        if any(not node_id.strip() for node_id in self.candidate_node_ids):
            raise ValueError("Workspace Plan candidate node IDs must not be blank")
        if len(set(self.candidate_node_ids)) != len(self.candidate_node_ids):
            raise ValueError("Workspace Plan candidate node IDs must be unique")
        if self.kind == "select_pipeline_target" and not self.candidate_node_ids:
            raise ValueError("Workspace Plan pipeline selection requires candidates")
        return self


class WorkspacePlanJudgeVerdict(BaseModel):
    """Validated decision plus the complete auditable structured tool call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proceed: bool
    selected_node_id: str | None = None
    rationale: str = Field(min_length=1)
    agent_id: str = Field(min_length=1, max_length=512)
    tool_name: Literal["judge_workspace_plan"]
    input_json: dict[str, Any]
    output_json: dict[str, Any]
    latency_ms: int = Field(ge=0)


class WorkspacePlanJudgeUnavailable(RuntimeError):
    """No valid structured Plan judgment was available."""


@runtime_checkable
class WorkspacePlanJudgePort(Protocol):
    """Structured judgment authority consumed by the authenticated adapter."""

    async def judge(self, request: WorkspacePlanJudgeRequest) -> WorkspacePlanJudgeVerdict: ...


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


class AgentWorkspacePlanJudge:
    """Require an Agent tool call for every semantic Plan verdict."""

    def __init__(
        self,
        *,
        pool_service: ModelPoolService | _ModelPool | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        super().__init__()
        self._pool = pool_service or get_model_pool_service()
        self._client_factory = client_factory or _default_client_factory

    async def judge(self, request: WorkspacePlanJudgeRequest) -> WorkspacePlanJudgeVerdict:
        judge_candidates = await self._pool.list_candidates(
            tenant_id=request.tenant_id,
            pool_filter=PoolFilter(require_tools=True),
        )
        if not judge_candidates:
            raise WorkspacePlanJudgeUnavailable(
                "no tenant tool-capable Workspace Plan judge is available"
            )
        judge_candidate = judge_candidates[0]
        input_json = _judgment_input(request)
        started_at = time.perf_counter()
        try:
            client = self._client_factory(judge_candidate.provider_config)
            response = await client.generate(
                messages=_judgment_messages(input_json),
                tools=[_judgment_tool(request.candidate_node_ids)],
                tool_choice={"type": "function", "function": {"name": _PLAN_TOOL_NAME}},
                temperature=0.0,
                max_tokens=512,
                model=judge_candidate.model_name,
            )
            output_json = _extract_plan_tool_call(response)
            if output_json is None:
                raise WorkspacePlanJudgeUnavailable(
                    "Workspace Plan judge omitted the required structured tool call"
                )
            proceed = output_json.get("proceed")
            if not isinstance(proceed, bool):
                raise WorkspacePlanJudgeUnavailable(
                    "Workspace Plan judge returned an invalid proceed verdict"
                )
            selected_node_id = output_json.get("selected_node_id")
            if selected_node_id is not None and (
                not isinstance(selected_node_id, str)
                or selected_node_id not in request.candidate_node_ids
            ):
                raise WorkspacePlanJudgeUnavailable(
                    "Workspace Plan judge selected a node outside the candidates"
                )
            if proceed and request.kind == "select_pipeline_target" and selected_node_id is None:
                raise WorkspacePlanJudgeUnavailable(
                    "Workspace Plan judge omitted the required selected node"
                )
            rationale = output_json.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                raise WorkspacePlanJudgeUnavailable(
                    "Workspace Plan judge returned an empty rationale"
                )
        except WorkspacePlanJudgeUnavailable:
            raise
        except Exception as exc:
            raise WorkspacePlanJudgeUnavailable(
                f"Workspace Plan judge failed with {type(exc).__name__}"
            ) from exc

        latency_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        logger.info(
            "Workspace Plan judgment completed",
            extra={
                "tenant_id": request.tenant_id,
                "project_id": request.project_id,
                "workspace_id": request.workspace_id,
                "plan_id": request.plan_id,
                "kind": request.kind,
                "agent_id": judge_candidate.candidate_key,
                "tool_name": _PLAN_TOOL_NAME,
                "latency_ms": latency_ms,
            },
        )
        return WorkspacePlanJudgeVerdict(
            proceed=proceed,
            selected_node_id=selected_node_id,
            rationale=rationale.strip(),
            agent_id=judge_candidate.candidate_key,
            tool_name=_PLAN_TOOL_NAME,
            input_json=input_json,
            output_json=output_json,
            latency_ms=latency_ms,
        )


def _judgment_input(request: WorkspacePlanJudgeRequest) -> dict[str, Any]:
    return {
        **request.model_dump(mode="json"),
        "available_action": _PLAN_TOOL_NAME,
    }


def _judgment_messages(input_json: dict[str, Any]) -> list[Message]:
    return [
        Message.system(
            " ".join(
                (
                    "You are the Workspace Plan judgment agent.",
                    "Use only the supplied structured plan evidence and candidate node IDs.",
                    "Call judge_workspace_plan exactly once with a proceed verdict and rationale.",
                    "Select a node only from candidate_node_ids and only when the action needs it.",
                    "Do not use keyword rules, hidden priority, or unavailable data.",
                )
            )
        ),
        Message.user(json.dumps(input_json, sort_keys=True, separators=(",", ":"))),
    ]


def _judgment_tool(candidate_node_ids: list[str]) -> dict[str, Any]:
    selected_schema: dict[str, Any] = {"type": ["string", "null"]}
    if candidate_node_ids:
        selected_schema["enum"] = [*candidate_node_ids, None]
    return {
        "type": "function",
        "function": {
            "name": _PLAN_TOOL_NAME,
            "description": "Judge one supplied Workspace Plan transition.",
            "parameters": {
                "type": "object",
                "properties": {
                    "proceed": {"type": "boolean"},
                    "selected_node_id": selected_schema,
                    "rationale": {"type": "string", "minLength": 1},
                },
                "required": ["proceed", "selected_node_id", "rationale"],
                "additionalProperties": False,
            },
        },
    }


def _extract_plan_tool_call(response: Mapping[str, object]) -> dict[str, Any] | None:
    tool_calls = _object_list(response.get("tool_calls"))
    if not tool_calls:
        choices = _object_list(response.get("choices"))
        first_choice = _object_mapping(choices[0]) if choices else None
        message = _object_mapping(first_choice.get("message")) if first_choice else None
        tool_calls = _object_list(message.get("tool_calls")) if message else []
    for raw_call in tool_calls:
        call = _object_mapping(raw_call)
        function = _object_mapping(call.get("function")) if call else None
        if function is None or function.get("name") != _PLAN_TOOL_NAME:
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
    "AgentWorkspacePlanJudge",
    "WorkspacePlanJudgePort",
    "WorkspacePlanJudgeRequest",
    "WorkspacePlanJudgeUnavailable",
    "WorkspacePlanJudgeVerdict",
]
