"""SynthesizeResults use case for multi-level thinking.

This use case handles synthesizing results from all steps in a work plan
into a final comprehensive response.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.domain.llm_providers.llm_types import LLMClient, Message

if TYPE_CHECKING:
    from src.domain.model.agent import WorkPlan

logger = logging.getLogger(__name__)


class SynthesizeResultsUseCase:
    """Use case for synthesizing results from work plan execution."""

    def __init__(
        self,
        llm: LLMClient,
    ):
        """
        Initialize the use case.

        Args:
            llm: LLM for synthesis
        """
        self._llm = llm

    async def execute(
        self,
        work_plan: WorkPlan,
        original_query: str,
        step_results: list[dict[str, Any]],
        conversation_context: list[dict],
    ) -> str:
        """
        Synthesize results from all steps into a final response.

        Args:
            work_plan: The completed work plan
            original_query: User's original query
            step_results: Results from each step execution
            conversation_context: Full conversation context

        Returns:
            Synthesized final response

        Raises:
            ValueError: If synthesis fails
        """
        logger.info(
            f"Synthesizing results for work plan {work_plan.id} "
            f"with {len(step_results)} steps completed"
        )

        # Build synthesis context
        steps_summary = self._build_steps_summary(work_plan, step_results)

        system_prompt = f"""You are an AI assistant that synthesizes results from multiple steps into a comprehensive response.

You have just completed a multi-step process to answer the user's question.
Your task is to combine all the findings into a clear, well-structured response.

Original question: {original_query}

Steps completed:
{steps_summary}

Provide a comprehensive response that:
1. Directly answers the user's question
2. Incorporates relevant findings from each step
3. Is well-structured and easy to follow
4. Acknowledges any limitations or uncertainties

Be thorough but concise. Focus on actionable insights.
"""

        try:
            # No timeout - allow long-running LLM calls
            response = await self._llm.ainvoke(
                [
                    Message.system(system_prompt),
                    Message.user("Please provide the synthesized response."),
                ]
            )

            synthesized = response.content.strip()
            logger.info(f"Synthesis complete for work plan {work_plan.id}")

            return synthesized

        except Exception as e:
            logger.error(f"Error synthesizing results: {e}")
            # Fallback: simple concatenation of results
            return self._fallback_synthesis(work_plan, step_results)

    def _build_steps_summary(
        self,
        work_plan: WorkPlan,
        step_results: list[dict[str, Any]],
    ) -> str:
        """Build a summary of steps and their results."""
        summary_parts = []

        for i, step in enumerate(work_plan.steps):
            summary_parts.append(f"\nStep {i + 1}: {step.description}")

            if i < len(step_results):
                result = step_results[i]
                summary_parts.append(
                    f"  Status: {'Success' if result.get('success') else 'Failed'}"
                )

                # Add tool results
                tool_results = result.get("tool_results", [])
                if tool_results:
                    for tr in tool_results:
                        if "error" in tr:
                            summary_parts.append(f"  Error: {tr['error']}")
                        elif "result" in tr:
                            result_preview = str(tr["result"])[:100]
                            summary_parts.append(f"  Result: {result_preview}...")

        return "\n".join(summary_parts)

    def _fallback_synthesis(
        self,
        work_plan: WorkPlan,
        step_results: list[dict[str, Any]],
    ) -> str:
        """Fallback synthesis when LLM fails."""
        parts = ["Based on the analysis completed:"]
        parts.append("")

        for i, (step, result) in enumerate(zip(work_plan.steps, step_results)):
            parts.append(f"{i + 1}. {step.description}")
            if result.get("success"):
                tool_results = result.get("tool_results", [])
                if tool_results:
                    for tr in tool_results:
                        if "result" in tr:
                            preview = str(tr["result"])[:200]
                            parts.append(f"   Found: {preview}...")
            else:
                parts.append("   (Step encountered an error)")
            parts.append("")

        parts.append("Please let me know if you need more details on any specific aspect.")
        return "\n".join(parts)
