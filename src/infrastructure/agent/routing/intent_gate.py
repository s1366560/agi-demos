"""Intent Gate: structural pre-classification for routing decisions.

Per the project's top-level Agent First rule (see AGENTS.md), subjective
routing verdicts MUST be made by an agent via a tool-call, not by a
hardcoded keyword/regex heuristic over natural language. Therefore the
default IntentGate ships with NO patterns and always returns ``None``,
allowing the LLM-driven routing in ReActAgent._decide_execution_path()
to make the decision.

The IntentPattern API is preserved so that explicit, **structural**
patterns (e.g. slash-commands like ``/plan``) can be wired in by callers
who want a deterministic short-circuit. Such patterns are objective —
they match a user-typed control sigil, not a semantic guess at intent.
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

# Hard cap on classified message length. Beyond this we truncate before
# evaluating any keyword/regex match: this bounds worst-case match time
# in the face of pathological user input combined with a custom pattern
# that has catastrophic backtracking properties.
_MAX_CLASSIFY_LEN = 4096


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

    Examines only explicit structural commands, such as slash commands.
    It does not classify natural-language intent.
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
        """Built-in intent patterns.

        Defangs prior keyword/regex-based intent classification per the
        Agent First rule. Returns an empty list so the gate never makes a
        subjective verdict on natural-language content. Callers that need
        a structural short-circuit (e.g. slash-commands) should pass
        ``patterns=[...]`` explicitly.
        """
        return []

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
        if len(normalized) > _MAX_CLASSIFY_LEN:
            normalized = normalized[:_MAX_CLASSIFY_LEN]
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
        """Score structural command matches only."""
        is_structural_message = normalized_message.startswith("/")
        if not is_structural_message:
            return 0.0

        keyword_match = any(
            _is_structural_keyword(kw) and normalized_message.startswith(kw.lower())
            for kw in pattern.keywords
        )
        regex_match = False
        if pattern.regex is not None:
            try:
                regex_match = pattern.regex.search(normalized_message) is not None
            except re.error:
                # Pattern is registered as a compiled re.Pattern, but defensive
                # coding: a custom subclass could still raise here. Treat as
                # no-match rather than letting one bad pattern poison routing.
                logger.warning(
                    "[IntentGate] regex evaluation failed for pattern %s",
                    pattern.name,
                )
                regex_match = False

        if keyword_match or regex_match:
            return pattern.confidence
        return 0.0


def _is_structural_keyword(keyword: str) -> bool:
    """Return whether *keyword* denotes an explicit control surface."""
    return keyword.strip().startswith("/")
