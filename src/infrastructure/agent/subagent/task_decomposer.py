"""
TaskDecomposer - LLM-driven task decomposition for parallel SubAgent execution.

Analyzes complex user queries and decomposes them into independent sub-tasks
that can be assigned to different SubAgents and executed in parallel.
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
                    "Decompose a complex task into independent sub-tasks "
                    "that can be executed in parallel by specialized agents. "
                    "If the task is simple, return a single sub-task."
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


_DECOMPOSITION_SYSTEM_PROMPT = """You are a task decomposition expert. Analyze the user's request and break it down into independent sub-tasks when beneficial.

Rules:
- Only decompose if the task has genuinely independent parts
- Keep it simple: 2-4 sub-tasks maximum
- If the task is simple or sequential, return a single sub-task
- Mark dependencies between tasks using depends_on
- Independent tasks with no dependencies can run in parallel

Available agents: {agents}
"""


class TaskDecomposer:
    """Decomposes complex tasks into parallelizable sub-tasks using LLM analysis.

    The decomposer makes a single LLM call to determine whether a task
    should be split and how. It is conservative by default - only
    decomposing when there are clearly independent sub-tasks.
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
            agents=", ".join(self._agent_names) if self._agent_names else "auto-detect"
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
            response = await self._llm_client.generate(
                messages=messages,
                tools=tools,
                temperature=0.0,
                max_tokens=512,
            )
            return self._parse_response(response, query)

        except Exception as e:
            logger.warning(f"[TaskDecomposer] Decomposition failed: {e}")
            return DecompositionResult(
                subtasks=(SubTask(id="t1", description=query),),
                reasoning=f"Decomposition failed: {e}",
            )

    def _parse_response(self, response: dict[str, Any], original_query: str) -> DecompositionResult:
        """Parse LLM response into DecompositionResult."""
        tool_calls = response.get("tool_calls", [])
        if not tool_calls:
            return DecompositionResult(
                subtasks=(SubTask(id="t1", description=original_query),),
                reasoning="LLM did not decompose",
            )

        tool_call = tool_calls[0]
        func = tool_call if isinstance(tool_call, dict) else tool_call.__dict__
        function_data = func.get("function", func)
        args_raw = function_data.get("arguments", "{}")

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
