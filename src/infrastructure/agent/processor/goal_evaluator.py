"""Goal evaluation for session processor.

Extracted from processor.py -- evaluates whether the agent's current goal
has been completed, using task state, LLM self-check, or assistant text
heuristics.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
    SqlWorkspaceTaskRepository,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.result import ToolResult

if TYPE_CHECKING:
    from ..core.message import Message

logger = logging.getLogger(__name__)


class TaskStateUnavailableError(RuntimeError):
    """Raised when persisted task state cannot be verified for final gating."""


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
        runtime_context: dict[str, Any] | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._tools = tools
        self._current_message: Message | None = None
        self._runtime_context = dict(runtime_context or {})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_current_message(self, message: Message | None) -> None:
        """Update the current assistant message for text-based evaluation."""
        self._current_message = message

    def has_task_reader(self) -> bool:
        """Whether persisted task state can be queried via todoread."""
        return self._tools.get("todoread") is not None

    async def evaluate_goal_completion(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> GoalCheckResult:
        """Evaluate whether the current goal is complete."""
        workspace_result = await self._evaluate_workspace_goal()
        if workspace_result is not None:
            return workspace_result
        if self.has_task_reader():
            try:
                tasks = await self._load_session_tasks(session_id, strict=True)
            except TaskStateUnavailableError:
                return GoalCheckResult(
                    achieved=False,
                    should_stop=True,
                    reason="Unable to verify task completion state",
                    source="tasks",
                )
            if tasks:
                return self._evaluate_task_goal(tasks)
        return await self._evaluate_llm_goal(messages)

    async def evaluate_task_completion_gate(self, session_id: str) -> GoalCheckResult | None:
        """Evaluate only persisted task state for a final completion gate."""
        workspace_result = await self._evaluate_workspace_goal()
        if workspace_result is not None:
            return workspace_result
        if not self.has_task_reader():
            return None
        try:
            tasks = await self._load_session_tasks(session_id, strict=True)
        except TaskStateUnavailableError:
            return GoalCheckResult(
                achieved=False,
                should_stop=True,
                reason="Unable to verify task completion state",
                source="tasks",
            )
        if not tasks:
            return None
        return self._evaluate_task_goal(tasks)

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

    async def summarize_tasks(self, session_id: str) -> dict[str, int] | None:
        """Return deterministic task counts for the current session."""
        if not self.has_task_reader():
            return None
        tasks = await self._load_session_tasks(session_id, strict=False)
        if not tasks:
            return None
        return self._summarize_task_counts(tasks)

    # ------------------------------------------------------------------
    # Task-based evaluation
    # ------------------------------------------------------------------

    async def _evaluate_workspace_goal(self) -> GoalCheckResult | None:
        if self._runtime_context.get("task_authority") != "workspace":
            return None

        workspace_id = self._runtime_context.get("workspace_id")
        root_goal_task_id = self._runtime_context.get("root_goal_task_id")
        if not isinstance(workspace_id, str) or not isinstance(root_goal_task_id, str):
            marker_result = GoalCheckResult(
                achieved=False,
                should_stop=True,
                reason="Workspace task authority markers are incomplete",
                source="workspace_tasks",
            )
            return marker_result

        async with async_session_factory() as db:
            task = await SqlWorkspaceTaskRepository(db).find_by_id(root_goal_task_id)

        if task is None or task.workspace_id != workspace_id:
            return GoalCheckResult(
                achieved=False,
                should_stop=True,
                reason="Workspace root goal task not found",
                source="workspace_tasks",
            )

        remediation_status = task.metadata.get("remediation_status")
        remediation_summary = str(task.metadata.get("remediation_summary", "")).strip()

        result: GoalCheckResult
        if remediation_status == "replan_required":
            result = GoalCheckResult(
                achieved=False,
                should_stop=True,
                reason=remediation_summary or "Workspace root goal requires replanning",
                source="workspace_tasks",
            )
        elif task.status.value != "done":
            if remediation_status == "ready_for_completion":
                result = GoalCheckResult(
                    achieved=False,
                    should_stop=False,
                    reason=(
                        remediation_summary
                        or "Workspace root goal is ready for completion evidence"
                    ),
                    source="workspace_tasks",
                )
            else:
                result = GoalCheckResult(
                    achieved=False,
                    should_stop=False,
                    reason="Workspace root goal task is not complete",
                    source="workspace_tasks",
                )
        elif "goal_evidence" not in task.metadata:
            result = GoalCheckResult(
                achieved=False,
                should_stop=True,
                reason="Workspace root goal task is missing goal_evidence",
                source="workspace_tasks",
            )
        else:
            result = GoalCheckResult(
                achieved=True,
                should_stop=False,
                reason="Workspace root goal task completed with on-ledger evidence",
                source="workspace_tasks",
            )

        return result

    async def _load_session_tasks(
        self, session_id: str, *, strict: bool = False
    ) -> list[dict[str, Any]]:
        """Load tasks for the session via todoread when available."""
        todoread_tool = self._tools.get("todoread")
        if todoread_tool is None:
            return []

        try:
            raw_result = await self._execute_todoread(todoread_tool, session_id)
        except Exception as exc:
            return self._task_state_failure(
                "Failed to load tasks via todoread",
                strict,
                log_message=f"[GoalEvaluator] Failed to load tasks via todoread: {exc}",
                exc=exc,
            )

        return self._extract_tasks_from_todoread_result(raw_result, strict)

    async def _execute_todoread(self, todoread_tool: Any, session_id: str) -> Any:  # noqa: ANN401
        """Execute todoread with compatibility for ToolInfo-based tools."""
        tool_instance = getattr(todoread_tool, "_tool_instance", None)
        if isinstance(tool_instance, ToolInfo):
            ctx = ToolContext(
                session_id=session_id,
                message_id="",
                call_id=f"goal-evaluator-todoread:{session_id}",
                agent_name="goal_evaluator",
                conversation_id=session_id,
                abort_signal=asyncio.Event(),
            )
            return await tool_instance.execute(ctx)
        return await todoread_tool.execute(session_id=session_id)

    def _coerce_todoread_payload(self, raw_result: Any) -> dict[str, Any] | None:  # noqa: ANN401
        """Normalize todoread output into a JSON object payload."""
        payload: dict[str, Any] | None = None

        if isinstance(raw_result, ToolResult):
            payload = self._parse_todoread_payload_str(raw_result.output)
        elif isinstance(raw_result, dict):
            output = raw_result.get("output")
            if output is None:
                payload = raw_result
            elif isinstance(output, str):
                payload = self._parse_todoread_payload_str(output)
            else:
                logger.warning(
                    "[GoalEvaluator] Unsupported todoread dict.output type: %s",
                    type(output).__name__,
                )
        elif isinstance(raw_result, str):
            stripped = raw_result.strip()
            if stripped.startswith("Error executing tool"):
                logger.warning("[GoalEvaluator] todoread execution failed: %s", stripped)
            else:
                payload = self._parse_todoread_payload_str(stripped)
        else:
            logger.warning(
                "[GoalEvaluator] Unsupported todoread result type: %s",
                type(raw_result).__name__,
            )

        return payload

    def _extract_tasks_from_todoread_result(
        self, raw_result: Any, strict: bool  # noqa: ANN401
    ) -> list[dict[str, Any]]:
        """Extract todo items from a todoread execution result."""
        if isinstance(raw_result, ToolResult) and raw_result.is_error:
            return self._task_state_failure(
                "todoread returned an error result",
                strict,
                log_message="[GoalEvaluator] todoread returned an error ToolResult",
            )

        payload = self._coerce_todoread_payload(raw_result)
        if payload is None:
            return self._task_state_failure("Unable to parse todoread payload", strict)
        return self._extract_tasks_from_payload(payload, strict)

    def _extract_tasks_from_payload(
        self, payload: dict[str, Any], strict: bool
    ) -> list[dict[str, Any]]:
        """Validate a parsed todoread payload and return normalized tasks."""
        if payload.get("error"):
            return self._task_state_failure(
                "todoread payload reported an error",
                strict,
                log_message=f"[GoalEvaluator] todoread payload contained error: {payload['error']}",
            )
        if "todos" not in payload:
            return self._task_state_failure(
                "todoread payload missing 'todos'",
                strict,
                log_message="[GoalEvaluator] todoread payload missing field 'todos'",
            )

        tasks = payload["todos"]
        if not isinstance(tasks, list):
            return self._task_state_failure(
                "todoread payload missing list field 'todos'",
                strict,
                log_message="[GoalEvaluator] todoread payload missing list field 'todos'",
            )
        return self._normalize_todoread_tasks(tasks, strict)

    def _normalize_todoread_tasks(
        self, tasks: list[Any], strict: bool
    ) -> list[dict[str, Any]]:
        """Normalize todo entries and fail closed on malformed strict payloads."""
        normalized: list[dict[str, Any]] = []

        for index, task in enumerate(tasks):
            if not isinstance(task, dict):
                if strict:
                    return self._task_state_failure(
                        f"todoread todo[{index}] is not an object",
                        strict,
                        log_message=f"[GoalEvaluator] todoread todo[{index}] is not an object",
                    )
                continue

            task_id_raw = task.get("id")
            status_raw = task.get("status")
            task_id = task_id_raw.strip() if isinstance(task_id_raw, str) else ""
            status = status_raw.strip().lower() if isinstance(status_raw, str) else ""
            if strict and (not task_id or not status):
                return self._task_state_failure(
                    f"todoread todo[{index}] missing id/status",
                    strict,
                    log_message=f"[GoalEvaluator] todoread todo[{index}] missing id/status",
                )

            normalized_task = dict(task)
            if task_id:
                normalized_task["id"] = task_id
            if status:
                normalized_task["status"] = status
            normalized.append(normalized_task)

        return normalized

    @staticmethod
    def _task_state_failure(
        reason: str,
        strict: bool,
        *,
        log_message: str | None = None,
        exc: Exception | None = None,
    ) -> list[dict[str, Any]]:
        """Return an empty task list or fail closed for strict completion gates."""
        if log_message:
            logger.warning(log_message)
        if strict:
            raise TaskStateUnavailableError(reason) from exc
        return []

    @staticmethod
    def _parse_todoread_payload_str(raw_result: str) -> dict[str, Any] | None:
        """Parse a todoread JSON payload from string output."""
        if not raw_result:
            logger.warning("[GoalEvaluator] Empty todoread payload")
            return None
        try:
            payload = json.loads(raw_result)
        except json.JSONDecodeError as exc:
            logger.warning(f"[GoalEvaluator] Invalid todoread JSON result: {exc}")
            return None
        if not isinstance(payload, dict):
            logger.warning("[GoalEvaluator] todoread JSON payload is not an object")
            return None
        return payload

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

    @staticmethod
    def _summarize_task_counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
        """Summarize persisted tasks into stable status counters."""
        counts = {
            "total": len(tasks),
            "completed": 0,
            "pending": 0,
            "in_progress": 0,
            "failed": 0,
            "cancelled": 0,
            "other": 0,
        }
        for task in tasks:
            status = str(task.get("status", "")).strip().lower()
            if status in counts and status != "total":
                counts[status] += 1
            elif status == "done":
                counts["completed"] += 1
            else:
                counts["other"] += 1
        counts["remaining"] = (
            counts["pending"]
            + counts["in_progress"]
            + counts["failed"]
            + counts["other"]
        )
        return counts

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
