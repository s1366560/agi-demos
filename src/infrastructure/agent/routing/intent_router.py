"""
IntentRouter - LLM-driven semantic routing for SubAgents.

Uses a lightweight LLM function-calling request to analyze user intent
and route to the most appropriate SubAgent. This replaces pure keyword
matching with semantic understanding.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.llm_providers.llm_types import LLMClient


from .schemas import (
    LLMRoutingDecision,
    RoutingCandidate,
    build_routing_system_prompt,
    build_routing_tool_schema,
    parse_routing_response,
)

logger = logging.getLogger(__name__)


class IntentRouter:
    """LLM-driven intent analysis and SubAgent routing.

    Makes a single lightweight LLM call with function calling to determine
    which SubAgent best matches the user's query. Uses small/fast models
    to minimize latency and cost.

    Attributes:
        llm_client: LLM client for making routing calls.
        candidates: Pre-built list of routing candidates.
        _tool_schema: Cached function calling schema.
        _system_prompt: Cached system prompt.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        candidates: list[RoutingCandidate] | None = None,
    ) -> None:
        """Initialize IntentRouter.

        Args:
            llm_client: LLM client with generate() method.
            candidates: Pre-built routing candidates. Can be set later
                via update_candidates().
        """
        self._llm_client = llm_client
        self._candidates: list[RoutingCandidate] = candidates or []
        self._tool_schema: list[dict[str, Any]] = []
        self._system_prompt: str = ""

        if self._candidates:
            self._rebuild_cache()

    def update_candidates(self, candidates: list[RoutingCandidate]) -> None:
        """Update available routing candidates and rebuild caches.

        Args:
            candidates: New list of routing candidates.
        """
        self._candidates = candidates
        self._rebuild_cache()

    def _rebuild_cache(self) -> None:
        """Rebuild cached tool schema and system prompt."""
        self._tool_schema = build_routing_tool_schema(self._candidates)
        self._system_prompt = build_routing_system_prompt(self._candidates)

    async def route(
        self,
        query: str,
        conversation_context: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> LLMRoutingDecision:
        """Route a user query to the best SubAgent using LLM analysis.

        Args:
            query: User query to route.
            conversation_context: Optional recent conversation summary
                to help the LLM understand context.
            temperature: LLM temperature (0.0 for deterministic).
            max_tokens: Max response tokens (routing is short).

        Returns:
            LLMRoutingDecision with matched SubAgent name and confidence.
        """
        if not self._candidates:
            return LLMRoutingDecision(reasoning="No candidates configured")

        if not self._llm_client:
            return LLMRoutingDecision(reasoning="No LLM client available")

        # Build messages
        messages = [{"role": "system", "content": self._system_prompt}]

        if conversation_context:
            messages.append(
                {
                    "role": "user",
                    "content": f"Recent context:\n{conversation_context}\n\nNew query: {query}",
                }
            )
        else:
            messages.append({"role": "user", "content": query})

        try:
            response = await self._llm_client.generate(
                messages=messages,
                tools=self._tool_schema,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            decision = parse_routing_response(response)
            logger.info(
                f"[IntentRouter] LLM routing: "
                f"agent={decision.subagent_name}, "
                f"confidence={decision.confidence:.2f}, "
                f"reason={decision.reasoning[:80]}"
            )
            return decision

        except Exception as e:
            logger.warning(f"[IntentRouter] LLM routing failed: {e}")
            return LLMRoutingDecision(reasoning=f"LLM call failed: {e}")
