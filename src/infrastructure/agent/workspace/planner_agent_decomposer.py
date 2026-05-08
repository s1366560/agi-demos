"""Agent-backed workspace planning decomposer."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol

from src.infrastructure.agent.sisyphus.builtin_agent import (
    BUILTIN_WORKSPACE_PLANNER_ID,
    build_builtin_workspace_planner_agent,
)
from src.infrastructure.agent.subagent.task_decomposer import DecompositionResult, SubTask
from src.infrastructure.agent.tools.define import tool_info_to_openai_format
from src.infrastructure.agent.tools.workspace_planning_contract import (
    WORKSPACE_SUBMIT_PLANNING_CONTRACT_TOOL_NAME,
    normalize_workspace_planning_contract,
    persist_workspace_planning_contract,
    workspace_submit_planning_contract_tool,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.domain.llm_providers.llm_types import LLMClient
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
                conversation_id=f"workspace-planner:{workspace_id}:{turn_id}",
                user_message=user_prompt,
                user_id=actor_user_id or "workspace-planner",
                tenant_id=self._tenant_id,
                message_id=f"workspace-planner-{turn_id}",
                conversation_context=conversation_context,
                agent_id=planner_agent.id,
            ):
                payload = _planning_contract_from_event(event)
                if payload is not None:
                    return payload
        finally:
            await agent.stop()
        return None


class WorkspacePlannerAgentDecomposer:
    """TaskDecomposerProtocol implementation backed by the builtin planner agent."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        llm_client: LLMClient,
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
        self._llm_client = llm_client
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
        if not self._llm_client:
            return self._fallback(query, "No LLM client available for builtin workspace planner")

        messages = [
            {"role": "system", "content": self._planner_agent.system_prompt},
            {
                "role": "user",
                "content": self._build_user_prompt(
                    query=query,
                    conversation_context=conversation_context,
                ),
            },
        ]
        tools = [tool_info_to_openai_format(workspace_submit_planning_contract_tool)]
        try:
            payload: dict[str, Any] | None = None
            if self._turn_runner is not None:
                payload = await self._turn_runner.run_planning_turn(
                    planner_agent=self._planner_agent,
                    user_prompt=messages[1]["content"],
                    workspace_id=self._workspace_id,
                    root_task_id=self._root_task_id,
                    actor_user_id=self._actor_user_id,
                    workspace_metadata=self._workspace_metadata,
                    root_metadata=self._root_metadata,
                )
            else:
                response = await self._generate_contract(messages=messages, tools=tools)
                args = self._parse_tool_arguments(response)
                if args is not None:
                    payload = await self._capture_contract(args)
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

    async def _generate_contract(
        self,
        *,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            return await self._llm_client.generate(
                messages=messages,
                tools=tools,
                temperature=0.0,
                max_tokens=2048,
                tool_choice={
                    "type": "function",
                    "function": {"name": WORKSPACE_SUBMIT_PLANNING_CONTRACT_TOOL_NAME},
                },
            )
        except Exception as forced_exc:
            logger.debug(
                "workspace planner forced tool_choice failed; retrying without tool_choice: %s",
                forced_exc,
            )
            return await self._llm_client.generate(
                messages=messages,
                tools=tools,
                temperature=0.0,
                max_tokens=2048,
            )

    async def _capture_contract(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = normalize_workspace_planning_contract(
            task_graph=args.get("task_graph") or {},
            delivery_cicd=args.get("delivery_cicd") or {},
            reasoning=str(args.get("reasoning") or ""),
            evidence_refs=args.get("evidence_refs") or [],
            confidence=args.get("confidence", 0),
            actor_user_id=self._actor_user_id,
        )
        if payload["delivery_cicd"].get("services"):
            payload = await persist_workspace_planning_contract(
                workspace_id=self._workspace_id,
                task_graph=args.get("task_graph") or {},
                delivery_cicd=args.get("delivery_cicd") or {},
                reasoning=str(args.get("reasoning") or ""),
                evidence_refs=args.get("evidence_refs") or [],
                confidence=args.get("confidence", 0),
                actor_user_id=self._actor_user_id,
                session=self._session,
                commit=False,
            )
        else:
            payload["metadata_written"] = False
        return payload

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
        return (
            "Plan this workspace kickoff using the builtin workspace planner contract.\n\n"
            f"Workspace ID: {self._workspace_id}\n"
            f"Root task ID: {self._root_task_id or 'none'}\n"
            f"Maximum subtasks: {self._max_subtasks}\n"
            f"Minimum subtasks when software work has separable phases: {self._min_subtasks}\n\n"
            f"Context:\n{context or 'none'}\n\n"
            f"Goal:\n{query}\n\n"
            "Call workspace_submit_planning_contract exactly once. If code evidence is "
            "insufficient for delivery services, submit the task DAG without inventing services."
        )

    def _metadata_context(self) -> str:
        return json.dumps(
            {
                "workspace_metadata": self._workspace_metadata,
                "root_metadata": self._root_metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _parse_tool_arguments(self, response: dict[str, Any]) -> dict[str, Any] | None:
        tool_calls = response.get("tool_calls", [])
        if tool_calls:
            tool_call = tool_calls[0]
            function_data = self._read_field(tool_call, "function", tool_call)
            name = self._read_field(function_data, "name", WORKSPACE_SUBMIT_PLANNING_CONTRACT_TOOL_NAME)
            if name != WORKSPACE_SUBMIT_PLANNING_CONTRACT_TOOL_NAME:
                return None
            return self._parse_arguments(self._read_field(function_data, "arguments", "{}"))
        return self._parse_json_content(response.get("content"))

    def _parse_arguments(self, args_raw: object) -> dict[str, Any] | None:
        if isinstance(args_raw, str):
            try:
                parsed = json.loads(args_raw)
            except json.JSONDecodeError:
                return None
        else:
            parsed = args_raw
        return parsed if isinstance(parsed, dict) else None

    def _parse_json_content(self, content: object) -> dict[str, Any] | None:
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
        )

    def _fallback(self, query: str, reasoning: str) -> DecompositionResult:
        return DecompositionResult(
            subtasks=(SubTask(id="t1", description=query),),
            reasoning=reasoning,
            is_decomposed=False,
        )

    def _read_field(self, source: object, key: str, default: object) -> object:
        if isinstance(source, dict):
            return source.get(key, default)
        return getattr(source, key, default)


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


def _code_context(
    workspace_metadata: Mapping[str, Any],
    root_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    for metadata in (root_metadata, workspace_metadata):
        raw = metadata.get("code_context")
        if isinstance(raw, Mapping):
            return dict(raw)
    return {}


__all__ = [
    "RuntimeWorkspacePlannerAgentTurnRunner",
    "WorkspacePlannerAgentDecomposer",
    "WorkspacePlannerAgentTurnRunner",
]
