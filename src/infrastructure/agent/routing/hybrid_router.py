"""
HybridRouter - Combines keyword matching with LLM semantic routing.

Fast path: Keyword exact match with high confidence skips LLM call.
Slow path: Low keyword confidence triggers LLM-based intent analysis.

This replaces the pure-keyword SubAgentRouter while maintaining
backward compatibility via the SubAgentRouterProtocol interface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol

if TYPE_CHECKING:
    from src.domain.llm_providers.llm_types import LLMClient


from src.domain.model.agent.subagent import SubAgent

from ..core.subagent_router import SubAgentMatch, SubAgentRouter
from .intent_router import IntentRouter
from .schemas import RoutingCandidate

logger = logging.getLogger(__name__)


class ExecutionConfigLike(Protocol):
    """Protocol describing ExecutionConfig fields used by HybridRouterConfig."""

    subagent_keyword_skip_threshold: float
    subagent_keyword_floor_threshold: float
    subagent_llm_min_confidence: float
    enable_subagent_routing: bool


def _safe_float(value: Any, default: float) -> float:  # noqa: ANN401
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class HybridRouterConfig:
    """Configuration for hybrid routing behavior."""

    # Keyword confidence above this skips LLM (fast path)
    keyword_skip_threshold: float = 0.85

    # Minimum keyword confidence to even consider the match
    keyword_floor_threshold: float = 0.3

    # LLM confidence below this is treated as no match
    llm_min_confidence: float = 0.6

    # Whether to enable LLM fallback routing
    enable_llm_routing: bool = True

    @classmethod
    def from_execution_config(
        cls, execution_config: Optional[ExecutionConfigLike]
    ) -> HybridRouterConfig:
        """Build HybridRouterConfig from ExecutionConfig-like object."""
        if execution_config is None:
            return cls()

        defaults = cls()
        return cls(
            keyword_skip_threshold=_safe_float(
                getattr(
                    execution_config,
                    "subagent_keyword_skip_threshold",
                    defaults.keyword_skip_threshold,
                ),
                defaults.keyword_skip_threshold,
            ),
            keyword_floor_threshold=_safe_float(
                getattr(
                    execution_config,
                    "subagent_keyword_floor_threshold",
                    defaults.keyword_floor_threshold,
                ),
                defaults.keyword_floor_threshold,
            ),
            llm_min_confidence=_safe_float(
                getattr(
                    execution_config,
                    "subagent_llm_min_confidence",
                    defaults.llm_min_confidence,
                ),
                defaults.llm_min_confidence,
            ),
            enable_llm_routing=bool(getattr(execution_config, "enable_subagent_routing", True)),
        )


class HybridRouter:
    """Hybrid keyword + LLM SubAgent router.

    Implements the same interface as SubAgentRouter so it can be
    used as a drop-in replacement in SubAgentOrchestrator.

    Routing flow:
    1. Run keyword matching (fast, no LLM cost)
    2. If keyword confidence >= keyword_skip_threshold -> return immediately
    3. If keyword confidence < keyword_floor_threshold or no match -> LLM route
    4. If keyword matched but low confidence -> LLM route to confirm/override

    This ensures:
    - Zero latency for obvious keyword matches
    - LLM semantic understanding for ambiguous queries
    - Cost control via the fast path
    """

    def __init__(
        self,
        subagents: List[SubAgent],
        llm_client: Optional[LLMClient] = None,
        config: Optional[HybridRouterConfig] = None,
        default_confidence_threshold: float = 0.5,
    ):
        """Initialize HybridRouter.

        Args:
            subagents: Available SubAgents.
            llm_client: LLM client for semantic routing (optional).
            config: Hybrid routing configuration.
            default_confidence_threshold: Default routing threshold.
        """
        self._config = config or HybridRouterConfig()
        self.default_confidence_threshold = default_confidence_threshold

        # L1: Keyword router (existing logic, always available)
        self._keyword_router = SubAgentRouter(
            subagents=subagents,
            default_confidence_threshold=default_confidence_threshold,
        )

        # L2: LLM intent router (optional, for semantic fallback)
        self._intent_router: Optional[IntentRouter] = None
        if llm_client and self._config.enable_llm_routing:
            candidates = self._build_candidates(subagents)
            self._intent_router = IntentRouter(
                llm_client=llm_client,
                candidates=candidates,
            )

        self._subagents = {s.name: s for s in subagents if s.enabled}

    @staticmethod
    def _build_candidates(subagents: List[SubAgent]) -> List[RoutingCandidate]:
        """Convert SubAgents to RoutingCandidates for the IntentRouter."""
        return [
            RoutingCandidate(
                name=s.name,
                display_name=s.display_name,
                description=s.trigger.description,
                examples=list(s.trigger.examples),
            )
            for s in subagents
            if s.enabled
        ]

    def match(
        self,
        query: str,
        confidence_threshold: Optional[float] = None,
    ) -> SubAgentMatch:
        """Synchronous keyword-only match (protocol compatibility).

        For the full hybrid flow with LLM fallback, use match_async().
        This method is kept for backward compatibility with the
        SubAgentRouterProtocol which expects synchronous match().

        Args:
            query: User query.
            confidence_threshold: Optional threshold override.

        Returns:
            SubAgentMatch from keyword matching.
        """
        return self._keyword_router.match(query, confidence_threshold)

    async def match_async(
        self,
        query: str,
        confidence_threshold: Optional[float] = None,
        conversation_context: Optional[str] = None,
    ) -> SubAgentMatch:
        """Async hybrid match: keyword fast path + LLM semantic fallback.

        Args:
            query: User query.
            confidence_threshold: Optional threshold override.
            conversation_context: Recent conversation for LLM context.

        Returns:
            SubAgentMatch with best routing decision.
        """
        threshold = confidence_threshold or self.default_confidence_threshold

        # Step 1: Keyword fast path
        keyword_result = self._keyword_router.match(query, threshold)

        if (
            keyword_result.subagent
            and keyword_result.confidence >= self._config.keyword_skip_threshold
        ):
            logger.info(
                f"[HybridRouter] Fast path: {keyword_result.subagent.name} "
                f"(confidence={keyword_result.confidence:.2f})"
            )
            return keyword_result

        # Step 2: LLM semantic routing (if available)
        if not self._intent_router:
            # No LLM available, return keyword result as-is
            return keyword_result

        try:
            llm_decision = await self._intent_router.route(
                query=query,
                conversation_context=conversation_context,
            )

            if llm_decision.matched and llm_decision.confidence >= self._config.llm_min_confidence:
                subagent = self._subagents.get(llm_decision.subagent_name or "")
                if subagent:
                    logger.info(
                        f"[HybridRouter] LLM route: {subagent.name} "
                        f"(confidence={llm_decision.confidence:.2f}, "
                        f"reason={llm_decision.reasoning[:60]})"
                    )
                    return SubAgentMatch(
                        subagent=subagent,
                        confidence=llm_decision.confidence,
                        match_reason=f"LLM routing: {llm_decision.reasoning[:100]}",
                    )

            # LLM didn't match or low confidence - check if keyword had a marginal match
            if (
                keyword_result.subagent
                and keyword_result.confidence >= self._config.keyword_floor_threshold
            ):
                logger.info(
                    f"[HybridRouter] Fallback to keyword: {keyword_result.subagent.name} "
                    f"(confidence={keyword_result.confidence:.2f})"
                )
                return keyword_result

        except Exception as e:
            logger.warning(f"[HybridRouter] LLM routing failed, using keyword: {e}")
            return keyword_result

        # No match from either path
        return SubAgentMatch(
            subagent=None,
            confidence=0.0,
            match_reason=f"No match (keyword: {keyword_result.match_reason}, "
            f"LLM: {llm_decision.reasoning[:60] if llm_decision else 'unavailable'})",
        )

    # ====================================================================
    # Delegated methods (pass through to keyword router)
    # ====================================================================

    def get_subagent(self, name: str) -> Optional[SubAgent]:
        """Get SubAgent by name."""
        return self._keyword_router.get_subagent(name)

    def list_subagents(self) -> List[SubAgent]:
        """List all enabled SubAgents."""
        return self._keyword_router.list_subagents()

    def get_subagent_config(self, subagent: SubAgent) -> Dict[str, Any]:
        """Get configuration for running a SubAgent."""
        return self._keyword_router.get_subagent_config(subagent)

    def filter_tools(
        self,
        subagent: SubAgent,
        available_tools: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Filter tools based on SubAgent permissions."""
        return self._keyword_router.filter_tools(subagent, available_tools)

    def get_or_create_explore_agent(
        self,
        tenant_id: str,
        project_id: Optional[str] = None,
    ) -> SubAgent:
        """Get or create an explore-agent for Plan Mode."""
        return self._keyword_router.get_or_create_explore_agent(tenant_id, project_id)
