"""Terminal tools for built-in workspace plan judgment agents."""

from __future__ import annotations

import json
from typing import Any

from src.domain.model.review.review_finding import ReviewSeverity
from src.domain.ports.services.iteration_review_port import IterationReviewDecision
from src.domain.ports.services.workspace_verification_judge_port import (
    WorkspaceVerificationJudgeVerdict,
    WorkspaceVerificationNextActionKind,
)
from src.infrastructure.agent.sisyphus.builtin_agent import (
    BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID,
    BUILTIN_WORKSPACE_VERIFIER_ID,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_WORKER,
    require_workspace_session_role,
    runtime_context_string,
)

WORKSPACE_SUBMIT_VERIFICATION_JUDGMENT_TOOL_NAME = "workspace_submit_verification_judgment"
WORKSPACE_SUBMIT_ITERATION_REVIEW_TOOL_NAME = "workspace_submit_iteration_review"

_VALID_VERIFICATION_VERDICTS = {item.value for item in WorkspaceVerificationJudgeVerdict}
_VALID_VERIFICATION_NEXT_ACTION_KINDS = {
    item.value for item in WorkspaceVerificationNextActionKind
}
_VALID_REVIEW_VERDICTS = {"complete_goal", "continue_next_iteration", "needs_human_review"}
_VALID_PHASES = {"research", "plan", "implement", "test", "deploy", "review"}
_VALID_SEVERITIES = {item.value for item in ReviewSeverity}

WORKSPACE_VERIFICATION_JUDGMENT_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": sorted(_VALID_VERIFICATION_VERDICTS)},
        "rationale": {"type": "string"},
        "failed_criteria": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 12,
        },
        "required_next_action": {"type": "string"},
        "next_action_kind": {
            "type": "string",
            "enum": sorted(_VALID_VERIFICATION_NEXT_ACTION_KINDS),
            "description": (
                "Structured next action: none, retry_same_node, create_repair_node, or "
                "human_required."
            ),
        },
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
}

WORKSPACE_ITERATION_REVIEW_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": sorted(_VALID_REVIEW_VERDICTS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "summary": {"type": "string"},
        "next_sprint_goal": {"type": "string"},
        "feedback_items": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
        },
        "next_tasks": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "description": {"type": "string"},
                    "target_subagent": {"type": ["string", "null"]},
                    "dependencies": {"type": "array", "items": {"type": "string"}},
                    "priority": {"type": "integer"},
                    "phase": {"type": "string", "enum": sorted(_VALID_PHASES)},
                    "expected_artifacts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 6,
                    },
                },
                "required": ["id", "description"],
            },
        },
        "findings": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": "integer", "minimum": 0},
                    "category": {"type": "string"},
                    "severity": {"type": "string", "enum": sorted(_VALID_SEVERITIES)},
                    "raw_confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "description": {"type": "string"},
                    "suggestion": {"type": "string"},
                    "concrete_evidence": {"type": "boolean"},
                },
                "required": [
                    "file",
                    "line",
                    "category",
                    "severity",
                    "raw_confidence",
                    "description",
                    "suggestion",
                ],
            },
        },
    },
    "required": ["verdict", "confidence", "summary"],
    "additionalProperties": False,
}


def _deny(error: str, **extra: Any) -> ToolResult:
    payload: dict[str, Any] = {"error": error}
    payload.update(extra)
    return ToolResult(output=json.dumps(payload, ensure_ascii=False), is_error=True)


def _require_builtin_agent(ctx: ToolContext, *, expected_agent_id: str, tool_name: str) -> str | None:
    role_error = require_workspace_session_role(
        ctx,
        expected_role=WORKSPACE_ROLE_WORKER,
        action_label=tool_name,
    )
    if role_error:
        return role_error
    selected_agent_id = runtime_context_string(ctx, "selected_agent_id")
    if selected_agent_id != expected_agent_id:
        return f"{tool_name} may only be called by {expected_agent_id}"
    return None


@tool_define(
    name=WORKSPACE_SUBMIT_VERIFICATION_JUDGMENT_TOOL_NAME,
    description=(
        "Terminal workspace verification tool. The builtin workspace verifier calls this exactly "
        "once to submit the semantic node verification verdict."
    ),
    parameters=WORKSPACE_VERIFICATION_JUDGMENT_TOOL_PARAMETERS,
    permission=None,
    category="workspace",
)
async def workspace_submit_verification_judgment_tool(
    ctx: ToolContext,
    *,
    verdict: str,
    rationale: str,
    failed_criteria: list[str],
    required_next_action: str,
    confidence: float,
    next_action_kind: str = WorkspaceVerificationNextActionKind.RETRY_SAME_NODE.value,
) -> ToolResult:
    error = _require_builtin_agent(
        ctx,
        expected_agent_id=BUILTIN_WORKSPACE_VERIFIER_ID,
        tool_name=WORKSPACE_SUBMIT_VERIFICATION_JUDGMENT_TOOL_NAME,
    )
    if error:
        return _deny(error, selected_agent_id=runtime_context_string(ctx, "selected_agent_id") or None)
    if verdict not in _VALID_VERIFICATION_VERDICTS:
        return _deny(f"invalid verification verdict: {verdict}")
    if next_action_kind not in _VALID_VERIFICATION_NEXT_ACTION_KINDS:
        return _deny(f"invalid verification next_action_kind: {next_action_kind}")
    payload = {
        "verdict": verdict,
        "rationale": str(rationale or "").strip() or verdict,
        "failed_criteria": _string_list(failed_criteria, limit=12),
        "required_next_action": str(required_next_action or "").strip(),
        "next_action_kind": next_action_kind,
        "confidence": _confidence(confidence),
    }
    return ToolResult(
        output=json.dumps({"captured": True, "verdict": verdict}, ensure_ascii=False),
        metadata={"verification_judgment": payload},
    )


