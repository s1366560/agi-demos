"""
ResultAggregator - Aggregates results from multiple SubAgent executions.

Collects SubAgentResult instances from parallel or sequential executions
and produces a unified summary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.llm_providers.llm_types import LLMClient


from src.domain.model.agent.subagent_result import SubAgentResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AggregatedResult:
    """Aggregated result from multiple SubAgent executions.

    Attributes:
        summary: Unified summary of all results.
        results: Individual SubAgent results.
        total_tokens: Combined token usage.
        total_tool_calls: Combined tool call count.
        all_succeeded: Whether all SubAgents succeeded.
        failed_agents: Names of SubAgents that failed.
    """

    summary: str
    results: tuple
    total_tokens: int = 0
    total_tool_calls: int = 0
    all_succeeded: bool = True
    failed_agents: tuple = field(default_factory=tuple)


class ResultAggregator:
    """Aggregates multiple SubAgent results into a unified response.

    For simple cases (2-3 results), concatenates summaries with headers.
    For complex cases with an LLM client, can optionally use LLM to
    produce a coherent unified summary.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        """Initialize ResultAggregator.

        Args:
            llm_client: Optional LLM client for intelligent summarization.
        """
        self._llm_client = llm_client

    def aggregate(self, results: list[SubAgentResult]) -> AggregatedResult:
        """Aggregate multiple SubAgent results.

        Args:
            results: List of SubAgentResult from completed SubAgents.

        Returns:
            AggregatedResult with unified summary.
        """
        if not results:
            return AggregatedResult(summary="No results to aggregate.", results=())

        if len(results) == 1:
            r = results[0]
            return AggregatedResult(
                summary=r.final_content,
                results=(r,),
                total_tokens=r.tokens_used,
                total_tool_calls=r.tool_calls_count,
                all_succeeded=r.success,
                failed_agents=(r.subagent_name,) if not r.success else (),
            )

        # Multiple results - build structured summary
        sections = []
        total_tokens = 0
        total_tool_calls = 0
        failed = []

        for r in results:
            header = f"## {r.subagent_name}"
            if not r.success:
                header += " (FAILED)"
                failed.append(r.subagent_name)

            content = r.final_content or r.error or "No output"
            sections.append(f"{header}\n{content}")
            total_tokens += r.tokens_used
            total_tool_calls += r.tool_calls_count

        summary = "\n\n".join(sections)

        return AggregatedResult(
            summary=summary,
            results=tuple(results),
            total_tokens=total_tokens,
            total_tool_calls=total_tool_calls,
            all_succeeded=len(failed) == 0,
            failed_agents=tuple(failed),
        )

    async def aggregate_with_llm(self, results: list[SubAgentResult]) -> AggregatedResult:
        """Aggregate results using LLM for coherent summarization.

        Falls back to simple aggregation if LLM is unavailable.

        Args:
            results: List of SubAgentResult from completed SubAgents.

        Returns:
            AggregatedResult with LLM-generated summary.
        """
        simple = self.aggregate(results)

        if not self._llm_client or len(results) <= 1:
            return simple

        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Combine the following sub-agent results into a single coherent response. "
                        "Preserve key details. Be concise."
                    ),
                },
                {"role": "user", "content": simple.summary},
            ]

            response = await self._llm_client.generate(
                messages=messages,
                temperature=0.3,
                max_tokens=1024,
            )

            llm_summary = response.get("content", "") or simple.summary
            return AggregatedResult(
                summary=llm_summary,
                results=simple.results,
                total_tokens=simple.total_tokens,
                total_tool_calls=simple.total_tool_calls,
                all_succeeded=simple.all_succeeded,
                failed_agents=simple.failed_agents,
            )

        except Exception as e:
            logger.warning(f"[ResultAggregator] LLM aggregation failed: {e}")
            return simple
