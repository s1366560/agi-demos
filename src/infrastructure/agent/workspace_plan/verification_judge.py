"""LLM-backed Agent-First verification judge for workspace plan nodes."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.domain.llm_providers.llm_types import LLMClient
from src.domain.ports.services.workspace_verification_judge_port import (
    WorkspaceVerificationJudgeRequest,
    WorkspaceVerificationJudgeResult,
    WorkspaceVerificationJudgeVerdict,
)

logger = logging.getLogger(__name__)

_VALID_VERDICTS = {item.value for item in WorkspaceVerificationJudgeVerdict}


class LLMWorkspaceVerificationJudge:
    """Ask an LLM judge to make the final subjective verification verdict."""

    def __init__(self, llm_client: LLMClient) -> None:
        super().__init__()
        self._llm_client = llm_client

    async def judge(
        self,
        request: WorkspaceVerificationJudgeRequest,
    ) -> WorkspaceVerificationJudgeResult:
        payload = _request_payload(request)
        try:
            response = await self._llm_client.generate(
                messages=[
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": payload},
                ],
                tools=[_judge_tool_schema()],
                temperature=0.0,
                max_tokens=1200,
                tool_choice={
                    "type": "function",
                    "function": {"name": "judge_workspace_verification"},
                },
            )
        except Exception as forced_exc:
            logger.debug(
                "workspace verification judge forced tool call failed; retrying: %s",
                forced_exc,
            )
            response = await self._llm_client.generate(
                messages=[
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": payload},
                ],
                tools=[_judge_tool_schema()],
                temperature=0.0,
                max_tokens=1200,
            )
        parsed = _parse_judge_response(response)
        if parsed is not None:
            return parsed

        repaired_response = await self._llm_client.generate(
            messages=[
                {"role": "system", "content": _json_repair_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "context": json.loads(payload),
                            "previous_unstructured_response": _response_text(response)[:4000],
                            "required_json_shape": {
                                "verdict": "needs_rework",
                                "rationale": "short evidence-backed rationale",
                                "failed_criteria": ["criterion or guard that still fails"],
                                "required_next_action": "single concrete next action",
                                "confidence": 0.75,
                            },
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=1200,
        )
        repaired = _parse_judge_response(repaired_response)
        if repaired is None:
            raise ValueError("workspace verification judge did not return structured arguments")
        return repaired


class UnavailableWorkspaceVerificationJudge:
    """Force retry/recovery when the Agent-First judge surface is unavailable."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def judge(
        self,
        request: WorkspaceVerificationJudgeRequest,
    ) -> WorkspaceVerificationJudgeResult:
        _ = request
        return WorkspaceVerificationJudgeResult(
            verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
            rationale=self._reason,
            failed_criteria=("workspace_verification_judge",),
            required_next_action="retry verification when judge agent is available",
            confidence=0.5,
        )


def _system_prompt() -> str:
    return (
        "You are the workspace verification judge. Make exactly one structured tool call named "
        "judge_workspace_verification. You make the final semantic judgment for whether the "
        "reported node output is acceptable, needs more agent work, is blocked by human-only "
        "authority, or should retry because infrastructure failed. Deterministic guards are "
        "evidence, not the final semantic verdict. Use accepted only when the worker report, "
        "artifacts, verification evidence, and acceptance criteria together show the node goal "
        "is satisfied. Do not accept if the completed worker report is missing. Use needs_rework "
        "for missing evidence, failed tests, dirty worktree evidence, incomplete output, or "
        "quality gaps that an agent can fix. Use retry_infrastructure for sandbox, model, tool, "
        "rate-limit, or transient platform failures. Use blocked_human_required only for missing "
        "credentials, private access, permission, irreversible external deployment/spend, legal "
        "or product approval, unsafe destructive action, or another authority boundary that an "
        "agent cannot resolve. Do not choose blocked_human_required for ordinary verification "
        "failure, missing evidence, clean-worktree sentinel output, or low quality."
    )


