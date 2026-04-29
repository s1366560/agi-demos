"""LLM-backed structured review for completed workspace plan iterations."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.domain.llm_providers.llm_types import LLMClient
from src.domain.ports.services.iteration_review_port import (
    IterationNextTask,
    IterationReviewContext,
    IterationReviewVerdict,
)

logger = logging.getLogger(__name__)

_VALID_VERDICTS = {"complete_goal", "continue_next_iteration", "needs_human_review"}
_VALID_PHASES = {"research", "plan", "implement", "test", "deploy", "review"}
_MIN_REVIEW_CONFIDENCE = 0.6


class LLMIterationReviewProvider:
    """Ask an LLM to make the subjective sprint review decision via tool call."""

    def __init__(self, llm_client: LLMClient, *, max_next_tasks: int = 6) -> None:
        super().__init__()
        self._llm_client = llm_client
        self._max_next_tasks = max(1, max_next_tasks)

    async def review(self, context: IterationReviewContext) -> IterationReviewVerdict:
        try:
            response = await self._llm_client.generate(
                messages=[
                    {"role": "system", "content": _system_prompt(self._max_next_tasks)},
                    {"role": "user", "content": _user_payload(context)},
                ],
                tools=[_review_tool_schema(self._max_next_tasks)],
                temperature=0.0,
                max_tokens=1600,
                tool_choice={
                    "type": "function",
                    "function": {"name": "review_workspace_iteration"},
                },
            )
        except Exception as forced_exc:
            logger.debug(
                "workspace iteration review forced tool call failed; retrying: %s",
                forced_exc,
            )
            try:
                response = await self._llm_client.generate(
                    messages=[
                        {"role": "system", "content": _system_prompt(self._max_next_tasks)},
                        {"role": "user", "content": _user_payload(context)},
                    ],
                    tools=[_review_tool_schema(self._max_next_tasks)],
                    temperature=0.0,
                    max_tokens=1600,
                )
            except Exception as exc:
                logger.warning("workspace iteration review failed: %s", exc)
                return _needs_human_review(f"iteration review failed: {exc}")

        return _parse_review_response(response, max_next_tasks=context.max_next_tasks)


class UnavailableIterationReviewProvider:
    """Suspends software iteration loops when the agent review surface is unavailable."""

    def __init__(self, reason: str) -> None:
        super().__init__()
        self._reason = reason

    async def review(self, context: IterationReviewContext) -> IterationReviewVerdict:
        _ = context
        return _needs_human_review(self._reason)


def _system_prompt(max_next_tasks: int) -> str:
    return (
        "You are the workspace iteration review agent. Make exactly one structured "
        "tool call named review_workspace_iteration. Decide whether the overall goal "
        "is complete, whether a bounded next sprint is needed, or whether human review "
        "is required. Do not create a full future backlog. If continuing, return at "
        f"most {max_next_tasks} next_tasks for only the next sprint. Use phases in this "
        "order when useful: research, plan, implement, test, deploy, review. If evidence "
        "is ambiguous or confidence is low, choose needs_human_review. In summary and "
        "next_sprint_goal text, refer only to the provided iteration_index; do not invent "
        "or increment iteration numbers."
    )


def _user_payload(context: IterationReviewContext) -> str:
    payload = {
        "workspace_id": context.workspace_id,
        "plan_id": context.plan_id,
        "iteration_index": context.iteration_index,
        "goal": {
            "title": context.goal_title,
            "description": context.goal_description,
        },
        "completed_tasks": list(context.completed_tasks),
        "deliverables": list(context.deliverables),
        "feedback_items": list(context.feedback_items),
        "max_next_tasks": context.max_next_tasks,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _review_tool_schema(max_next_tasks: int) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "review_workspace_iteration",
            "description": "Review a completed workspace sprint and choose the next action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": [
                            "complete_goal",
                            "continue_next_iteration",
                            "needs_human_review",
                        ],
                    },
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
                        "maxItems": max_next_tasks,
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "description": {"type": "string"},
                                "target_subagent": {"type": ["string", "null"]},
                                "dependencies": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "priority": {"type": "integer"},
                                "phase": {
                                    "type": "string",
                                    "enum": [
                                        "research",
                                        "plan",
                                        "implement",
                                        "test",
                                        "deploy",
                                        "review",
                                    ],
                                },
                                "expected_artifacts": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "maxItems": 6,
                                },
                            },
                            "required": ["id", "description"],
                        },
                    },
                },
                "required": ["verdict", "confidence", "summary"],
            },
        },
    }


def _parse_review_response(
    response: dict[str, Any], *, max_next_tasks: int
) -> IterationReviewVerdict:
    args = _response_arguments(response)
    if args is None:
        return _needs_human_review("iteration review did not return structured arguments")

    verdict = str(args.get("verdict") or "")
    if verdict not in _VALID_VERDICTS:
        return _needs_human_review("iteration review returned an invalid verdict")

    confidence = _float_between(args.get("confidence"), default=0.0)
    summary = str(args.get("summary") or "").strip()
    if confidence < _MIN_REVIEW_CONFIDENCE:
        return _needs_human_review(summary or "iteration review confidence was too low")

    tasks = _parse_next_tasks(args.get("next_tasks"), max_next_tasks=max_next_tasks)
    if verdict == "continue_next_iteration" and not tasks:
        return _needs_human_review("iteration review requested continuation without next tasks")

    return IterationReviewVerdict(
        verdict=verdict,  # type: ignore[arg-type]
        confidence=confidence,
        summary=summary or verdict,
        next_sprint_goal=str(args.get("next_sprint_goal") or "").strip(),
        feedback_items=_string_tuple(args.get("feedback_items"), limit=8),
        next_tasks=tasks,
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


def _read_field(source: object, key: str, default: object) -> object:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _parse_next_tasks(value: object, *, max_next_tasks: int) -> tuple[IterationNextTask, ...]:
    if not isinstance(value, list):
        return ()
    tasks: list[IterationNextTask] = []
    for index, item in enumerate(value[:max_next_tasks], start=1):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        phase = str(item.get("phase") or "").strip()
        tasks.append(
            IterationNextTask(
                id=str(item.get("id") or f"t{index}").strip() or f"t{index}",
                description=description,
                target_subagent=_optional_str(item.get("target_subagent")),
                dependencies=_string_tuple(item.get("dependencies"), limit=8),
                priority=max(0, int(item.get("priority") or 0)),
                phase=phase if phase in _VALID_PHASES else None,
                expected_artifacts=_string_tuple(item.get("expected_artifacts"), limit=6),
            )
        )
    return tuple(tasks)


def _string_tuple(value: object, *, limit: int) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list | tuple):
        items = [str(item) for item in value]
    else:
        return ()
    cleaned = [item.strip() for item in items if item.strip()]
    return tuple(dict.fromkeys(cleaned))[:limit]


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _float_between(value: object, *, default: float) -> float:
    if not isinstance(value, int | float | str):
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(0.0, min(parsed, 1.0))


def _needs_human_review(summary: str) -> IterationReviewVerdict:
    return IterationReviewVerdict(
        verdict="needs_human_review",
        confidence=0.0,
        summary=summary,
    )


__all__ = ["LLMIterationReviewProvider", "UnavailableIterationReviewProvider"]
