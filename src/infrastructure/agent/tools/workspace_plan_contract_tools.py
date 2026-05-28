"""Terminal tools for built-in workspace plan judgment agents."""

from __future__ import annotations

import json
from typing import Any

from src.domain.model.review.review_finding import ReviewSeverity
from src.domain.ports.services.iteration_review_port import IterationReviewDecision
from src.domain.ports.services.workspace_supervisor_decision_port import (
    WorkspaceSupervisorDecisionAction,
)
from src.domain.ports.services.workspace_verification_judge_port import (
    WorkspaceVerificationFeedbackKind,
    WorkspaceVerificationFeedbackSeverity,
    WorkspaceVerificationFeedbackTargetLayer,
    WorkspaceVerificationJudgeVerdict,
    WorkspaceVerificationNextActionKind,
    WorkspaceVerificationRecommendedAction,
)
from src.infrastructure.agent.sisyphus.builtin_agent import (
    BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID,
    BUILTIN_WORKSPACE_SUPERVISOR_ID,
    BUILTIN_WORKSPACE_VERIFIER_ID,
    BUILTIN_WORKSPACE_WORKTREE_MANAGER_ID,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ID_KEY,
    WORKSPACE_ROLE_CONTRACT,
    WORKSPACE_SESSION_ROLE_KEY,
    runtime_context_string,
)

WORKSPACE_SUBMIT_VERIFICATION_JUDGMENT_TOOL_NAME = "workspace_submit_verification_judgment"
WORKSPACE_SUBMIT_ITERATION_REVIEW_TOOL_NAME = "workspace_submit_iteration_review"
WORKSPACE_SUBMIT_SUPERVISOR_DECISION_TOOL_NAME = "workspace_submit_supervisor_decision"
WORKSPACE_SUBMIT_WORKTREE_PREPARATION_TOOL_NAME = "workspace_submit_worktree_preparation"

_VALID_VERIFICATION_VERDICTS = {item.value for item in WorkspaceVerificationJudgeVerdict}
_VALID_VERIFICATION_NEXT_ACTION_KINDS = {item.value for item in WorkspaceVerificationNextActionKind}
_VALID_VERIFICATION_FEEDBACK_TARGET_LAYERS = {
    item.value for item in WorkspaceVerificationFeedbackTargetLayer
}
_VALID_VERIFICATION_FEEDBACK_KINDS = {item.value for item in WorkspaceVerificationFeedbackKind}
_VALID_VERIFICATION_FEEDBACK_SEVERITIES = {
    item.value for item in WorkspaceVerificationFeedbackSeverity
}
_VALID_VERIFICATION_RECOMMENDED_ACTIONS = {
    item.value for item in WorkspaceVerificationRecommendedAction
}
_VALID_REVIEW_VERDICTS = {"complete_goal", "continue_next_iteration", "needs_human_review"}
_VALID_SUPERVISOR_ACTIONS = {item.value for item in WorkspaceSupervisorDecisionAction}
_VALID_WORKTREE_PREPARATION_STATUSES = {"prepared", "fallback_used", "failed", "skipped"}
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
        "satisfied_guard_failures": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 12,
            "description": (
                "Required guard failure ids from the input guard_failures that this verdict "
                "explicitly satisfies using fresh current-attempt evidence. Leave empty unless "
                "the evidence proves why the guard no longer blocks acceptance."
            ),
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
        "repair_brief": {
            "type": "object",
            "description": (
                "Compact current-attempt repair brief for retry_same_node verdicts. Include "
                "failed_items, evidence, allowed_write_scope, forbidden_actions, "
                "minimum_verifications, and fresh_evidence_requirements when applicable."
            ),
            "additionalProperties": True,
        },
        "feedback_items": {
            "type": "array",
            "maxItems": 8,
            "description": (
                "Layer-targeted feedback items that explain who should act next. Use worker "
                "only for failures the same worker can fix; use planner/reviewer/runtime/"
                "verifier_policy/human when retrying the same worker would be wasteful."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "target_layer": {
                        "type": "string",
                        "enum": sorted(_VALID_VERIFICATION_FEEDBACK_TARGET_LAYERS),
                    },
                    "feedback_kind": {
                        "type": "string",
                        "enum": sorted(_VALID_VERIFICATION_FEEDBACK_KINDS),
                    },
                    "severity": {
                        "type": "string",
                        "enum": sorted(_VALID_VERIFICATION_FEEDBACK_SEVERITIES),
                    },
                    "recommended_action": {
                        "type": "string",
                        "enum": sorted(_VALID_VERIFICATION_RECOMMENDED_ACTIONS),
                    },
                    "summary": {"type": "string"},
                    "evidence_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 12,
                    },
                    "failure_signature": {"type": "string"},
                },
                "required": [
                    "target_layer",
                    "feedback_kind",
                    "severity",
                    "recommended_action",
                ],
                "additionalProperties": False,
            },
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

