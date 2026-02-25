"""Goal evaluation for session processor.

Extracted from processor.py -- evaluates whether the agent's current goal
has been completed, using task state, LLM self-check, or assistant text
heuristics.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.message import Message

logger = logging.getLogger(__name__)


@dataclass
class GoalCheckResult:
    """Result of goal completion evaluation."""

    achieved: bool
    should_stop: bool = False
    reason: str = ""
    source: str = "unknown"
    pending_tasks: int = 0


class GoalEvaluator:
    """Evaluates whether the agent's current goal is complete.

    Mostly stateless -- the only mutable dependency injected per-step is
    ``current_message`` (the assistant's latest output).  Everything else
    is provided at construction time.

    Parameters
    ----------
    llm_client:
        Optional LLM client for explicit goal self-check calls.
    tools:
        The processor's live tools dict (name -> ToolDefinition).  Only
        ``todoread`` is accessed.
    """

    def __init__(
        self,
        llm_client: Any | None,  # noqa: ANN401
        tools: dict[str, Any],
    ) -> None:
        self._llm_client = llm_client
        self._tools = tools
        self._current_message: Message | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_current_message(self, message: Message | None) -> None:
        """Update the current assistant message for text-based evaluation."""
        self._current_message = message

    async def evaluate_goal_completion(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> GoalCheckResult:
        """Evaluate whether the current goal is complete."""
        tasks = await self._load_session_tasks(session_id)
        if tasks:
            return self._evaluate_task_goal(tasks)
        return await self._evaluate_llm_goal(messages)

    async def generate_suggestions(self, messages: list[dict[str, Any]]) -> list[str] | None:
        """Generate follow-up suggestions based on conversation context.

        Returns a list of 2-3 suggestion strings, or None on failure.
        """
        if not self._llm_client:
            return None

        try:
            recent = messages[-6:] if len(messages) > 6 else messages
            context_summary: list[str] = []
            for msg in recent:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    context_summary.append(f"{role}: {content[:200]}")

            if not context_summary:
                return None

            suggestion_prompt = [
                {
                    "role": "system",
                    "content": (
                        "Based on the conversation below, generate exactly 3 short follow-up "
                        "questions or actions the user might want to take next. "
                        "Each suggestion should be concise (under 60 characters), actionable, "
                        "and contextually relevant. Return ONLY a JSON array of strings, "
                        "no other text. Example: "
                        '["Explain the error in detail", "Show me the code fix", '
                        '"Run the tests again"]'
                    ),
                },
                {
                    "role": "user",
                    "content": "\n".join(context_summary),
                },
            ]

            response = await self._llm_client.generate(
                messages=suggestion_prompt,
                temperature=0.7,
                max_tokens=200,
            )

            content = response.get("content", "")
            suggestions = json.loads(content)
            if isinstance(suggestions, list) and all(isinstance(s, str) for s in suggestions):
                return suggestions[:3]
        except Exception as e:
            logger.debug(f"Failed to generate suggestions: {e}")

        return None

    # ------------------------------------------------------------------
    # Task-based evaluation
    # ------------------------------------------------------------------

    async def _load_session_tasks(self, session_id: str) -> list[dict[str, Any]]:
        """Load tasks for the session via todoread when available."""
        todoread_tool = self._tools.get("todoread")
        if todoread_tool is None:
            return []

        try:
            raw_result = await todoread_tool.execute(session_id=session_id)
        except Exception as exc:
            logger.warning(f"[GoalEvaluator] Failed to load tasks via todoread: {exc}")
            return []

        payload: dict[str, Any]
        if isinstance(raw_result, str):
            try:
                payload = json.loads(raw_result)
            except json.JSONDecodeError as exc:
                logger.warning(f"[GoalEvaluator] Invalid todoread JSON result: {exc}")
                return []
        elif isinstance(raw_result, dict):
            payload = raw_result
        else:
            logger.warning(
                f"[GoalEvaluator] Unsupported todoread result type: {type(raw_result).__name__}"
            )
            return []

        tasks = payload.get("todos", [])
        if not isinstance(tasks, list):
            logger.warning("[GoalEvaluator] todoread payload missing list field 'todos'")
            return []

        return [t for t in tasks if isinstance(t, dict)]

    @staticmethod
    def _evaluate_task_goal(tasks: list[dict[str, Any]]) -> GoalCheckResult:
        """Evaluate completion from persisted task state."""
        pending_count = 0
        failed_count = 0

        for task in tasks:
            status = str(task.get("status", "")).strip().lower()
            if status in {"pending", "in_progress"}:
                pending_count += 1
            elif status == "failed":
                failed_count += 1
            elif status not in {"completed", "cancelled"}:
                pending_count += 1

        if pending_count > 0:
            return GoalCheckResult(
                achieved=False,
                reason=f"{pending_count} task(s) still in progress",
                source="tasks",
                pending_tasks=pending_count,
            )
        if failed_count > 0:
            return GoalCheckResult(
                achieved=False,
                should_stop=True,
                reason=f"{failed_count} task(s) failed",
                source="tasks",
            )
        return GoalCheckResult(
            achieved=True,
            reason="All tasks reached terminal success states",
            source="tasks",
        )

    # ------------------------------------------------------------------
    # LLM-based evaluation
    # ------------------------------------------------------------------

    async def _evaluate_llm_goal(self, messages: list[dict[str, Any]]) -> GoalCheckResult:
        """Evaluate completion using explicit LLM self-check in no-task mode."""
        fallback = self._evaluate_goal_from_latest_text()
        if self._llm_client is None:
            return fallback

        context_summary = self._build_goal_check_context(messages)
        if not context_summary:
            return fallback

        content = await self._call_goal_check_llm(context_summary)
        if content is None:
            return fallback

        parsed = self._extract_goal_json(content)
        if parsed is None:
            parsed = self._extract_goal_from_plain_text(content)
        if parsed is None:
            logger.debug(
                "[GoalEvaluator] Goal self-check payload not parseable, using fallback: %s",
                content[:200],
            )
            return fallback

        achieved = self._coerce_goal_achieved_bool(parsed.get("goal_achieved"))
        if achieved is None:
            logger.debug("[GoalEvaluator] Goal self-check missing boolean goal_achieved")
            return fallback

        reason = str(parsed.get("reason", "")).strip()
        return GoalCheckResult(
            achieved=achieved,
            reason=reason or ("Goal achieved" if achieved else "Goal not achieved"),
            source="llm_self_check",
        )

    async def _call_goal_check_llm(self, context_summary: str) -> str | None:
        """Call LLM for goal check and return content string, or None on failure."""
        try:
            response = await self._llm_client.generate(  # type: ignore[union-attr]
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a strict completion checker. "
                            "Return ONLY JSON object: "
                            '{"goal_achieved": boolean, "reason": string}. '
                            "Use goal_achieved=true only when user objective is fully satisfied."
                        ),
                    },
                    {"role": "user", "content": context_summary},
                ],
                temperature=0.0,
                max_tokens=120,
            )
        except Exception as exc:
            logger.warning(f"[GoalEvaluator] LLM goal self-check failed: {exc}")
            return None

        if isinstance(response, dict):
            return str(response.get("content", "") or "")
        if isinstance(response, str):
            return response
        return str(response)

    # ------------------------------------------------------------------
    # Text-based fallback evaluation
    # ------------------------------------------------------------------

    def _evaluate_goal_from_latest_text(self) -> GoalCheckResult:
        """Fallback goal check from latest assistant text."""
        if not self._current_message:
            return GoalCheckResult(
                achieved=False,
                reason="No assistant output available for goal check",
                source="assistant_text",
            )

        full_text = self._current_message.get_full_text().strip()
        if not full_text:
            return GoalCheckResult(
                achieved=False,
                reason="Assistant output is empty",
                source="assistant_text",
            )

        parsed = self._extract_goal_json(full_text)
        if parsed and isinstance(parsed.get("goal_achieved"), bool):
            achieved = bool(parsed["goal_achieved"])
            reason = str(parsed.get("reason", "")).strip()
            return GoalCheckResult(
                achieved=achieved,
                reason=reason or ("Goal achieved" if achieved else "Goal not achieved"),
                source="assistant_text",
            )

        if self._has_explicit_completion_phrase(full_text):
            return GoalCheckResult(
                achieved=True,
                reason="Assistant declared completion in final response",
                source="assistant_text",
            )

        return GoalCheckResult(
            achieved=False,
            reason="No explicit goal_achieved signal in assistant response",
            source="assistant_text",
        )

    def _build_goal_check_context(self, messages: list[dict[str, Any]]) -> str:
        """Build a compact context summary for goal self-check."""
        summary_lines: list[str] = []
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

        if self._current_message:
            latest_text = self._current_message.get_full_text().strip()
            if latest_text:
                summary_lines.append(f"assistant_latest: {latest_text[:400]}")

        return "\n".join(summary_lines)

    # ------------------------------------------------------------------
    # JSON / text parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_goal_achieved_bool(value: Any) -> bool | None:  # noqa: ANN401
        """Coerce a goal_achieved value to bool, or return None if not possible."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "1"}:
                return True
            if lowered in {"false", "no", "0"}:
                return False
        return None

    def _extract_goal_from_plain_text(self, text: str) -> dict[str, Any] | None:
        """Parse non-JSON goal-check payloads from plain text."""
        normalized = text.strip()
        if not normalized:
            return None
        normalized = normalized[:2000]

        bool_match = re.search(
            r"\bgoal[_\s-]*achieved\b\s*[:=]\s*(true|false|yes|no|1|0)\b",
            normalized,
            flags=re.IGNORECASE,
        )
        if bool_match:
            bool_token = bool_match.group(1).strip().lower()
            achieved = bool_token in {"true", "yes", "1"}
            reason_match = re.search(
                r"\breason\b\s*[:=]\s*([^\n\r]{1,500})",
                normalized,
                flags=re.IGNORECASE,
            )
            reason = reason_match.group(1).strip() if reason_match else normalized[:200]
            return {"goal_achieved": achieved, "reason": reason}

        lowered = normalized.lower()
        if "goal not achieved" in lowered or "goal is not achieved" in lowered:
            return {"goal_achieved": False, "reason": normalized[:200]}
        if ("goal achieved" in lowered or "goal is achieved" in lowered) and not re.search(
            r"\b(not|still|remaining|in progress|incomplete|partial)\b",
            lowered,
        ):
            return {"goal_achieved": True, "reason": normalized[:200]}
        return None

    @staticmethod
    def _find_json_object_end(text: str, start_idx: int) -> int | None:
        """Find the end index (inclusive) of a balanced JSON object.

        Scans from start_idx (which must be a '{') tracking brace depth
        and string escaping. Returns the index of the closing '}' or None.
        """
        depth = 0
        in_string = False
        escape_next = False
        for index in range(start_idx, len(text)):
            char = text[index]

            if in_string:
                if escape_next:
                    escape_next = False
                elif char == "\\":
                    escape_next = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index
        return None

    @staticmethod
    def _try_parse_json_dict(text: str) -> dict[str, Any] | None:
        """Try to parse text as a JSON dict. Returns dict or None."""
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
        return None

    def _extract_goal_json(self, text: str) -> dict[str, Any] | None:
        """Extract goal-check JSON object from model text."""
        stripped = text.strip()
        if not stripped:
            return None

        result = self._try_parse_json_dict(stripped)
        if result is not None:
            return result

        start_idx = stripped.find("{")
        while start_idx >= 0:
            end_idx = self._find_json_object_end(stripped, start_idx)
            if end_idx is not None:
                candidate = stripped[start_idx : end_idx + 1]
                result = self._try_parse_json_dict(candidate)
                if result is not None:
                    return result
            start_idx = stripped.find("{", start_idx + 1)

        return None

    @staticmethod
    def _has_explicit_completion_phrase(text: str) -> bool:
        """Conservative completion phrase detection."""
        lowered = text.strip().lower()
        if not lowered:
            return False

        positive_patterns = (
            r"\bgoal\s+achieved\b",
            r"\btask\s+completed\b",
            r"\ball\s+tasks?\s+(?:are\s+)?done\b",
            r"\bwork\s+(?:is\s+)?complete\b",
            r"\bsuccessfully\s+completed\b",
        )
        negative_patterns = (
            r"\bnot\s+(?:yet\s+)?done\b",
            r"\bnot\s+(?:yet\s+)?complete\b",
            r"\bstill\s+working\b",
            r"\bin\s+progress\b",
            r"\bremaining\b",
        )

        has_positive = any(re.search(pattern, lowered) for pattern in positive_patterns)
        has_negative = any(re.search(pattern, lowered) for pattern in negative_patterns)
        return has_positive and not has_negative