@tool_define(
    name=WORKSPACE_SUBMIT_ITERATION_REVIEW_TOOL_NAME,
    description=(
        "Terminal workspace iteration review tool. The builtin iteration reviewer calls this "
        "exactly once to submit the sprint verdict and optional next tasks."
    ),
    parameters=WORKSPACE_ITERATION_REVIEW_TOOL_PARAMETERS,
    permission=None,
    category="workspace",
)
async def workspace_submit_iteration_review_tool(
    ctx: ToolContext,
    *,
    verdict: IterationReviewDecision,
    confidence: float,
    summary: str,
    next_sprint_goal: str = "",
    feedback_items: list[str] | None = None,
    next_tasks: list[dict[str, Any]] | None = None,
    findings: list[dict[str, Any]] | None = None,
) -> ToolResult:
    error = _require_builtin_agent(
        ctx,
        expected_agent_id=BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID,
        tool_name=WORKSPACE_SUBMIT_ITERATION_REVIEW_TOOL_NAME,
    )
    if error:
        return _deny(error, selected_agent_id=runtime_context_string(ctx, "selected_agent_id") or None)
    if verdict not in _VALID_REVIEW_VERDICTS:
        return _deny(f"invalid iteration review verdict: {verdict}")
    payload = {
        "verdict": verdict,
        "confidence": _confidence(confidence),
        "summary": str(summary or "").strip() or verdict,
        "next_sprint_goal": str(next_sprint_goal or "").strip(),
        "feedback_items": _string_list(feedback_items or [], limit=8),
        "next_tasks": _normalize_next_tasks(next_tasks or []),
        "findings": _normalize_findings(findings or []),
    }
    return ToolResult(
        output=json.dumps({"captured": True, "verdict": verdict}, ensure_ascii=False),
        metadata={"iteration_review": payload},
    )


def _string_list(value: object, *, limit: int) -> list[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list | tuple):
        items = [str(item) for item in value]
    else:
        return []
    cleaned = [item.strip() for item in items if item.strip()]
    return list(dict.fromkeys(cleaned))[:limit]


def _confidence(value: object) -> float:
    if not isinstance(value, int | float | str):
        return 0.0
    try:
        parsed = float(value)
    except ValueError:
        return 0.0
    return max(0.0, min(parsed, 1.0))


def _normalize_next_tasks(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for index, item in enumerate(value[:12], start=1):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        phase = str(item.get("phase") or "").strip()
        task = {
            "id": str(item.get("id") or f"t{index}").strip() or f"t{index}",
            "description": description,
            "dependencies": _string_list(item.get("dependencies") or [], limit=8),
            "priority": int(item.get("priority") or 0),
            "expected_artifacts": _string_list(item.get("expected_artifacts") or [], limit=6),
        }
        target_subagent = item.get("target_subagent")
        if isinstance(target_subagent, str) and target_subagent.strip():
            task["target_subagent"] = target_subagent.strip()
        if phase in _VALID_PHASES:
            task["phase"] = phase
        tasks.append(task)
    return tasks


def _normalize_findings(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in value[:12]:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "").strip().upper()
        if severity not in _VALID_SEVERITIES:
            continue
        file_path = str(item.get("file") or "").strip()
        category = str(item.get("category") or "").strip()
        description = str(item.get("description") or "").strip()
        suggestion = str(item.get("suggestion") or "").strip()
        if not file_path or not category or not description:
            continue
        findings.append(
            {
                "file": file_path,
                "line": int(item.get("line") or 0),
                "category": category,
                "severity": severity,
                "raw_confidence": int(item.get("raw_confidence") or 0),
                "description": description,
                "suggestion": suggestion,
                "concrete_evidence": bool(item.get("concrete_evidence")),
            }
        )
    return findings


__all__ = [
    "WORKSPACE_ITERATION_REVIEW_TOOL_PARAMETERS",
    "WORKSPACE_SUBMIT_ITERATION_REVIEW_TOOL_NAME",
    "WORKSPACE_SUBMIT_VERIFICATION_JUDGMENT_TOOL_NAME",
    "WORKSPACE_VERIFICATION_JUDGMENT_TOOL_PARAMETERS",
    "workspace_submit_iteration_review_tool",
    "workspace_submit_verification_judgment_tool",
]