WORKSPACE_SUPERVISOR_DECISION_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": sorted(_VALID_SUPERVISOR_ACTIONS)},
        "rationale": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "feedback_items": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "object", "additionalProperties": True},
        },
        "retry_not_before_seconds": {"type": ["integer", "null"], "minimum": 0},
        "repair_brief": {
            "type": "object",
            "additionalProperties": True,
        },
        "event_payload": {
            "type": "object",
            "additionalProperties": True,
        },
    },
    "required": ["action", "rationale", "confidence"],
    "additionalProperties": False,
}

WORKSPACE_WORKTREE_PREPARATION_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": sorted(_VALID_WORKTREE_PREPARATION_STATUSES),
        },
        "reason": {"type": "string"},
        "output": {"type": "string"},
        "worktree_path": {"type": "string"},
        "branch_name": {"type": "string"},
        "base_ref": {"type": "string"},
        "original_base_ref": {"type": "string"},
        "resolved_base_ref": {"type": "string"},
        "fallback_reason": {"type": "string"},
        "git_fsck_summary": {"type": "string"},
        "pruned_worktrees_count": {"type": ["integer", "null"], "minimum": 0},
    },
    "required": ["status", "worktree_path", "branch_name", "base_ref"],
    "additionalProperties": False,
}

def _deny(error: str, **extra: Any) -> ToolResult:
    payload: dict[str, Any] = {"error": error}
    payload.update(extra)
    return ToolResult(output=json.dumps(payload, ensure_ascii=False), is_error=True)


def _require_builtin_agent(
    ctx: ToolContext, *, expected_agent_id: str, tool_name: str
) -> str | None:
    role = runtime_context_string(ctx, WORKSPACE_SESSION_ROLE_KEY)
    if role != WORKSPACE_ROLE_CONTRACT:
        return (
            f"{tool_name} may only be called from a workspace {WORKSPACE_ROLE_CONTRACT} session "
            f"(current role: {role or 'none'})"
        )
    if not runtime_context_string(ctx, WORKSPACE_ID_KEY):
        return "workspace_id is missing from runtime_context — is this a workspace session?"
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
    satisfied_guard_failures: list[str] | None = None,
    next_action_kind: str = "",
    repair_brief: dict[str, Any] | None = None,
    feedback_items: list[dict[str, Any]] | None = None,
) -> ToolResult:
    error = _require_builtin_agent(
        ctx,
        expected_agent_id=BUILTIN_WORKSPACE_VERIFIER_ID,
        tool_name=WORKSPACE_SUBMIT_VERIFICATION_JUDGMENT_TOOL_NAME,
    )
    if error:
        return _deny(
            error, selected_agent_id=runtime_context_string(ctx, "selected_agent_id") or None
        )
    if verdict not in _VALID_VERIFICATION_VERDICTS:
        return _deny(f"invalid verification verdict: {verdict}")
    resolved_next_action_kind = _verification_next_action_kind(next_action_kind, verdict)
    if resolved_next_action_kind not in _VALID_VERIFICATION_NEXT_ACTION_KINDS:
        return _deny(f"invalid verification next_action_kind: {next_action_kind}")
    payload: dict[str, Any] = {
        "verdict": verdict,
        "rationale": str(rationale or "").strip() or verdict,
        "failed_criteria": _string_list(failed_criteria, limit=12),
        "satisfied_guard_failures": _string_list(satisfied_guard_failures or [], limit=12),
        "required_next_action": str(required_next_action or "").strip(),
        "next_action_kind": resolved_next_action_kind,
        "confidence": _confidence(confidence),
    }
    if isinstance(repair_brief, dict) and repair_brief:
        payload["repair_brief"] = repair_brief
    normalized_feedback = _verification_feedback_items(feedback_items or [])
    if normalized_feedback:
        payload["feedback_items"] = normalized_feedback
    return ToolResult(
        output=json.dumps({"captured": True, "verdict": verdict}, ensure_ascii=False),
        metadata={"verification_judgment": payload},
    )


