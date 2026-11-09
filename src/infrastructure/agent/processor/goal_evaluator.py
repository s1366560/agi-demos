"""Goal evaluation for session processor.

Extracted from processor.py -- evaluates whether the agent's current goal
has been completed, using authoritative task state or a structured Agent
judgment tool call.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from src.infrastructure.agent.processor.goal_judgment import (
    GOAL_COMPLETION_JUDGE_TOOL_V2,
    NATIVE_CONTROL_HANDOFF_GUIDANCE,
    GoalCheckResult as GoalCheckResult,
    GoalJudgmentAuditSinkV2,
    GoalJudgmentAuditV2,
    _GoalJudgmentV2,
    _object_list,
    build_goal_check_context,
    extract_goal_judgment_tool_call_v2,
    goal_completion_judgment_tool_v2,
    log_goal_judgment_audit,
    parse_goal_judgment,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.result import ToolControlOutcome, ToolResult
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_CONTRACT,
    WORKSPACE_ROLE_WORKER,
    WORKSPACE_SESSION_ROLE_KEY,
)
from src.infrastructure.llm.completion_finish import (
    ProviderCompletionError,
    check_completion_finish_reason,
)
from src.infrastructure.workspace_core.legacy_runtime import legacy_workspace_runtime_retired

if TYPE_CHECKING:
    from ..core.message import Message

logger = logging.getLogger(__name__)

SUGGESTION_TIMEOUT_SECONDS = 5.0


class TaskStateUnavailableError(RuntimeError):
    """Raised when persisted task state cannot be verified for final gating."""


class GoalEvaluator:
    """Evaluates whether the agent's current goal is complete.

    The processor supplies the latest assistant evidence and trusted native
    control state, resetting the latter at the start of each run.

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
        generation_parameters: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._tools = tools
        self._current_message: Message | None = None
        self._runtime_context = dict(runtime_context or {})
        self._audit_sink = audit_sink or log_goal_judgment_audit
        self._generation_parameters = generation_parameters
        self._native_control_outcome: ToolControlOutcome | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_current_message(self, message: Message | None) -> None:
        """Update the latest assistant evidence included in judgment context."""
        self._current_message = message

    def has_task_reader(self) -> bool:
        """Whether persisted task state can be queried via todoread."""
        return self._tools.get("todoread") is not None

    def set_native_control_outcome(self, outcome: ToolControlOutcome | None) -> None:
        """Bind trusted native control evidence to the current run, or reset it."""
        self._native_control_outcome = outcome if isinstance(outcome, ToolControlOutcome) else None

    async def evaluate_goal_completion(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> GoalCheckResult:
        """Evaluate whether the current goal is complete."""
        if self._runtime_context.get("effective_mode") == "plan":
            return await self._evaluate_llm_goal(messages)
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
                return await self._evaluate_loaded_task_goal(tasks, messages)
        return await self._evaluate_llm_goal(messages)

    async def _evaluate_loaded_task_goal(
        self,
        tasks: list[dict[str, Any]],
        messages: list[dict[str, Any]],
    ) -> GoalCheckResult:
        task_result = self._evaluate_task_goal(tasks)
        if self._native_control_outcome is ToolControlOutcome.USER_STOPPED:
            return await self._evaluate_llm_goal(
                messages,
                context_summary=self._build_task_goal_check_context(
                    tasks,
                    task_result,
                    messages,
                ),
            )
        return await self._evaluate_task_goal_with_llm(
            tasks,
            task_result,
            messages,
        )

    async def evaluate_task_completion_gate(
        self, session_id: str, messages: list[dict[str, Any]]
    ) -> GoalCheckResult | None:
        """Recheck persisted task evidence against the current requested scope."""
        if self._runtime_context.get("effective_mode") == "plan":
            return None
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
        return await self._evaluate_loaded_task_goal(tasks, messages)

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

            # Suggestions are optional; provider stalls must not delay run settlement.
            async with asyncio.timeout(SUGGESTION_TIMEOUT_SECONDS):
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

        legacy_workspace_runtime_retired("goal evaluator Workspace task read")

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

    async def _evaluate_task_goal_with_llm(
        self,
        tasks: list[dict[str, Any]],
        task_result: GoalCheckResult,
        messages: list[dict[str, Any]],
    ) -> GoalCheckResult:
        """Judge ordinary ledger evidence within the latest authorized user scope."""
        if self._llm_client is None:
            return self._goal_judge_unavailable_result()

        context_summary = self._build_task_goal_check_context(
            tasks,
            task_result,
            messages,
        )
        if not context_summary:
            return self._goal_judge_unavailable_result()

        judgment = await self._call_goal_check_llm(context_summary)
        if judgment is None:
            return self._goal_judge_unavailable_result()

        return GoalCheckResult(
            achieved=judgment.achieved,
            reason=judgment.rationale,
            source="llm_task_reconciliation" if judgment.achieved else "llm_self_check",
        )

    async def _evaluate_llm_goal(
        self,
        messages: list[dict[str, Any]],
        *,
        context_summary: str | None = None,
    ) -> GoalCheckResult:
        """Evaluate completion through one required structured Agent tool call."""
        if self._llm_client is None:
            return self._goal_judge_unavailable_result()

        context_summary = context_summary or self._build_goal_check_context(messages)
        if not context_summary:
            return self._goal_judge_unavailable_result()

        judgment = await self._call_goal_check_llm(context_summary)
        if judgment is None:
            return self._goal_judge_unavailable_result()
        return GoalCheckResult(
            achieved=judgment.achieved,
            control_handoff=judgment.control_handoff,
            reason=judgment.rationale,
            source="native_control_handoff" if judgment.control_handoff else "llm_self_check",
        )

    @staticmethod
    def _goal_judge_unavailable_result() -> GoalCheckResult:
        return GoalCheckResult(
            achieved=False,
            should_stop=True,
            reason="Goal completion judge unavailable or invalid",
            source="agent_judge",
        )

    async def _call_goal_check_llm(self, context_summary: str) -> _GoalJudgmentV2 | None:
        """Require and audit one structured goal-completion judgment tool call."""
        allow_handoff = self._native_control_outcome is ToolControlOutcome.USER_STOPPED
        input_json = {"context_summary": context_summary}
        if allow_handoff:
            input_json["native_control_outcome"] = ToolControlOutcome.USER_STOPPED.value
        started_at = time.perf_counter()
        generation_parameters, use_completion_tokens = self._generation_parameters_snapshot()
        # Retry only this structured judge; never ask the main Agent to repair it.
        max_tokens = 192
        expanded_budget_used = False
        for attempt in range(3):
            # Keep two normal attempts. If the second one first reveals
            # truncation, honor the one expanded attempt it requested.
            if attempt == 2 and (max_tokens != 4096 or expanded_budget_used):
                break
            expanded_budget_used = expanded_budget_used or max_tokens == 4096
            attempt_parameters = copy.deepcopy(generation_parameters)
            if use_completion_tokens:
                attempt_parameters["max_completion_tokens"] = max_tokens
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
                                + (NATIVE_CONTROL_HANDOFF_GUIDANCE if allow_handoff else "")
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(input_json, ensure_ascii=False, sort_keys=True),
                        },
                    ],
                    tools=[goal_completion_judgment_tool_v2(allow_handoff=allow_handoff)],
                    # Thinking providers may reject forced named selection. The sole
                    # declared tool and strict exact-call parser still define the verdict.
                    tool_choice="auto",
                    max_tokens=max_tokens,
                    **attempt_parameters,
                )
                self._check_response_finish_reason(response)
            except ProviderCompletionError as exc:
                logger.warning("[GoalEvaluator] Structured goal judgment rejected: %s", exc.code)
                if exc.finish_reason != "length":
                    break
                max_tokens = 4096
                continue
            except Exception as exc:
                logger.warning(
                    "[GoalEvaluator] Structured goal judgment failed with %s",
                    type(exc).__name__,
                )
                continue
            if not isinstance(response, Mapping):
                logger.warning(
                    "[GoalEvaluator] Structured goal judgment returned an invalid envelope"
                )
                continue
            output_json = extract_goal_judgment_tool_call_v2(response)
            if output_json is None:
                logger.warning(
                    "[GoalEvaluator] Structured goal judgment omitted the required tool call "
                    "(finish_reason=%s, tool_calls=%d)",
                    response.get("finish_reason")
                    if isinstance(response.get("finish_reason"), str)
                    and response.get("finish_reason")
                    in {"stop", "length", "tool_calls", "content_filter"}
                    else "other",
                    len(_object_list(response.get("tool_calls"))),
                )
                continue
            judgment = parse_goal_judgment(output_json, allow_handoff=allow_handoff)
            if judgment is None:
                logger.warning(
                    "[GoalEvaluator] Structured goal judgment returned invalid arguments"
                )
                continue
            normalized_output = {**output_json, "rationale": judgment.rationale}
            audit = GoalJudgmentAuditV2(
                agent_id=self._goal_judge_agent_id(),
                tool_name=GOAL_COMPLETION_JUDGE_TOOL_V2,
                input_json=input_json,
                output_json=normalized_output,
                rationale=judgment.rationale,
                latency_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            )
            audit_result = self._audit_sink(audit)
            if inspect.isawaitable(audit_result):
                await audit_result
            return judgment
        return None

    @staticmethod
    def _check_response_finish_reason(response: object) -> None:
        if isinstance(response, Mapping):
            check_completion_finish_reason(response.get("finish_reason"))
            if not _object_list(response.get("tool_calls")):
                choices = _object_list(response.get("choices"))
                if choices and isinstance(choices[0], Mapping):
                    check_completion_finish_reason(choices[0].get("finish_reason"))

    def _generation_parameters_snapshot(self) -> tuple[dict[str, Any], bool]:
        """Inherit current validated sampling metadata; retain the judge's protocol budget."""
        supplied = self._generation_parameters() if self._generation_parameters else {}
        options = supplied.get("provider_options", {})
        options = options if isinstance(options, Mapping) else {}
        protected = {
            "model",
            "temperature",
            "messages",
            "tools",
            "tool_choice",
            "stream",
            "stream_options",
            "max_tokens",
            "max_completion_tokens",
            "_omit_temperature",
            "_request_recorder_v2",
            "api_key",
            "api_base",
            "base_url",
            "extra_headers",
        }
        result = {
            key: copy.deepcopy(value)
            for key, value in options.items()
            if isinstance(key, str) and not key.startswith("__") and key not in protected
        }
        if supplied.get("model") is not None:
            result["model"] = supplied["model"]
        if options.get("__omit_temperature") is True:
            result["_omit_temperature"] = True
        elif supplied.get("temperature") is not None:
            result["temperature"] = supplied["temperature"]
        return result, options.get("__use_max_completion_tokens") is True

    def _goal_judge_agent_id(self) -> str:
        selected_agent_id = str(self._runtime_context.get("selected_agent_id", "")).strip()
        return selected_agent_id or "agent:goal-completion-judge"

    def _build_task_goal_check_context(
        self,
        tasks: list[dict[str, Any]],
        task_result: GoalCheckResult,
        messages: list[dict[str, Any]],
    ) -> str:
        """Provide persisted task facts without treating them as current-run scope."""
        base_context = self._build_goal_check_context(messages)
        counts = self._summarize_task_counts(tasks)
        task_examples: list[str] = []
        for task in tasks:
            status = str(task.get("status", "")).strip().lower()
            task_id = str(task.get("id", "")).strip()
            content = str(task.get("content", "")).strip()
            task_examples.append(f"- id={task_id or '<missing>'} status={status} content={content}")

        lines = [
            base_context,
            "",
            "Task ledger reconciliation:",
            f"- current_task_result: {task_result.reason}",
            f"- status_counts: {json.dumps(counts, ensure_ascii=False, sort_keys=True)}",
            "- persisted_tasks:",
            *(task_examples or ["- <none>"]),
            "",
            "Task statuses are evidence, not authorization to execute every item. Judge only "
            "the current user request and its explicit limits. Updating, restoring, inspecting, "
            "or deferring a task list does not authorize executing its pending tasks. Pending "
            "items outside the current request may remain pending when that request is complete. "
            "Return goal_achieved=true only when the current request is satisfied by the evidence. "
            "Historical completed or cancelled statuses do not prove that a new request is done. "
            "Failures relevant to the current request must not be hidden by completion or handoff. "
            "If false, identify the specific unfinished work within the current authorized scope; "
            "do not demand executing, cancelling, or falsely completing unrelated backlog items.",
        ]
        return "\n".join(lines)

    def _build_goal_check_context(self, messages: list[dict[str, Any]]) -> str:
        return build_goal_check_context(
            messages,
            latest_text=self._current_message.get_full_text() if self._current_message else "",
            plan_mode=self._runtime_context.get("effective_mode") == "plan",
        )
