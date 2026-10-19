"""Structured goal judgment schema, result types and audit serialization."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.infrastructure.logging_redaction import redact_sensitive_log_text

GOAL_COMPLETION_JUDGE_TOOL_V2 = "submit_goal_completion_judgment_v2"
audit_logger = logging.getLogger("agent_decision_audit")


@dataclass
class GoalCheckResult:
    """Result of goal completion evaluation."""

    achieved: bool
    should_stop: bool = False
    reason: str = ""
    source: str = "unknown"
    pending_tasks: int = 0
    control_handoff: bool = False


@dataclass(frozen=True, kw_only=True)
class GoalJudgmentAuditV2:
    """Complete audit envelope for one structured goal-completion judgment."""

    agent_id: str
    tool_name: str
    input_json: Mapping[str, Any]
    output_json: Mapping[str, Any]
    rationale: str
    latency_ms: int


@dataclass(frozen=True, kw_only=True)
class _GoalJudgmentV2:
    achieved: bool
    rationale: str
    control_handoff: bool = False


type GoalJudgmentAuditSinkV2 = Callable[[GoalJudgmentAuditV2], None | Awaitable[None]]


NATIVE_CONTROL_HANDOFF_GUIDANCE = (
    " The authenticated native controller reports that the user explicitly stopped computer use "
    "for this run. This is normal user control, not a tool failure and not goal completion. "
    "Return control_handoff=true and goal_achieved=false only when ending this turn returns "
    "control to the user because remaining work requires the stopped desktop interaction. "
    "If other requested, authorized work remains possible, return both false and continue it. "
    "Do not use handoff to suppress genuine errors, authorization denials, or failed tasks. "
    "A stopped or cancelled task alone is never evidence the user objective was achieved."
)


def goal_completion_judgment_tool_v2(*, allow_handoff: bool = False) -> dict[str, Any]:
    tool: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": GOAL_COMPLETION_JUDGE_TOOL_V2,
            "description": "Submit one auditable judgment of whether the user goal is complete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_achieved": {"type": "boolean"},
                    "rationale": {"type": "string", "minLength": 1},
                },
                "required": ["goal_achieved", "rationale"],
                "additionalProperties": False,
            },
        },
    }
    if allow_handoff:
        parameters = tool["function"]["parameters"]
        parameters["properties"]["control_handoff"] = {"type": "boolean"}
        parameters["required"].append("control_handoff")
    return tool


def extract_goal_judgment_tool_call_v2(
    response: Mapping[str, object],
) -> dict[str, Any] | None:
    tool_calls = _object_list(response.get("tool_calls"))
    if not tool_calls:
        choices = _object_list(response.get("choices"))
        choice = _object_mapping(choices[0]) if choices else None
        message = _object_mapping(choice.get("message")) if choice else None
        tool_calls = _object_list(message.get("tool_calls")) if message else []
    if len(tool_calls) != 1:
        return None
    call = _object_mapping(tool_calls[0])
    function = _object_mapping(call.get("function")) if call else None
    if (
        call is None
        or call.get("type") != "function"
        or function is None
        or function.get("name") != GOAL_COMPLETION_JUDGE_TOOL_V2
    ):
        return None
    arguments = function.get("arguments")
    mapping = _object_mapping(arguments)
    if mapping is None and isinstance(arguments, str):
        try:
            mapping = _object_mapping(json.loads(arguments))
        except json.JSONDecodeError:
            mapping = None
    if mapping is None:
        return None
    return dict(mapping) or None


def _object_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _object_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, dict):
        return None
    if not all(isinstance(key, str) for key in value):
        return None
    return value


def log_goal_judgment_audit(audit: GoalJudgmentAuditV2) -> None:
    audit_logger.info(
        "Goal completion judgment completed",
        extra={
            "agent_id": audit.agent_id,
            "tool_name": audit.tool_name,
            "input": _redacted_audit_json(audit.input_json),
            "output": _redacted_audit_json(audit.output_json),
            "rationale": redact_sensitive_log_text(audit.rationale),
            "latency_ms": audit.latency_ms,
        },
    )


def _redacted_audit_json(value: Mapping[str, Any]) -> str:
    return redact_sensitive_log_text(
        json.dumps(dict(value), ensure_ascii=False, sort_keys=True, default=str)
    )


def build_goal_check_context(
    messages: list[dict[str, Any]],
    *,
    latest_text: str,
    plan_mode: bool,
) -> str:
    """Build compact evidence for the structured judgment without classifying prose."""
    summary_lines: list[str] = []
    if plan_mode:
        summary_lines.append(
            "Plan mode is active. Judge whether the requested planning and analysis "
            "are complete and ready for user approval. Execution tasks remain pending "
            "until approval; do not require their execution or completed statuses."
        )
    recent_messages = messages[-8:] if len(messages) > 8 else messages
    for msg in recent_messages:
        role = str(msg.get("role", "unknown"))
        content = msg.get("content", "")

        if isinstance(content, list):
            text_chunks = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_chunks.append(str(part.get("text", "")))
            content_text = " ".join(chunk for chunk in text_chunks if chunk).strip()
        elif isinstance(content, str):
            content_text = content.strip()
        else:
            content_text = str(content).strip() if content else ""

        if content_text:
            summary_lines.append(f"{role}: {content_text[:400]}")

    if latest_text:
        summary_lines.append(f"assistant_latest: {latest_text.strip()[:400]}")

    return "\n".join(summary_lines)


def parse_goal_judgment(
    output: Mapping[str, Any],
    *,
    allow_handoff: bool,
) -> _GoalJudgmentV2 | None:
    """Validate typed verdict fields; prose cannot enable native control handoff."""
    expected = {"goal_achieved", "rationale"}
    if allow_handoff:
        expected.add("control_handoff")
    achieved = output.get("goal_achieved")
    rationale = output.get("rationale")
    handoff = output.get("control_handoff", False)
    if (
        set(output) != expected
        or not isinstance(achieved, bool)
        or not isinstance(handoff, bool)
        or (achieved and handoff)
        or not isinstance(rationale, str)
        or not rationale.strip()
    ):
        return None
    return _GoalJudgmentV2(
        achieved=achieved,
        rationale=rationale.strip(),
        control_handoff=handoff,
    )
