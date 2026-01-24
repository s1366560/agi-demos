"""
Skill Executor - Executes Skills as tool compositions.

Skills encapsulate domain knowledge and tool compositions for specific task patterns.
This executor handles the execution of matched skills within the ReAct agent loop.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

from src.domain.model.agent.skill import Skill

from .events import SSEEvent, SSEEventType

logger = logging.getLogger(__name__)


@dataclass
class SkillExecutionResult:
    """Result of skill execution."""

    skill_id: str
    skill_name: str
    success: bool
    result: Any
    tool_results: List[Dict[str, Any]]
    execution_time_ms: int
    error: Optional[str] = None


class SkillExecutor:
    """
    Executes Skills as coordinated tool compositions.

    Skills define which tools to use and in what order for specific task patterns.
    The executor handles the orchestration of these tool calls.
    """

    def __init__(
        self,
        tools: Dict[str, Any],  # Tool name -> Tool definition with execute method
    ):
        """
        Initialize skill executor.

        Args:
            tools: Dictionary of available tools
        """
        self.tools = tools

    async def execute(
        self,
        skill: Skill,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[SSEEvent]:
        """
        Execute a skill by running its tool composition.

        Args:
            skill: Skill to execute
            query: User query that triggered the skill
            context: Optional execution context

        Yields:
            SSEEvent objects for real-time updates
        """
        start_time = time.time()
        context = context or {}
        tool_results = []

        # Emit skill start event
        yield SSEEvent(
            type=SSEEventType.THOUGHT,
            data={
                "content": f"Executing skill: {skill.name}",
                "thought_level": "skill",
                "skill_id": skill.id,
            },
        )

        # Execute each tool in the skill's tool list
        accumulated_context = {"query": query, **context}
        success = True
        error_msg = None

        for tool_name in skill.tools:
            if tool_name not in self.tools:
                logger.warning(f"Tool {tool_name} not found in skill {skill.name}")
                continue

            tool = self.tools[tool_name]

            # Emit tool start
            yield SSEEvent(
                type=SSEEventType.ACT,
                data={
                    "tool_name": tool_name,
                    "tool_input": accumulated_context,
                    "skill_id": skill.id,
                    "status": "running",
                },
            )

            try:
                tool_start = time.time()

                # Execute tool
                if hasattr(tool, "execute"):
                    result = tool.execute(**accumulated_context)
                    if hasattr(result, "__await__"):
                        result = await result
                elif hasattr(tool, "ainvoke"):
                    result = await tool.ainvoke(accumulated_context)
                elif hasattr(tool, "_arun"):
                    result = await tool._arun(**accumulated_context)
                elif hasattr(tool, "_run"):
                    result = tool._run(**accumulated_context)
                else:
                    result = f"Tool {tool_name} has no execute method"

                tool_end = time.time()
                duration_ms = int((tool_end - tool_start) * 1000)

                tool_results.append(
                    {
                        "tool": tool_name,
                        "result": result,
                        "success": True,
                        "duration_ms": duration_ms,
                    }
                )

                # Add result to accumulated context for next tool
                accumulated_context[f"{tool_name}_result"] = result

                # Emit tool result
                yield SSEEvent(
                    type=SSEEventType.OBSERVE,
                    data={
                        "tool_name": tool_name,
                        "result": result,
                        "duration_ms": duration_ms,
                        "status": "completed",
                    },
                )

            except Exception as e:
                logger.error(f"Tool {tool_name} execution error: {e}", exc_info=True)

                tool_results.append(
                    {
                        "tool": tool_name,
                        "error": str(e),
                        "success": False,
                    }
                )

                yield SSEEvent(
                    type=SSEEventType.OBSERVE,
                    data={
                        "tool_name": tool_name,
                        "error": str(e),
                        "status": "error",
                    },
                )

                success = False
                error_msg = f"Tool {tool_name} failed: {str(e)}"
                break

        end_time = time.time()
        execution_time_ms = int((end_time - start_time) * 1000)

        # Emit skill completion
        yield SSEEvent(
            type=SSEEventType.THOUGHT,
            data={
                "content": f"Skill {skill.name} {'completed' if success else 'failed'}",
                "thought_level": "skill_complete",
                "skill_id": skill.id,
                "success": success,
                "execution_time_ms": execution_time_ms,
            },
        )

        # Final result event with all tool outputs
        final_result = {
            "skill_id": skill.id,
            "skill_name": skill.name,
            "success": success,
            "tool_results": tool_results,
            "execution_time_ms": execution_time_ms,
        }

        if error_msg:
            final_result["error"] = error_msg

        yield SSEEvent(
            type=SSEEventType.COMPLETE,
            data=final_result,
        )

    def get_skill_tools_description(self, skill: Skill) -> str:
        """
        Get description of tools in a skill.

        Args:
            skill: Skill to describe

        Returns:
            Human-readable tool composition description
        """
        tool_descs = []
        for tool_name in skill.tools:
            if tool_name in self.tools:
                tool = self.tools[tool_name]
                desc = getattr(tool, "description", f"Tool: {tool_name}")
                tool_descs.append(f"  - {tool_name}: {desc}")

        return "\n".join(tool_descs)