def _json_repair_system_prompt() -> str:
    return (
        "Return only one JSON object with verdict, rationale, failed_criteria, "
        "required_next_action, and confidence. verdict must be one of accepted, needs_rework, "
        "blocked_human_required, retry_infrastructure."
    )


def _request_payload(request: WorkspaceVerificationJudgeRequest) -> str:
    payload = {
        "workspace_id": request.workspace_id,
        "node": {
            "id": request.node_id,
            "title": request.node_title,
            "description": request.node_description,
            "acceptance_criteria": list(request.acceptance_criteria),
        },
        "attempt": {
            "id": request.attempt_id,
            "worker_summary": request.worker_summary,
            "candidate_artifacts": list(request.candidate_artifacts),
            "candidate_verifications": list(request.candidate_verifications),
        },
        "evidence": {
            "task_evidence_refs": list(request.task_evidence_refs),
            "latest_verification_results": list(request.latest_verification_results),
            "guard_failures": list(request.guard_failures),
            "recent_git_status": request.recent_git_status,
        },
        "sandbox": {
            "code_root": request.sandbox_code_root,
            "worktree_path": request.worktree_path,
        },
        "task_metadata": request.task_metadata,
        "policy": {
            "verdicts": sorted(_VALID_VERDICTS),
            "blocked_human_required_only_for": [
                "credentials or private access",
                "permissions or external authority",
                "irreversible deployment, spending, or destructive action",
                "legal, compliance, or product approval",
            ],
            "needs_rework_for": [
                "missing evidence",
                "failed tests or failed quality checks",
                "dirty or ambiguous git worktree evidence",
                "incomplete worker output",
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _judge_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "judge_workspace_verification",
            "description": "Return the final semantic verification verdict for one plan node.",
            "parameters": {
                "type": "object",
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": sorted(_VALID_VERDICTS),
                    },
                    "rationale": {"type": "string"},
                    "failed_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 12,
                    },
                    "required_next_action": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": [
                    "verdict",
                    "rationale",
                    "failed_criteria",
                    "required_next_action",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        },
    }


def _parse_judge_response(response: dict[str, Any]) -> WorkspaceVerificationJudgeResult | None:
    args = _response_arguments(response)
    if not args:
        return None
    raw_verdict = str(args.get("verdict") or "").strip()
    if raw_verdict not in _VALID_VERDICTS:
        return None
    rationale = str(args.get("rationale") or "").strip()
    next_action = str(args.get("required_next_action") or "").strip()
    failed = _string_tuple(args.get("failed_criteria"), limit=12)
    return WorkspaceVerificationJudgeResult(
        verdict=WorkspaceVerificationJudgeVerdict(raw_verdict),
        rationale=rationale or raw_verdict,
        failed_criteria=failed,
        required_next_action=next_action,
        confidence=_float_between(args.get("confidence"), default=0.0),
    )


def _response_arguments(response: dict[str, Any]) -> dict[str, Any] | None:  # noqa: PLR0911
    tool_calls = response.get("tool_calls", [])
    if tool_calls:
        tool_call = tool_calls[0]
        function_data = _read_field(tool_call, "function", tool_call)
        args_raw = _read_field(function_data, "arguments", "{}")
        if isinstance(args_raw, str):
            try:
                parsed = json.loads(args_raw)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
        return args_raw if isinstance(args_raw, dict) else None
    content = response.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _response_text(response: dict[str, Any]) -> str:
    content = response.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    try:
        return json.dumps(response, ensure_ascii=False, default=str)
    except TypeError:
        return str(response)


def _read_field(source: object, key: str, default: object) -> object:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _string_tuple(value: object, *, limit: int) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list | tuple):
        items = [str(item) for item in value]
    else:
        return ()
    cleaned = [item.strip() for item in items if item.strip()]
    return tuple(dict.fromkeys(cleaned))[:limit]


def _float_between(value: object, *, default: float) -> float:
    if not isinstance(value, int | float | str):
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(0.0, min(parsed, 1.0))


__all__ = ["LLMWorkspaceVerificationJudge", "UnavailableWorkspaceVerificationJudge"]
