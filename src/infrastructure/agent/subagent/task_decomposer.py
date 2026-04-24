"""
TaskDecomposer - LLM-driven task decomposition for SubAgent execution.

Analyzes complex user queries and decomposes them into executable sub-tasks.
Those tasks may be independent work items or dependent DAG phases that need to
run in prerequisite order.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.llm_providers.llm_types import LLMClient


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubTask:
    """A single decomposed sub-task for SubAgent execution.

    Attributes:
        id: Unique identifier for the sub-task.
        description: Task description for the SubAgent.
        target_subagent: Name of the recommended SubAgent (or None for auto-route).
        dependencies: List of sub-task IDs that must complete first.
        priority: Execution priority (higher = execute first).
    """

    id: str
    description: str
    target_subagent: str | None = None
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    priority: int = 0


@dataclass(frozen=True)
class DecompositionResult:
    """Result of task decomposition.

    Attributes:
        subtasks: Ordered list of sub-tasks.
        reasoning: LLM's reasoning for the decomposition.
        is_decomposed: Whether the task was actually split (False = single task).
    """

    subtasks: tuple[SubTask, ...]
    reasoning: str = ""
    is_decomposed: bool = False


def _build_decomposition_tool_schema(
    available_agents: list[str],
) -> list[dict[str, Any]]:
    """Build LLM function calling schema for task decomposition."""
    return [
        {
            "type": "function",
            "function": {
                "name": "decompose_task",
                "description": (
                    "Decompose a complex task into executable sub-tasks. "
                    "Use depends_on for prerequisite relationships so the result can "
                    "form a DAG. If the task is simple, return a single sub-task."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "subtasks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {
                                        "type": "string",
                                        "description": "Short unique ID (e.g. 't1', 't2').",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "Clear task description.",
                                    },
                                    "target_agent": {
                                        "type": "string",
                                        "enum": [*available_agents, "auto"],
                                        "description": "Best agent for this task, or 'auto'.",
                                    },
                                    "depends_on": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "IDs of tasks that must complete first.",
                                    },
                                    "priority": {
                                        "type": "integer",
                                        "description": "Priority (higher = sooner). Default 0.",
                                    },
                                },
                                "required": ["id", "description"],
                            },
                            "description": "List of sub-tasks.",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Brief explanation of the decomposition.",
                        },
                    },
                    "required": ["subtasks", "reasoning"],
                },
            },
        }
    ]


_DECOMPOSITION_SYSTEM_PROMPT = """You are a task decomposition expert. Analyze the user's request and break it down into executable sub-tasks when beneficial.

Rules:
- You must call decompose_task exactly once
- Decompose when the task has separable phases, deliverables, or verification steps
- If the request explicitly asks for a DAG, multiple child tasks, or named phases, preserve those handoff points as sub-tasks
- Software delivery tasks usually split into requirements/API contract, implementation, tests, and documentation/review when those deliverables are in scope
- Dependent phases are valid sub-tasks; represent prerequisites with depends_on
- Keep it simple: {max_subtasks} sub-tasks maximum
- If the request explicitly asks for four phases and max_subtasks allows it, return four sub-tasks
- If the task is simple or is purely sequential without separable handoff points, return a single sub-task
- Mark dependencies between tasks using depends_on
- Independent tasks with no dependencies can run in parallel

Available agents: {agents}
"""


_DECOMPOSITION_REPAIR_PROMPT = """The previous decomposition produced a single sub-task.

Re-evaluate the original task and call decompose_task exactly once:
- If the original task explicitly asks for a DAG, multiple child tasks, named phases, or separable deliverables, return a multi-node DAG up to the maximum.
- If the original task truly has no separable handoff points, return one sub-task.
- Preserve prerequisite relationships with depends_on.

Original task:
{query}

Previous reasoning:
{reasoning}

