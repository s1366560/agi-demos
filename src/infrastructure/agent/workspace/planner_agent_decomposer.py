"""Agent-backed workspace planning decomposer."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Protocol

from src.application.services.workspace_autonomy_profiles import resolve_workspace_type
from src.infrastructure.agent.sisyphus.builtin_agent import (
    BUILTIN_WORKSPACE_PLANNER_ID,
    build_builtin_workspace_planner_agent,
)
from src.infrastructure.agent.subagent.task_decomposer import DecompositionResult, SubTask
from src.infrastructure.agent.tools.workspace_planning_contract import (
    WORKSPACE_SUBMIT_PLANNING_CONTRACT_TOOL_NAME,
    persist_workspace_planning_contract,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import PREFERRED_LANGUAGE

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.domain.model.agent.agent_definition import Agent

logger = logging.getLogger(__name__)


class WorkspacePlannerAgentTurnRunner(Protocol):
    """Runs one builtin workspace-planner turn and returns the captured contract."""

    async def run_planning_turn(
        self,
        *,
        planner_agent: Agent,
        user_prompt: str,
        workspace_id: str,
        root_task_id: str | None,
        actor_user_id: str | None,
        workspace_metadata: Mapping[str, Any],
        root_metadata: Mapping[str, Any],
        contract_only: bool = False,
    ) -> dict[str, Any] | None: ...


class RuntimeWorkspacePlannerAgentTurnRunner:
    """Run the builtin planner through the normal project ReAct runtime."""

    def __init__(
        self,
        *,
        tenant_id: str,
        project_id: str,
        max_steps: int = 12,
        max_tokens: int = 8192,
    ) -> None:
        super().__init__()
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._max_steps = max_steps
        self._max_tokens = max_tokens
        self._last_diagnostics: dict[str, Any] = {}

    @property
    def last_diagnostics(self) -> dict[str, Any]:
        return dict(self._last_diagnostics)

    async def run_planning_turn(
        self,
        *,
        planner_agent: Agent,
        user_prompt: str,
        workspace_id: str,
        root_task_id: str | None,
        actor_user_id: str | None,
        workspace_metadata: Mapping[str, Any],
        root_metadata: Mapping[str, Any],
        contract_only: bool = False,
    ) -> dict[str, Any] | None:
        from src.infrastructure.agent.core.project_react_agent import (
            ProjectAgentConfig,
            ProjectReActAgent,
        )
        from src.infrastructure.agent.workspace.runtime_role_contract import (
            WORKSPACE_ROLE_WORKER,
            WORKSPACE_SESSION_ROLE_KEY,
        )

        turn_id = uuid.uuid4().hex
        conversation_id = f"workspace-planner:{workspace_id}:{turn_id}"
        diagnostics: dict[str, Any] = {
            "conversation_id": conversation_id,
            "contract_only": contract_only,
            "event_count": 0,
            "observed_tools": [],
            "evidence_summaries": [],
            "contract_submitted": False,
        }
        agent = ProjectReActAgent(
            ProjectAgentConfig(
                tenant_id=self._tenant_id,
                project_id=self._project_id,
                agent_mode="workspace-planner",
                temperature=0.0,
                max_tokens=self._max_tokens,
                max_steps=self._max_steps,
                persistent=False,
                enable_subagents=False,
            )
        )
        if not await agent.initialize():
            return None

        conversation_context = [
            {
                "role": "system",
                "content": "workspace_worker_runtime\n"
                + json.dumps(
                    {
                        "context_type": "workspace_worker_runtime",
                        WORKSPACE_SESSION_ROLE_KEY: WORKSPACE_ROLE_WORKER,
                        "workspace_binding": {
                            "workspace_id": workspace_id,
                            "root_goal_task_id": root_task_id or "",
                        },
                        "code_context": _code_context(workspace_metadata, root_metadata),
                    },
                    ensure_ascii=False,
                ),
            }
        ]
        try:
            async for event in agent.execute_chat(
                conversation_id=conversation_id,
                user_message=user_prompt,
                user_id=actor_user_id or "workspace-planner",
                tenant_id=self._tenant_id,
                message_id=f"workspace-planner-{turn_id}",
                conversation_context=conversation_context,
                agent_id=planner_agent.id,
            ):
                diagnostics["event_count"] += 1
                tool_name = _tool_name_from_event(event)
                if tool_name:
                    observed_tools = diagnostics["observed_tools"]
                    if tool_name not in observed_tools:
                        observed_tools.append(tool_name)
                    summary = _planner_event_evidence_summary(event, tool_name=tool_name)
                    if summary and len(diagnostics["evidence_summaries"]) < 12:
                        diagnostics["evidence_summaries"].append(summary)
                payload = _planning_contract_from_event(event)
                if payload is not None:
                    diagnostics["contract_submitted"] = True
                    self._last_diagnostics = diagnostics
                    return payload
        finally:
            await agent.stop()
        self._last_diagnostics = diagnostics
        return None


class WorkspacePlannerAgentDecomposer:
    """TaskDecomposerProtocol implementation backed by the builtin planner agent."""

    def __init__(
        self,
        *,
        tenant_id: str,
        project_id: str | None,
        workspace_id: str,
        root_task_id: str | None = None,
        actor_user_id: str | None = None,
        workspace_metadata: Mapping[str, Any] | None = None,
        root_metadata: Mapping[str, Any] | None = None,
        max_subtasks: int = 8,
        min_subtasks: int = 1,
        extra_context: str | None = None,
        session: AsyncSession | None = None,
        turn_runner: WorkspacePlannerAgentTurnRunner | None = None,
    ) -> None:
        super().__init__()
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._workspace_id = workspace_id
        self._root_task_id = root_task_id
        self._actor_user_id = actor_user_id
        self._workspace_metadata = dict(workspace_metadata or {})
        self._root_metadata = dict(root_metadata or {})
        self._max_subtasks = max(1, max_subtasks)
        self._min_subtasks = max(1, min(min_subtasks, self._max_subtasks))
        self._extra_context = extra_context
        self._session = session
        self._resolved_language: str | None = None
        self._planner_agent = build_builtin_workspace_planner_agent(
            tenant_id=tenant_id,
            project_id=project_id,
        )
        self._turn_runner = turn_runner

    async def decompose(
        self,
        *,
        query: str,
        conversation_context: str | None = None,
    ) -> DecompositionResult:
        if self._turn_runner is None:
            return self._fallback(query, "No agent turn runner available for builtin workspace planner")

        await self._ensure_resolved_language()

        user_prompt = self._build_user_prompt(
            query=query,
            conversation_context=conversation_context,
        )
        try:
            payload: dict[str, Any] | None = None
            payload = await self._turn_runner.run_planning_turn(
                planner_agent=self._planner_agent,
                user_prompt=user_prompt,
                workspace_id=self._workspace_id,
                root_task_id=self._root_task_id,
                actor_user_id=self._actor_user_id,
                workspace_metadata=self._workspace_metadata,
                root_metadata=self._root_metadata,
            )
            diagnostics = [self._runner_diagnostics("initial")]
            rejection_reason = self._software_contract_rejection(payload, query)
            if rejection_reason and self._should_suspend_on_missing_contract():
                payload = await self._turn_runner.run_planning_turn(
                    planner_agent=self._contract_only_planner_agent(),
                    user_prompt=self._build_contract_repair_prompt(
                        query=query,
                        conversation_context=conversation_context,
                        diagnostics=diagnostics,
                        rejection_reason=rejection_reason,
                    ),
                    workspace_id=self._workspace_id,
                    root_task_id=self._root_task_id,
                    actor_user_id=self._actor_user_id,
                    workspace_metadata=self._workspace_metadata,
                    root_metadata=self._root_metadata,
                    contract_only=True,
                )
                diagnostics.append(self._runner_diagnostics("contract_only_retry"))
            final_rejection_reason = self._software_contract_rejection(payload, query)
            if final_rejection_reason and self._should_suspend_on_missing_contract():
                return self._suspended_contract_missing(
                    query=query,
                    reasoning=final_rejection_reason,
                    diagnostics=diagnostics,
                )
            if payload is None:
                return self._fallback(
                    query,
                    "builtin workspace planner did not submit planning contract",
                )
            if payload["delivery_cicd"].get("services") and not payload.get("metadata_written"):
                payload = await persist_workspace_planning_contract(
                    workspace_id=self._workspace_id,
                    task_graph=payload["task_graph"],
                    delivery_cicd=payload["delivery_cicd"],
                    reasoning=str(payload.get("reasoning") or ""),
                    evidence_refs=payload.get("evidence_refs") or [],
                    confidence=float(payload.get("confidence") or 0),
                    actor_user_id=self._actor_user_id,
                    session=self._session,
                    commit=False,
                )
            return self._result_from_contract(payload, query)
        except Exception as exc:
            logger.warning(
                "workspace_planner_agent_decomposer: planning contract failed",
                extra={
                    "workspace_id": self._workspace_id,
                    "root_task_id": self._root_task_id,
                    "planner_agent_id": BUILTIN_WORKSPACE_PLANNER_ID,
                },
                exc_info=True,
            )
            return self._fallback(query, f"builtin workspace planner failed: {exc}")

    def _build_user_prompt(self, *, query: str, conversation_context: str | None) -> str:
        context = "\n\n".join(
            item
            for item in (
                self._extra_context,
                conversation_context,
                self._metadata_context(),
            )
            if item
        )
        language_directive = self._language_directive()
        return (
            "Plan this workspace kickoff using the builtin workspace planner contract.\n\n"
            f"Workspace ID: {self._workspace_id}\n"
            f"Root task ID: {self._root_task_id or 'none'}\n"
            f"Maximum subtasks: {self._max_subtasks}\n"
            f"Minimum subtasks when software work has separable phases: {self._min_subtasks}\n\n"
            f"Context:\n{context or 'none'}\n\n"
            f"Goal:\n{query}\n\n"
            f"{language_directive}"
            "You are in read-only planning mode. Do not implement, edit files, mutate todos, "
            "start services, or finish in prose. Your final action must be exactly one "
            "workspace_submit_planning_contract call. If code evidence is insufficient for "
            "delivery services, submit the task DAG without inventing services."
        )

    def _build_contract_repair_prompt(
        self,
        *,
        query: str,
        conversation_context: str | None,
        diagnostics: list[dict[str, Any]],
        rejection_reason: str,
    ) -> str:
        language_directive = self._language_directive()
        return (
            "The previous builtin workspace planner turn did not produce an acceptable "
            "workspace_submit_planning_contract.\n\n"
            f"Failure reason: {rejection_reason}\n"
            f"Workspace ID: {self._workspace_id}\n"
            f"Root task ID: {self._root_task_id or 'none'}\n"
            f"Maximum subtasks: {self._max_subtasks}\n"
            f"Minimum software subtasks: {max(2, self._min_subtasks)}\n\n"
            f"Prior turn diagnostics:\n{json.dumps(diagnostics, ensure_ascii=False)}\n\n"
            f"Context:\n{conversation_context or self._extra_context or 'none'}\n\n"
            f"Workspace metadata:\n{self._metadata_context()}\n\n"
            f"Goal:\n{query}\n\n"
            f"{language_directive}"
            "Contract-only repair mode is active. You have exactly one useful tool: "
            "workspace_submit_planning_contract. Use the prior evidence summaries and "
            "workspace context above; do not invent service commands or ports. Submit a "
            "task DAG now. If services are not sufficiently evidenced, leave "
            "delivery_cicd.services empty."
        )

    def _language_directive(self) -> str:
        """Return a language instruction block, empty when no preference is set.

        Reads from the pre-resolved language (see ``_ensure_resolved_language``), which
        considers root_metadata → workspace_metadata → actor user's stored preference.
        Returns a trailing ``\n\n`` so it can be safely concatenated into prompts.
        """
        language = self._resolved_language
        if language not in {"en-US", "zh-CN"}:
            return ""
        if language == "zh-CN":
            return (
                "Language: 使用简体中文撰写本次规划中所有子任务的 title 与 description"
                "（technical_concept / evidence_refs 中的英文标识符可以保留原文）。\n\n"
            )
        return (
            "Language: write every subtask title and description in English (en-US).\n\n"
        )

    async def _ensure_resolved_language(self) -> None:
        """Resolve and cache the preferred_language for this planning run.

        Resolution order:
          1. root_metadata[PREFERRED_LANGUAGE]
          2. workspace_metadata[PREFERRED_LANGUAGE]
          3. The actor user's stored ``users.preferred_language`` (DB lookup)

        Safe to call multiple times; only the first invocation does any work.
        """
        if self._resolved_language is not None:
            return
        candidate = self._root_metadata.get(PREFERRED_LANGUAGE) or self._workspace_metadata.get(
            PREFERRED_LANGUAGE
        )
        if isinstance(candidate, str) and candidate in {"en-US", "zh-CN"}:
            self._resolved_language = candidate
            return
        # DB fallback: read the actor's stored preference.
        if self._session is None or not self._actor_user_id:
            self._resolved_language = ""  # mark as resolved-empty
            return
        try:
            from sqlalchemy import select

            from src.infrastructure.adapters.secondary.persistence.models import (
                User as DBUser,
            )

            result = await self._session.execute(
                select(DBUser.preferred_language).where(DBUser.id == self._actor_user_id)
            )
            value = result.scalar_one_or_none()
            if isinstance(value, str) and value in {"en-US", "zh-CN"}:
                self._resolved_language = value
                return
        except Exception:
            logger.debug(
                "workspace_planner_agent_decomposer: user preferred_language lookup failed",
                exc_info=True,
            )
        self._resolved_language = ""

    def _metadata_context(self) -> str:
        return json.dumps(
            {
                "workspace_metadata": self._workspace_metadata,
                "root_metadata": self._root_metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _result_from_contract(self, payload: dict[str, Any], original_query: str) -> DecompositionResult:
        raw_tasks = list(payload["task_graph"].get("subtasks") or [])[: self._max_subtasks]
        if not raw_tasks:
            return self._fallback(original_query, payload.get("reasoning") or "No subtasks produced")
        subtasks = tuple(
            SubTask(
                id=str(task.get("id") or f"t{index}"),
                description=str(task.get("description") or original_query),
                target_subagent=(
                    str(task.get("target_agent"))
                    if task.get("target_agent") and task.get("target_agent") != "auto"
                    else None
                ),
                dependencies=tuple(
                    item for item in task.get("depends_on", []) if isinstance(item, str)
                ),
                priority=int(task.get("priority") or 0),
            )
            for index, task in enumerate(raw_tasks, start=1)
        )
        return DecompositionResult(
            subtasks=subtasks,
            reasoning=str(payload.get("reasoning") or ""),
            is_decomposed=len(subtasks) > 1,
            metadata={
                "decomposition_source": "planner_agent_code_analysis",
                "planning_contract": _planning_contract_metadata(payload),
            },
        )

    def _fallback(self, query: str, reasoning: str) -> DecompositionResult:
        return DecompositionResult(
            subtasks=(SubTask(id="t1", description=query),),
            reasoning=reasoning,
            is_decomposed=False,
            metadata={"decomposition_source": "fallback_single_task"},
        )

    def _suspended_contract_missing(
        self,
        *,
        query: str,
        reasoning: str,
        diagnostics: list[dict[str, Any]],
    ) -> DecompositionResult:
        return DecompositionResult(
            subtasks=(),
            reasoning=reasoning,
            is_decomposed=False,
            metadata={
                "decomposition_source": "planner_agent_contract_missing",
                "suspend_planning": True,
                "planner_contract_missing": True,
                "failure_reason": reasoning,
                "retry_count": max(0, len(diagnostics) - 1),
                "diagnostics": diagnostics,
                "goal": query,
                "workspace_id": self._workspace_id,
                "root_task_id": self._root_task_id,
            },
        )

    def _contract_only_planner_agent(self) -> Agent:
        return replace(
            self._planner_agent,
            system_prompt=self._planner_agent.system_prompt
            + "\n\nContract-only repair mode: call workspace_submit_planning_contract now. "
            "No other terminal output is acceptable.",
            max_iterations=1,
            allowed_tools=[WORKSPACE_SUBMIT_PLANNING_CONTRACT_TOOL_NAME],
        )

    def _runner_diagnostics(self, phase: str) -> dict[str, Any]:
        getter = getattr(self._turn_runner, "last_diagnostics", None)
        diagnostics = getter if isinstance(getter, dict) else {}
        return {"phase": phase, **dict(diagnostics)}

    def _should_suspend_on_missing_contract(self) -> bool:
        workspace_type = resolve_workspace_type(self._root_metadata, self._workspace_metadata)
        return workspace_type == "software_development" and bool(
            _code_context(self._workspace_metadata, self._root_metadata)
        )

    def _software_contract_rejection(
        self,
        payload: dict[str, Any] | None,
        original_query: str,
    ) -> str | None:
        if payload is None:
            return "builtin workspace planner did not submit planning contract"
        if not self._should_suspend_on_missing_contract():
            return None
        raw_tasks = list(payload.get("task_graph", {}).get("subtasks") or [])
        if len(raw_tasks) < 2:
            return "software workspace planner contract must contain at least two subtasks"
        first_description = str(raw_tasks[0].get("description") or "")
        if _normalized_text(first_description) == _normalized_text(original_query):
            return "software workspace planner produced a root-goal duplicate subtask"
        return None


def _planning_contract_from_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    if event.get("type") != "observe":
        return None
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    if data.get("tool_name") != WORKSPACE_SUBMIT_PLANNING_CONTRACT_TOOL_NAME:
        return None
    observation = data.get("observation") or data.get("result")
    if not isinstance(observation, Mapping):
        return None
    payload = observation.get("planning_contract")
    return dict(payload) if isinstance(payload, Mapping) else None


def _tool_name_from_event(event: Mapping[str, Any]) -> str | None:
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    tool_name = data.get("tool_name") or data.get("name")
    return tool_name.strip() if isinstance(tool_name, str) and tool_name.strip() else None


def _planner_event_evidence_summary(event: Mapping[str, Any], *, tool_name: str) -> str | None:
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    observation = data.get("observation") or data.get("result")
    text = _observation_text(observation)
    if not text:
        return None
    return f"{tool_name}: {_compact(text, limit=700)}"


def _observation_text(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Mapping):
        for key in ("output", "stdout", "stderr", "content", "text"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return None


def _code_context(
    workspace_metadata: Mapping[str, Any],
    root_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    for metadata in (root_metadata, workspace_metadata):
        raw = metadata.get("code_context")
        if isinstance(raw, Mapping):
            return dict(raw)
    return {}


def _planning_contract_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task_graph": dict(payload.get("task_graph") or {}),
        "delivery_cicd": dict(payload.get("delivery_cicd") or {}),
        "reasoning": str(payload.get("reasoning") or ""),
        "evidence_refs": list(payload.get("evidence_refs") or []),
        "confidence": float(payload.get("confidence") or 0),
    }


def _normalized_text(value: str) -> str:
    return " ".join(value.split()).strip().lower()


def _compact(value: str, *, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 15] + "...[truncated]"


__all__ = [
    "RuntimeWorkspacePlannerAgentTurnRunner",
    "WorkspacePlannerAgentDecomposer",
    "WorkspacePlannerAgentTurnRunner",
]
