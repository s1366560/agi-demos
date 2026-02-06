"""ExecuteStep use case for multi-level thinking.

This use case handles execution of individual steps in a work plan,
including task-level thinking for each step.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.domain.llm_providers.llm_types import LLMClient
from src.domain.model.agent import PlanStatus, PlanStep, ThoughtLevel, WorkPlan

if TYPE_CHECKING:
    from src.domain.ports.agent.agent_tool_port import AgentToolBase
    from src.domain.ports.repositories.work_plan_repository import WorkPlanRepositoryPort

logger = logging.getLogger(__name__)


class ExecuteStepUseCase:
    """Use case for executing individual work plan steps."""

    def __init__(
        self,
        work_plan_repository: WorkPlanRepositoryPort,
        llm: LLMClient,
        tools: dict[str, AgentToolBase],
    ):
        """
        Initialize the use case.

        Args:
            work_plan_repository: Repository for work plan persistence
            llm: LLM for task-level thinking
            tools: Dictionary of available tools
        """
        self._work_plan_repo = work_plan_repository
        self._llm = llm
        self._tools = tools

    async def execute(
        self,
        work_plan: WorkPlan,
        conversation_context: list[dict],
    ) -> dict[str, Any]:
        """
        Execute the current step of the work plan.

        Args:
            work_plan: The work plan to execute
            conversation_context: Conversation history for context

        Returns:
            Step execution result with:
            - step_number: The executed step number
            - thought: Task-level thinking for this step
            - tool_calls: Tools called during execution
            - tool_results: Results from tool calls
            - success: Whether the step completed successfully
            - error: Error message if failed

        Raises:
            ValueError: If the work plan is complete or has no steps
        """
        current_step = work_plan.get_current_step()
        if not current_step:
            raise ValueError("Work plan has no current step to execute")

        logger.info(
            f"Executing step {current_step.step_number} "
            f"for work plan {work_plan.id}: {current_step.description[:50]}..."
        )

        # Mark plan as in progress
        if work_plan.status == PlanStatus.PLANNING:
            work_plan.mark_in_progress()
            await self._work_plan_repo.save(work_plan)

        # Generate task-level thinking
        task_thought = await self._generate_task_level_thought(
            current_step=current_step,
            conversation_context=conversation_context,
        )

        # Execute tools for this step
        tool_calls = []
        tool_results = []

        for tool_name in current_step.required_tools:
            if tool_name in self._tools:
                try:
                    # Determine tool arguments based on context
                    tool_args = self._extract_tool_args(
                        tool_name=tool_name,
                        step=current_step,
                        context=conversation_context,
                    )

                    tool_calls.append(
                        {
                            "tool": tool_name,
                            "arguments": tool_args,
                        }
                    )

                    # Execute the tool (no timeout - allow long-running tasks)
                    tool = self._tools[tool_name]
                    result = await tool.execute(**tool_args)

                    tool_results.append(
                        {
                            "tool": tool_name,
                            "result": result,
                        }
                    )

                    logger.debug(f"Tool {tool_name} executed successfully")

                except Exception as e:
                    logger.error(f"Error executing tool {tool_name}: {e}")
                    tool_results.append(
                        {
                            "tool": tool_name,
                            "error": str(e),
                        }
                    )

        success = not any("error" in tr for tr in tool_results)

        # Advance to next step if successful
        if success:
            work_plan.advance_step()
            await self._work_plan_repo.save(work_plan)

        # Check if plan is complete
        if work_plan.is_complete:
            work_plan.mark_completed()
            await self._work_plan_repo.save(work_plan)

        return {
            "step_number": current_step.step_number,
            "description": current_step.description,
            "thought": task_thought,
            "thought_level": ThoughtLevel.TASK,
            "tool_calls": tool_calls,
            "tool_results": tool_results,
            "success": success,
            "is_plan_complete": work_plan.is_complete,
        }

    async def _generate_task_level_thought(
        self,
        current_step: PlanStep,
        conversation_context: list[dict],
    ) -> str:
        """
        Generate task-level thinking for the current step.

        Args:
            current_step: The step to generate thinking for
            conversation_context: Conversation history

        Returns:
            Task-level thought as a string
        """
        context_str = "\n".join(
            f"{msg.get('role', 'user')}: {msg.get('content', '')}"
            for msg in conversation_context[-5:]  # Last 5 messages for context
        )

        prompt = f"""You are executing a specific step in a larger plan.

Step to execute:
{current_step.description}

Thought prompt for this step:
{current_step.thought_prompt}

Expected output:
{current_step.expected_output}

Recent conversation context:
{context_str}

Provide your detailed task-level thinking for how to approach this step.
Be specific about what you need to do and how you'll use the available tools.
"""

        try:
            # No timeout - allow long-running LLM calls
            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
            return response.content.strip()
        except Exception as e:
            logger.error(f"Error generating task-level thought: {e}")
            return f"I need to {current_step.description.lower()}"

    def _extract_tool_args(
        self,
        tool_name: str,
        step: PlanStep,
        context: list[dict],
    ) -> dict[str, Any]:
        """
        Extract arguments for a tool based on the step and context.

        Args:
            tool_name: Name of the tool
            step: Current step
            context: Conversation context

        Returns:
            Dictionary of tool arguments
        """
        # Get the last user message for query extraction
        last_user_msg = None
        for msg in reversed(context):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break

        # Basic argument extraction based on tool type
        if tool_name == "memory_search":
            return {
                "query": last_user_msg or step.description,
                "limit": 10,
            }
        elif tool_name == "entity_lookup":
            return {
                "entity_name": last_user_msg.split()[-1] if last_user_msg else "",
            }
        elif tool_name == "episode_retrieval":
            return {
                "query": last_user_msg or step.description,
                "limit": 5,
            }
        elif tool_name == "summary":
            return {
                "text": step.description,
            }
        elif tool_name == "graph_query":
            return {
                "query": last_user_msg or step.description,
            }
        elif tool_name == "web_search":
            return {
                "query": last_user_msg or step.description,
                "max_results": 10,
            }
        elif tool_name == "web_scrape":
            # Try to extract URL from context or step description
            import re

            url_pattern = r"https?://[^\s<>\"{}|\\^`\[\]]+"
            urls = re.findall(url_pattern, last_user_msg or step.description)
            return {
                "url": urls[0] if urls else "",
            }
        else:
            return {}
