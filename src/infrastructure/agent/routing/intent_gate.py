"""Intent Gate: Lightweight pre-classification for routing decisions.

Pattern-based classifier that can short-circuit routing decisions
before entering the full ReAct loop. No LLM calls -- pure keyword
and regex matching for fast, deterministic routing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from src.infrastructure.agent.routing.execution_router import (
    ExecutionPath,
    RoutingDecision,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntentPattern:
    """A single intent classification pattern."""

    name: str
    path: ExecutionPath
    keywords: tuple[str, ...]  # ANY keyword match triggers
    confidence: float  # 0.0 to 1.0
    regex: re.Pattern[str] | None = None  # Optional regex for precise matching
    target: str | None = None  # Skill/subagent name if applicable


class IntentGate:
    """Lightweight pre-classification gate for routing decisions.

    Examines user messages using keyword and regex patterns to make
    fast routing decisions without LLM invocation. Returns None when
    no strong match is found, allowing the default routing to proceed.
    """

    def __init__(
        self,
        *,
        patterns: list[IntentPattern] | None = None,
        min_confidence: float = 0.7,
    ) -> None:
        self._patterns: tuple[IntentPattern, ...] = tuple(patterns or self._default_patterns())
        self._min_confidence = min_confidence

    @staticmethod
    def _default_patterns() -> list[IntentPattern]:
        """Built-in intent patterns."""
        return [
            # Plan mode signals -- user explicitly wants planning
            IntentPattern(
                name="explicit_plan",
                path=ExecutionPath.PLAN_MODE,
                keywords=(
                    "make a plan",
                    "create a plan",
                    "plan this",
                    "plan mode",
                    "let's plan",
                    "write a plan",
                    "design a plan",
                ),
                confidence=0.9,
            ),
            IntentPattern(
                name="complex_task",
                path=ExecutionPath.PLAN_MODE,
                keywords=(),
                confidence=0.8,
                regex=re.compile(
                    r"(?:implement|build|create|develop|design)"
                    + r"\s+(?:a\s+)?"
                    + r"(?:full|complete|entire|comprehensive)\s+",
                    re.IGNORECASE,
                ),
            ),
            # Simple Q&A -- still REACT_LOOP but with higher confidence
            IntentPattern(
                name="simple_question",
                path=ExecutionPath.REACT_LOOP,
                keywords=(),
                confidence=0.8,
                regex=re.compile(
                    r"^(?:what|who|when|where|how|why|is|are|can"
                    + r"|does|do|will|would|should)\s+.{5,80}\??$",
                    re.IGNORECASE,
                ),
            ),
            # Direct tool usage patterns -- REACT_LOOP with good confidence
            IntentPattern(
                name="direct_search",
                path=ExecutionPath.REACT_LOOP,
                keywords=(
                    "search for",
                    "find me",
                    "look up",
                    "search memory",
                    "query the",
                ),
                confidence=0.8,
            ),
            IntentPattern(
                name="direct_web",
                path=ExecutionPath.REACT_LOOP,
                keywords=(
                    "browse to",
                    "open url",
                    "scrape",
                    "fetch the page",
                    "web search",
                ),
                confidence=0.8,
            ),
        ]

    def classify(
        self,
        message: str,
        *,
        _available_skills: list[str] | None = None,
    ) -> RoutingDecision | None:
        """Classify user message intent.

        Returns a RoutingDecision if a strong match is found,
        or None if no pattern matches confidently.

        Args:
            message: The user's message text.
            _available_skills: Optional list of available skill names
                for skill-specific pattern matching.
        """
        if not message or not message.strip():
            return None

        normalized = message.strip().lower()
        best_match: IntentPattern | None = None
        best_score: float = 0.0

        for pattern in self._patterns:
            score = self._score_pattern(normalized, pattern)
            if score > best_score:
                best_score = score
                best_match = pattern

        if best_match is None or best_score < self._min_confidence:
            return None

        logger.info(
            "[IntentGate] Classified intent: pattern=%s, path=%s, confidence=%.2f",
            best_match.name,
            best_match.path.value,
            best_score,
        )
        return RoutingDecision(
            path=best_match.path,
            confidence=best_score,
            reason=f"Intent gate: {best_match.name}",
            target=best_match.target,
            metadata={
                "intent_gate": True,
                "pattern_name": best_match.name,
            },
        )

    def _score_pattern(
        self,
        normalized_message: str,
        pattern: IntentPattern,
    ) -> float:
        """Score how well a message matches a pattern."""
        keyword_match = any(kw in normalized_message for kw in pattern.keywords)
        regex_match = (
            pattern.regex is not None and pattern.regex.search(normalized_message) is not None
        )

        if keyword_match or regex_match:
            return pattern.confidence
        return 0.0