Previous subtasks:
{subtasks_json}
"""


class TaskDecomposer:
    """Decomposes complex tasks into parallelizable sub-tasks using LLM analysis.

    The decomposer makes a single LLM call to determine whether a task
    should be split and how. It is conservative by default, but it preserves
    explicit deliverable boundaries and dependency edges when the request asks
    for a DAG or names separable phases.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        available_agent_names: list[str] | None = None,
        max_subtasks: int = 4,
    ) -> None:
        """Initialize TaskDecomposer.

        Args:
            llm_client: LLM client with generate() method.
            available_agent_names: Names of available SubAgents.
            max_subtasks: Maximum number of sub-tasks to produce.
        """
        super().__init__()
        self._llm_client = llm_client
        self._agent_names = available_agent_names or []
        self._max_subtasks = max_subtasks

    def update_agents(self, agent_names: list[str]) -> None:
        """Update the list of available agent names."""
        self._agent_names = agent_names

    async def decompose(
        self,
        query: str,
        conversation_context: str | None = None,
    ) -> DecompositionResult:
        """Decompose a user query into sub-tasks.

        Args:
            query: User query to decompose.
            conversation_context: Optional recent conversation context.

        Returns:
            DecompositionResult with sub-tasks.
        """
        if not self._llm_client:
            return DecompositionResult(
                subtasks=(SubTask(id="t1", description=query),),
                reasoning="No LLM client available",
            )

        tools = _build_decomposition_tool_schema(self._agent_names)
        system_prompt = _DECOMPOSITION_SYSTEM_PROMPT.format(
            agents=", ".join(self._agent_names) if self._agent_names else "auto-detect",
            max_subtasks=self._max_subtasks,
        )

        messages = [{"role": "system", "content": system_prompt}]
        if conversation_context:
            messages.append(
                {
                    "role": "user",
                    "content": f"Context:\n{conversation_context}\n\nTask: {query}",
                }
            )
        else:
            messages.append({"role": "user", "content": query})

        try:
            response = await self._generate_decomposition(messages=messages, tools=tools)
            result = self._parse_response(response, query)
            if len(result.subtasks) <= 1 and self._max_subtasks > 1:
                repaired = await self._repair_single_task_decomposition(
                    query=query,
                    initial_result=result,
                    tools=tools,
                    system_prompt=system_prompt,
                )
                if len(repaired.subtasks) > len(result.subtasks):
                    return repaired
            return result

        except Exception as e:
            logger.warning(f"[TaskDecomposer] Decomposition failed: {e}")
            return DecompositionResult(
                subtasks=(SubTask(id="t1", description=query),),
                reasoning=f"Decomposition failed: {e}",
            )

    async def _generate_decomposition(
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
                max_tokens=1024,
                tool_choice={"type": "function", "function": {"name": "decompose_task"}},
            )
        except Exception as forced_exc:
            logger.debug(
                "[TaskDecomposer] Forced tool-choice decomposition failed; retrying without "
                "tool_choice: %s",
                forced_exc,
            )
            return await self._llm_client.generate(
                messages=messages,
                tools=tools,
                temperature=0.0,
                max_tokens=1024,
            )

    async def _repair_single_task_decomposition(
        self,
        *,
        query: str,
        initial_result: DecompositionResult,
        tools: list[dict[str, Any]],
        system_prompt: str,
    ) -> DecompositionResult:
        subtasks_json = json.dumps(
            [
                {
                    "id": subtask.id,
                    "description": subtask.description,
                    "target_agent": subtask.target_subagent or "auto",
                    "depends_on": list(subtask.dependencies),
                    "priority": subtask.priority,
                }
                for subtask in initial_result.subtasks
            ],
            ensure_ascii=False,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": _DECOMPOSITION_REPAIR_PROMPT.format(
                    query=query,
                    reasoning=initial_result.reasoning or "none",
                    subtasks_json=subtasks_json,
                ),
            },
        ]
        try:
            response = await self._generate_decomposition(messages=messages, tools=tools)
        except Exception as exc:
            logger.debug("[TaskDecomposer] Single-task repair failed: %s", exc)
            return initial_result
        repaired = self._parse_response(response, query)
        if len(repaired.subtasks) <= 1:
            return initial_result
        return repaired

    def _parse_response(self, response: dict[str, Any], original_query: str) -> DecompositionResult:
        """Parse LLM response into DecompositionResult."""
        tool_calls = response.get("tool_calls", [])
        if not tool_calls:
            content_args = self._parse_json_content(response.get("content"))
            if content_args is not None:
                return self._parse_arguments(content_args, original_query)
            return DecompositionResult(
                subtasks=(SubTask(id="t1", description=original_query),),
                reasoning="LLM did not decompose",
            )

        tool_call = tool_calls[0]
        function_data = self._read_field(tool_call, "function", tool_call)
        args_raw = self._read_field(function_data, "arguments", "{}")

        if isinstance(args_raw, str):
            try:
                args = json.loads(args_raw)
            except json.JSONDecodeError:
                return DecompositionResult(
                    subtasks=(SubTask(id="t1", description=original_query),),
                    reasoning="Failed to parse decomposition",
                )
        else:
            args = args_raw

        if not isinstance(args, dict):
            return DecompositionResult(
                subtasks=(SubTask(id="t1", description=original_query),),
                reasoning="Failed to parse decomposition",
            )

        return self._parse_arguments(args, original_query)

    def _read_field(self, source: object, key: str, default: object) -> object:
        if isinstance(source, dict):
            return source.get(key, default)
        return getattr(source, key, default)

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

    def _parse_arguments(
        self,
        args: dict[str, Any],
        original_query: str,
    ) -> DecompositionResult:
        raw_tasks = args.get("subtasks", [])
        reasoning = args.get("reasoning", "")

        if not raw_tasks:
            return DecompositionResult(
                subtasks=(SubTask(id="t1", description=original_query),),
                reasoning=reasoning or "No sub-tasks produced",
            )

        # Limit to max_subtasks
        raw_tasks = raw_tasks[: self._max_subtasks]

        subtasks = tuple(
            SubTask(
                id=t.get("id", f"t{i + 1}"),
                description=t.get("description", original_query),
                target_subagent=t.get("target_agent") if t.get("target_agent") != "auto" else None,
                dependencies=tuple(t.get("depends_on", [])),
                priority=t.get("priority", 0),
            )
            for i, t in enumerate(raw_tasks)
        )

        return DecompositionResult(
            subtasks=subtasks,
            reasoning=reasoning,
            is_decomposed=len(subtasks) > 1,
        )
