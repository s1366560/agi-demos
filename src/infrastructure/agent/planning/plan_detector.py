"""Plan Mode detector.

Per the project's top-level Agent First rule (see AGENTS.md), the verdict
on whether a user message warrants Plan Mode is **subjective** and MUST
come from an agent tool-call, not from a keyword/regex/length heuristic.

This module retains the legacy ``PlanDetector`` and ``PlanSuggestion``
public API for backward compatibility but ``detect()`` is now a
deterministic no-op: it always returns ``should_suggest=False``. The
LLM is free to suggest planning naturally inside the ReAct loop, and
users may opt in via explicit slash-command / Plan Mode UI affordance.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanSuggestion:
    """Result of plan mode detection."""

    should_suggest: bool
    reason: str
    confidence: float  # 0.0 to 1.0


class PlanDetector:
    """Deterministic no-op plan-mode detector.

    Retained for backward compatibility. Always returns a suggestion
    with ``should_suggest=False``. See module docstring.
    """

    def __init__(self, min_confidence: float = 0.4) -> None:
        # Kept for API compatibility; unused.
        self._min_confidence = min_confidence

    def detect(self, query: str) -> PlanSuggestion:
        """Return a non-suggestion. Subjective verdict is delegated to the agent."""
        logger.debug(
            "PlanDetector.detect called (defanged); returning should_suggest=False"
        )
        return PlanSuggestion(
            should_suggest=False,
            reason="plan-mode suggestion delegated to agent",
            confidence=0.0,
        )
