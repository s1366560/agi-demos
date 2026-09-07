"""Goal evaluation for session processor.

Extracted from processor.py -- evaluates whether the agent's current goal
has been completed, using authoritative task state or a structured Agent
judgment tool call.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_CONTRACT,
    WORKSPACE_ROLE_WORKER,
    WORKSPACE_SESSION_ROLE_KEY,
)
from src.infrastructure.logging_redaction import redact_sensitive_log_text
from src.infrastructure.workspace_core.legacy_runtime import legacy_workspace_runtime_retired

if TYPE_CHECKING:
    from ..core.message import Message

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("agent_decision_audit")

GOAL_COMPLETION_JUDGE_TOOL_V2 = "submit_goal_completion_judgment_v2"


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


type GoalJudgmentAuditSinkV2 = Callable[[GoalJudgmentAuditV2], None | Awaitable[None]]


class GoalEvaluator:
    """Evaluates whether the agent's current goal is complete.

    Mostly stateless -- the only mutable dependency injected per-step is
    ``current_message`` (the assistant's latest output).  Everything else
    is provided at construction time.

    Parameters
    ----------
    llm_client:
        Optional LLM client for structured goal-judgment calls.
    tools:
        The processor's live tools dict (name -> ToolDefinition).  Only
        ``todoread`` is accessed.
    """

    def __init__(
        self,
        llm_client: Any | None,  # noqa: ANN401
        tools: dict[str, Any],
        runtime_context: dict[str, Any] | None = None,
        audit_sink: GoalJudgmentAuditSinkV2 | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._tools = tools
        self._current_message: Message | None = None
        self._runtime_context = dict(runtime_context or {})
        self._audit_sink = audit_sink or _log_goal_judgment_audit

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_current_message(self, message: Message | None) -> None:
        """Update the latest assistant evidence included in judgment context."""
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
                task_result = self._evaluate_task_goal(tasks)
                if task_result.achieved or task_result.should_stop:
                    return task_result
                reconciled_result = await self._evaluate_pending_task_goal_with_llm(
                    tasks,
                    task_result,
                    messages,
                )
                if reconciled_result is not None:
                    return reconciled_result
                return task_result
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

        # Worker sessions are responsible only for their own task execution;
        # skip root goal evaluation to avoid circular dependency where root
        # status blocks workers and workers can't unblock root.
        if self._runtime_context.get(WORKSPACE_SESSION_ROLE_KEY) in {
            WORKSPACE_ROLE_WORKER,
            WORKSPACE_ROLE_CONTRACT,
        }:
            return None

        workspace_id = self._runtime_context.get("workspace_id")
        root_goal_task_id = self._runtime_context.get("root_goal_task_id")
        if (
            not isinstance(workspace_id, str)
            or not workspace_id.strip()
            or not isinstance(root_goal_task_id, str)
            or not root_goal_task_id.strip()
        ):
            marker_result = GoalCheckResult(
                achieved=False,
                should_stop=True,
                reason="Workspace task authority markers are incomplete",
                source="workspace_tasks",
            )
            return marker_result

        task_repo = legacy_workspace_runtime_retired("goal evaluator Workspace task read")
        task = await task_repo.find_by_id(root_goal_task_id)
        child_tasks = await task_repo.find_by_root_goal_task_id(workspace_id, root_goal_task_id)

        if task is None or task.workspace_id != workspace_id:
            return GoalCheckResult(
                achieved=False,
                should_stop=True,
                reason="Workspace root goal task not found",
                source="workspace_tasks",
            )

        remediation_status = task.metadata.get("remediation_status")
        remediation_summary = str(task.metadata.get("remediation_summary", "")).strip()
        invalid_children = [
            child
            for child in child_tasks
            if child.archived_at is None
            and child.metadata.get("task_role") == "execution_task"
            and child.status in {WorkspaceTaskStatus.DONE, WorkspaceTaskStatus.BLOCKED}
            and (
                not isinstance(child.metadata.get("current_attempt_id"), str)
                or not child.metadata.get("current_attempt_id")
                or not isinstance(child.metadata.get("last_leader_adjudication_status"), str)
                or not child.metadata.get("last_leader_adjudication_status")
            )
        ]

        result: GoalCheckResult
        if invalid_children:
            result = GoalCheckResult(
                achieved=False,
                should_stop=True,
                reason="Workspace execution tasks are missing attempt/adjudication evidence",
                source="workspace_tasks",
            )
        elif remediation_status == "replan_required":
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
        self,
        raw_result: Any,  # noqa: ANN401
        strict: bool,
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

    def _normalize_todoread_tasks(self, tasks: list[Any], strict: bool) -> list[dict[str, Any]]:
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
            counts["pending"] + counts["in_progress"] + counts["failed"] + counts["other"]
        )
        return counts

    # ------------------------------------------------------------------
    # LLM-based evaluation
    # ------------------------------------------------------------------

    async def _evaluate_pending_task_goal_with_llm(
        self,
        tasks: list[dict[str, Any]],
        task_result: GoalCheckResult,
        messages: list[dict[str, Any]],
    ) -> GoalCheckResult | None:
        """Reconcile a pending ordinary task ledger with recent completion evidence."""
        if task_result.pending_tasks <= 0 or self._llm_client is None:
            return None

        context_summary = self._build_pending_task_goal_check_context(
            tasks,
            task_result,
            messages,
        )
        if not context_summary:
            return None

        judgment = await self._call_goal_check_llm(context_summary)
        if judgment is None:
            return None
        if not judgment.achieved:
            return None

        return GoalCheckResult(
            achieved=True,
            reason=judgment.rationale,
            source="llm_task_reconciliation",
        )

    async def _evaluate_llm_goal(self, messages: list[dict[str, Any]]) -> GoalCheckResult:
        """Evaluate completion through one required structured Agent tool call."""
        if self._llm_client is None:
            return self._goal_judge_unavailable_result()

        context_summary = self._build_goal_check_context(messages)
        if not context_summary:
            return self._goal_judge_unavailable_result()

        judgment = await self._call_goal_check_llm(context_summary)
        if judgment is None:
            return self._goal_judge_unavailable_result()
        return GoalCheckResult(
            achieved=judgment.achieved,
            reason=judgment.rationale,
            source="llm_self_check",
        )

    @staticmethod
    def _goal_judge_unavailable_result() -> GoalCheckResult:
        return GoalCheckResult(
            achieved=False,
            reason="Goal completion judge unavailable or invalid",
            source="agent_judge",
        )

    async def _call_goal_check_llm(self, context_summary: str) -> _GoalJudgmentV2 | None:
        """Require and audit one structured goal-completion judgment tool call."""
        input_json = {"context_summary": context_summary}
        started_at = time.perf_counter()
        try:
            response = await self._llm_client.generate(  # type: ignore[union-attr]
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a strict completion judge. Call "
                            f"{GOAL_COMPLETION_JUDGE_TOOL_V2} exactly once. "
                            "Use goal_achieved=true only when the user objective is fully "
                            "satisfied. Do not return a prose or JSON verdict outside the tool call."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(input_json, ensure_ascii=False, sort_keys=True),
                    },
                ],
                tools=[_goal_completion_judgment_tool_v2()],
                tool_choice={
                    "type": "function",
                    "function": {"name": GOAL_COMPLETION_JUDGE_TOOL_V2},
                },
                temperature=0.0,
                max_tokens=192,
            )
        except Exception as exc:
            logger.warning(
                "[GoalEvaluator] Structured goal judgment failed with %s",
                type(exc).__name__,
            )
            return None
        if not isinstance(response, Mapping):
            logger.warning("[GoalEvaluator] Structured goal judgment returned an invalid envelope")
            return None
        output_json = _extract_goal_judgment_tool_call_v2(response)
        if output_json is None:
            logger.warning(
                "[GoalEvaluator] Structured goal judgment omitted the required tool call"
            )
            return None
        if set(output_json) != {"goal_achieved", "rationale"}:
            logger.warning("[GoalEvaluator] Structured goal judgment returned invalid arguments")
            return None
        achieved = output_json.get("goal_achieved")
        rationale = output_json.get("rationale")
        if (
            not isinstance(achieved, bool)
            or not isinstance(rationale, str)
            or not rationale.strip()
        ):
            logger.warning("[GoalEvaluator] Structured goal judgment returned invalid arguments")
            return None
        normalized_output = {
            "goal_achieved": achieved,
            "rationale": rationale.strip(),
        }
        audit = GoalJudgmentAuditV2(
            agent_id=self._goal_judge_agent_id(),
            tool_name=GOAL_COMPLETION_JUDGE_TOOL_V2,
            input_json=input_json,
            output_json=normalized_output,
            rationale=rationale.strip(),
            latency_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
        )
        audit_result = self._audit_sink(audit)
        if inspect.isawaitable(audit_result):
            await audit_result
        return _GoalJudgmentV2(achieved=achieved, rationale=rationale.strip())

    def _goal_judge_agent_id(self) -> str:
        selected_agent_id = str(self._runtime_context.get("selected_agent_id", "")).strip()
        return selected_agent_id or "agent:goal-completion-judge"

    def _build_pending_task_goal_check_context(
        self,
        tasks: list[dict[str, Any]],
        task_result: GoalCheckResult,
        messages: list[dict[str, Any]],
    ) -> str:
        """Build context for reconciling stale ordinary task ledgers."""
        base_context = self._build_goal_check_context(messages)
        counts = self._summarize_task_counts(tasks)
        pending_examples: list[str] = []
        for task in tasks:
            status = str(task.get("status", "")).strip().lower()
            if status not in {"pending", "in_progress"}:
                continue
            task_id = str(task.get("id", "")).strip()
            content = str(task.get("content", "")).strip()
            pending_examples.append(
                f"- id={task_id or '<missing>'} status={status} content={content[:160]}"
            )
            if len(pending_examples) >= 8:
                break

        lines = [
            base_context,
            "",
            "Task ledger reconciliation:",
            f"- current_task_result: {task_result.reason}",
            f"- status_counts: {json.dumps(counts, ensure_ascii=False, sort_keys=True)}",
            "- pending_task_examples:",
            *(pending_examples or ["- <none>"]),
            "",
            "The task ledger is authoritative unless it appears stale because recent assistant "
            "messages provide concrete final deliverables or verification evidence satisfying the "
            "user objective. Return goal_achieved=true only if the user's objective is fully "
            "satisfied despite the pending task statuses. Return false when listed tasks still "
            "represent real unfinished work.",
        ]
        return "\n".join(lines)

    def _build_goal_check_context(self, messages: list[dict[str, Any]]) -> str:
        """Build a compact context summary for the structured goal judge."""
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


def _goal_completion_judgment_tool_v2() -> dict[str, Any]:
    return {
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


def _extract_goal_judgment_tool_call_v2(
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


def _log_goal_judgment_audit(audit: GoalJudgmentAuditV2) -> None:
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
