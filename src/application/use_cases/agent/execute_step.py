"""ExecuteStep use case for multi-level thinking.

This use case handles execution of individual steps,
including task-level thinking for each step.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.domain.llm_providers.llm_types import LLMClient, Message
from src.infrastructure.memory.prompt_safety import sanitize_for_context

if TYPE_CHECKING:
    from src.domain.ports.agent.agent_tool_port import AgentToolBase

logger = logging.getLogger(__name__)


class ExecuteStepUseCase:
    """Use case for executing individual steps."""

    def __init__(
        self,
        llm: LLMClient,
        tools: dict[str, AgentToolBase],
    ) -> None:
        """
        Initialize the use case.

        Args:
            llm: LLM for task-level thinking
            tools: Dictionary of available tools
        """
        self._llm = llm
        self._tools = tools

    async def execute(
        self,
        work_plan: Any,
        conversation_context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Execute the next pending step in a legacy work plan.

        The current agent runtime no longer uses this use case for primary ReAct
        execution, but the DI surface is still public. Keep it functional for
        callers that still pass old work-plan objects or persisted plan steps.
        """
        step = self._select_next_step(work_plan)
        if step is None:
            return {
                "success": False,
                "error": "Work plan has no pending steps to execute",
                "tool_results": [],
            }

        tool_name = self._string_attr(step, "tool_name")
        try:
            if tool_name:
                return await self._execute_tool_step(step, tool_name)
            return await self._execute_llm_step(work_plan, step, conversation_context)
        except Exception as exc:
            logger.exception("Error executing work plan step")
            return {
                "success": False,
                "step": self._serialize_step(step),
                "error": str(exc),
                "tool_results": [],
            }

    @staticmethod
    def _select_next_step(work_plan: Any) -> Any:
        """Return the next pending/in-progress step from a legacy work plan."""
        steps = getattr(work_plan, "steps", None)
        if steps is None and isinstance(work_plan, dict):
            steps = work_plan.get("steps")
        if not steps:
            return None

        current_index = getattr(work_plan, "current_step_index", None)
        if current_index is None and isinstance(work_plan, dict):
            current_index = work_plan.get("current_step_index")
        if isinstance(current_index, int) and 0 <= current_index < len(steps):
            return steps[current_index]

        for step in steps:
            status = ExecuteStepUseCase._string_attr(step, "status", default="pending")
            if status.lower() in {"pending", "in_progress", "running"}:
                return step
        return None

    async def _execute_tool_step(self, step: Any, tool_name: str) -> dict[str, Any]:
        """Execute a step with an explicit tool name."""
        tool = self._tools.get(tool_name)
        if tool is None:
            error = f"Tool not available: {tool_name}"
            return {
                "success": False,
                "step": self._serialize_step(step),
                "error": error,
                "tool_results": [{"tool_name": tool_name, "error": error}],
            }

        tool_input = self._dict_attr(step, "tool_input")
        if not tool_input:
            tool_input = self._dict_attr(step, "tool_parameters")

        if hasattr(tool, "safe_execute"):
            result = await tool.safe_execute(**tool_input)
        else:
            result = await tool.execute(**tool_input)

        success = not (isinstance(result, str) and result.startswith("Error:"))
        tool_result: dict[str, Any] = {"tool_name": tool_name}
        if success:
            tool_result["result"] = result
        else:
            tool_result["error"] = result

        return {
            "success": success,
            "step": self._serialize_step(step),
            "result": result if success else None,
            "error": None if success else str(result),
            "tool_results": [tool_result],
        }

    async def _execute_llm_step(
        self,
        work_plan: Any,
        step: Any,
        conversation_context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Execute a free-form reasoning step with the configured LLM."""
        description = self._string_attr(step, "description")
        context = self._format_conversation_context(conversation_context)
        plan_name = self._string_attr(work_plan, "name", default="Untitled work plan")

        system_prompt = f"""You execute one step of a larger work plan.

Work plan: {sanitize_for_context(plan_name)}
Step: {sanitize_for_context(description)}

Use the conversation context to complete only this step. Return the concrete
result for the step, including relevant caveats when information is missing.
"""
        response = await self._llm.ainvoke(
            [
                Message.system(system_prompt),
                Message.user(sanitize_for_context(context) or "No prior context provided."),
            ]
        )
        result = str(getattr(response, "content", response)).strip()
        return {
            "success": bool(result),
            "step": self._serialize_step(step),
            "result": result,
            "error": None if result else "LLM returned an empty step result",
            "tool_results": [],
        }

    @staticmethod
    def _format_conversation_context(conversation_context: list[dict[str, Any]]) -> str:
        """Format recent conversation context for an LLM step prompt."""
        parts: list[str] = []
        for message in conversation_context[-12:]:
            role = str(message.get("role") or message.get("sender") or "unknown")
            content = str(message.get("content") or message.get("text") or "")
            if content:
                parts.append(f"{role}: {content}")
        return "\n".join(parts)

    @staticmethod
    def _string_attr(item: Any, name: str, default: str = "") -> str:
        value = getattr(item, name, None)
        if value is None and isinstance(item, dict):
            value = item.get(name)
        if value is None:
            return default
        return str(getattr(value, "value", value))

    @staticmethod
    def _dict_attr(item: Any, name: str) -> dict[str, Any]:
        value = getattr(item, name, None)
        if value is None and isinstance(item, dict):
            value = item.get(name)
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _serialize_step(step: Any) -> dict[str, Any]:
        if isinstance(step, dict):
            return dict(step)
        if hasattr(step, "model_dump"):
            dumped = step.model_dump(mode="json")
            return dumped if isinstance(dumped, dict) else {"value": dumped}
        if hasattr(step, "to_dict"):
            dumped = step.to_dict()
            return dumped if isinstance(dumped, dict) else {"value": dumped}
        return {
            "description": ExecuteStepUseCase._string_attr(step, "description"),
            "tool_name": ExecuteStepUseCase._string_attr(step, "tool_name") or None,
            "status": ExecuteStepUseCase._string_attr(step, "status") or None,
        }