def _verification_next_action_kind(value: str, verdict: str) -> str:
    normalized = str(value or "").strip()
    if normalized:
        return normalized
    if verdict == WorkspaceVerificationJudgeVerdict.ACCEPTED.value:
        return WorkspaceVerificationNextActionKind.NONE.value
    if verdict == WorkspaceVerificationJudgeVerdict.BLOCKED_HUMAN_REQUIRED.value:
        return WorkspaceVerificationNextActionKind.HUMAN_REQUIRED.value
    return WorkspaceVerificationNextActionKind.RETRY_SAME_NODE.value


def _verification_feedback_items(
    items: list[Any],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in items[:limit]:
        if not isinstance(raw, dict):
            continue
        target_layer = str(raw.get("target_layer") or "").strip()
        feedback_kind = str(raw.get("feedback_kind") or "").strip()
        severity = str(raw.get("severity") or "").strip()
        recommended_action = str(raw.get("recommended_action") or "").strip()
        if target_layer not in _VALID_VERIFICATION_FEEDBACK_TARGET_LAYERS:
            continue
        if feedback_kind not in _VALID_VERIFICATION_FEEDBACK_KINDS:
            continue
        if severity not in _VALID_VERIFICATION_FEEDBACK_SEVERITIES:
            continue
        if recommended_action not in _VALID_VERIFICATION_RECOMMENDED_ACTIONS:
            continue
        payload: dict[str, Any] = {
            "target_layer": target_layer,
            "feedback_kind": feedback_kind,
            "severity": severity,
            "recommended_action": recommended_action,
        }
        summary = str(raw.get("summary") or "").strip()
        if summary:
            payload["summary"] = summary[:1200]
        evidence_refs = _string_list(raw.get("evidence_refs") or [], limit=12)
        if evidence_refs:
            payload["evidence_refs"] = evidence_refs
        failure_signature = str(raw.get("failure_signature") or "").strip()
        if failure_signature:
            payload["failure_signature"] = failure_signature[:300]
        normalized.append(payload)
    return normalized


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
        return _deny(
            error, selected_agent_id=runtime_context_string(ctx, "selected_agent_id") or None
        )
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


@tool_define(
    name=WORKSPACE_SUBMIT_SUPERVISOR_DECISION_TOOL_NAME,
    description=(
        "Terminal workspace supervisor tool. The builtin workspace supervisor decision "
        "agent calls this exactly once to choose the durable plan tick's next action."
    ),
    parameters=WORKSPACE_SUPERVISOR_DECISION_TOOL_PARAMETERS,
    permission=None,
    category="workspace",
)
async def workspace_submit_supervisor_decision_tool(
    ctx: ToolContext,
    *,
    action: str,
    rationale: str,
    confidence: float,
    feedback_items: list[dict[str, Any]] | None = None,
    retry_not_before_seconds: int | None = None,
    repair_brief: dict[str, Any] | None = None,
    event_payload: dict[str, Any] | None = None,
) -> ToolResult:
    error = _require_builtin_agent(
        ctx,
        expected_agent_id=BUILTIN_WORKSPACE_SUPERVISOR_ID,
        tool_name=WORKSPACE_SUBMIT_SUPERVISOR_DECISION_TOOL_NAME,
    )
    if error:
        return _deny(
            error, selected_agent_id=runtime_context_string(ctx, "selected_agent_id") or None
        )
    if action not in _VALID_SUPERVISOR_ACTIONS:
        return _deny(f"invalid supervisor action: {action}")
    rationale_clean = str(rationale or "").strip()
    if not rationale_clean:
        return _deny("rationale cannot be empty")
    confidence_value = _confidence_in_range(confidence)
    if confidence_value is None:
        return _deny("confidence must be a number in [0,1]")
    payload: dict[str, Any] = {
        "action": action,
        "rationale": rationale_clean,
        "confidence": confidence_value,
        "feedback_items": _bounded_dict_list(feedback_items or [], limit=8),
    }
    if retry_not_before_seconds is not None:
        payload["retry_not_before_seconds"] = max(0, int(retry_not_before_seconds))
    if isinstance(repair_brief, dict) and repair_brief:
        payload["repair_brief"] = _bounded_jsonable(repair_brief)
    if isinstance(event_payload, dict) and event_payload:
        payload["event_payload"] = _bounded_jsonable(event_payload)
    return ToolResult(
        output=json.dumps({"captured": True, "action": action}, ensure_ascii=False),
        metadata={"supervisor_decision": payload},
    )


@tool_define(
    name=WORKSPACE_SUBMIT_WORKTREE_PREPARATION_TOOL_NAME,
    description=(
        "Terminal workspace worktree preparation tool. The builtin worktree manager calls "
        "this exactly once after preparing or failing an isolated attempt worktree."
    ),
    parameters=WORKSPACE_WORKTREE_PREPARATION_TOOL_PARAMETERS,
    permission=None,
    category="workspace",
)
async def workspace_submit_worktree_preparation_tool(
    ctx: ToolContext,
    *,
    status: str,
    worktree_path: str,
    branch_name: str,
    base_ref: str,
    reason: str = "",
    output: str = "",
    original_base_ref: str = "",
    resolved_base_ref: str = "",
    fallback_reason: str = "",
    git_fsck_summary: str = "",
    pruned_worktrees_count: int | None = None,
) -> ToolResult:
    error = _require_builtin_agent(
        ctx,
        expected_agent_id=BUILTIN_WORKSPACE_WORKTREE_MANAGER_ID,
        tool_name=WORKSPACE_SUBMIT_WORKTREE_PREPARATION_TOOL_NAME,
    )
    if error:
        return _deny(
            error, selected_agent_id=runtime_context_string(ctx, "selected_agent_id") or None
        )
    normalized_status = str(status or "").strip()
    if normalized_status not in _VALID_WORKTREE_PREPARATION_STATUSES:
        return _deny(f"invalid worktree preparation status: {status}")
    clean_worktree_path = str(worktree_path or "").strip()
    clean_branch_name = str(branch_name or "").strip()
    clean_base_ref = str(base_ref or "").strip()
    if not clean_worktree_path or not clean_branch_name or not clean_base_ref:
        return _deny("worktree_path, branch_name, and base_ref are required")
    payload: dict[str, Any] = {
        "status": normalized_status,
        "worktree_path": clean_worktree_path,
        "branch_name": clean_branch_name,
        "base_ref": clean_base_ref,
        "reason": str(reason or "").strip()[:1200],
        "output": str(output or "").strip()[:4000],
        "original_base_ref": str(original_base_ref or "").strip(),
        "resolved_base_ref": str(resolved_base_ref or "").strip(),
        "fallback_reason": str(fallback_reason or "").strip()[:1200],
        "git_fsck_summary": str(git_fsck_summary or "").strip()[:1200],
    }
    if pruned_worktrees_count is not None:
        payload["pruned_worktrees_count"] = max(0, int(pruned_worktrees_count))
    return ToolResult(
        output=json.dumps({"captured": True, "status": normalized_status}, ensure_ascii=False),
        metadata={"worktree_preparation": payload},
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


def _bounded_dict_list(value: list[Any], *, limit: int) -> list[dict[str, Any]]:
    return [_bounded_jsonable(item) for item in value[:limit] if isinstance(item, dict)]


def _bounded_jsonable(value: Any, *, max_items: int = 20) -> Any:
    if isinstance(value, dict):
        return {
            str(key)[:128]: _bounded_jsonable(item, max_items=max_items)
            for key, item in list(value.items())[:max_items]
        }
    if isinstance(value, list):
        return [_bounded_jsonable(item, max_items=max_items) for item in value[:max_items]]
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, int | float | bool) or value is None:
        return value
    return str(value)[:4000]


def _confidence(value: object) -> float:
    if not isinstance(value, int | float | str):
        return 0.0
    try:
        parsed = float(value)
    except ValueError:
        return 0.0
    return max(0.0, min(parsed, 1.0))


def _confidence_in_range(value: object) -> float | None:
    if not isinstance(value, int | float | str):
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if not 0.0 <= parsed <= 1.0:
        return None
    return parsed


def _normalize_next_tasks(value: list[Any]) -> list[dict[str, Any]]:
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


def _normalize_findings(value: list[Any]) -> list[dict[str, Any]]:
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
    "WORKSPACE_SUBMIT_SUPERVISOR_DECISION_TOOL_NAME",
    "WORKSPACE_SUBMIT_VERIFICATION_JUDGMENT_TOOL_NAME",
    "WORKSPACE_SUBMIT_WORKTREE_PREPARATION_TOOL_NAME",
    "WORKSPACE_SUPERVISOR_DECISION_TOOL_PARAMETERS",
    "WORKSPACE_VERIFICATION_JUDGMENT_TOOL_PARAMETERS",
    "WORKSPACE_WORKTREE_PREPARATION_TOOL_PARAMETERS",
    "workspace_submit_iteration_review_tool",
    "workspace_submit_supervisor_decision_tool",
    "workspace_submit_verification_judgment_tool",
    "workspace_submit_worktree_preparation_tool",
]
