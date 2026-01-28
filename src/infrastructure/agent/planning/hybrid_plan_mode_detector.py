"""
Hybrid Plan Mode Detector.

This module provides the HybridPlanModeDetector class which coordinates
all three layers of the Plan Mode detection strategy:

1. Layer 1: Fast heuristic filter (reject very short queries)
2. Layer 2: Heuristic scoring with fast path (accept/reject based on thresholds)
3. Layer 3: LLM classification for ambiguous queries (with caching)

This is the main entry point for Plan Mode detection.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.infrastructure.agent.planning.fast_heuristic_detector import (
    FastHeuristicDetector,
    DetectionResult as HeuristicDetectionResult,
)
from src.infrastructure.agent.planning.llm_classifier import (
    LLMClassifier,
    ClassificationResult,
    ClassificationError,
)
from src.infrastructure.agent.planning.llm_cache import LLMResponseCache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectionResult:
    """
    Result of Plan Mode detection.

    Attributes:
        should_trigger: Whether Plan Mode should be triggered
        confidence: Confidence score (0.0 to 1.0)
        method: Detection method used ("heuristic", "llm", "cache", "disabled")
    """

    should_trigger: bool
    confidence: float
    method: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "should_trigger": self.should_trigger,
            "confidence": self.confidence,
            "method": self.method,
        }


class HybridPlanModeDetector:
    """
    Hybrid detector for Plan Mode triggering.

    Coordinates three detection layers:
    1. Layer 1: Fast heuristic filter (reject very short queries)
    2. Layer 2: Heuristic scoring (fast path for high/low scores)
    3. Layer 3: LLM classification (for ambiguous scores with caching)

    Attributes:
        heuristic_detector: FastHeuristicDetector for Layer 1 & 2
        llm_classifier: LLMClassifier for Layer 3
        cache: Optional LLMResponseCache for Layer 3
        enabled: Whether detection is enabled
        high_threshold: Score threshold for auto-accept
        low_threshold: Score threshold for auto-reject
    """

    def __init__(
        self,
        heuristic_detector: FastHeuristicDetector,
        llm_classifier: LLMClassifier,
        cache: Optional[LLMResponseCache] = None,
        enabled: bool = True,
    ) -> None:
        """
        Initialize the HybridPlanModeDetector.

        Args:
            heuristic_detector: FastHeuristicDetector instance
            llm_classifier: LLMClassifier instance
            cache: Optional cache for LLM results
            enabled: Whether detection is enabled
        """
        self.heuristic_detector = heuristic_detector
        self.llm_classifier = llm_classifier
        self.cache = cache
        self.enabled = enabled

        # Cache threshold values from heuristic detector
        self.high_threshold = getattr(
            heuristic_detector, "high_threshold", 0.8
        )
        self.low_threshold = getattr(
            heuristic_detector, "low_threshold", 0.2
        )

    async def detect(
        self,
        query: str,
        conversation_context: Optional[List[Dict[str, str]]] = None,
    ) -> DetectionResult:
        """
        Detect if Plan Mode should be triggered.

        Detection flow:
        1. If disabled, return False
        2. Layer 1: Reject very short queries
        3. Layer 2: Heuristic scoring
           - Score > high_threshold: Fast accept
           - Score < low_threshold: Fast reject
           - Otherwise: Layer 3
        4. Layer 3: LLM classification with cache

        Args:
            query: The user query to analyze
            conversation_context: Optional conversation history

        Returns:
            DetectionResult with should_trigger, confidence, and method
        """
        # Disabled: Always return False
        if not self.enabled:
            return DetectionResult(
                should_trigger=False,
                confidence=0.0,
                method="disabled",
            )

        # Layer 1 & 2: Heuristic detection
        heuristic_result = self.heuristic_detector.detect(query)
        heuristic_score = heuristic_result.confidence

        # Check if we can use heuristic fast path
        # High score: Auto-accept
        if heuristic_score >= self.high_threshold:
            return DetectionResult(
                should_trigger=True,
                confidence=heuristic_score,
                method="heuristic",
            )

        # Low score: Auto-reject
        if heuristic_score <= self.low_threshold:
            return DetectionResult(
                should_trigger=False,
                confidence=heuristic_score,
                method="heuristic",
            )

        # Layer 3: LLM classification for ambiguous scores
        return await self._llm_classify(query, conversation_context, heuristic_result)

    async def _llm_classify(
        self,
        query: str,
        conversation_context: Optional[List[Dict[str, str]]],
        heuristic_result: HeuristicDetectionResult,
    ) -> DetectionResult:
        """
        Use LLM classification for ambiguous queries.

        Args:
            query: The user query
            conversation_context: Optional conversation history
            heuristic_result: Original heuristic result for fallback

        Returns:
            DetectionResult from LLM or heuristic fallback
        """
        # Check cache first
        if self.cache:
            cached = self.cache.get(query, conversation_context)
            if cached:
                try:
                    parsed = json.loads(cached)
                    return DetectionResult(
                        should_trigger=parsed.get("should_trigger", False),
                        confidence=parsed.get("confidence", 0.5),
                        method="cache",
                    )
                except (json.JSONDecodeError, KeyError):
                    logger.warning("Failed to parse cached result")

        # Call LLM classifier
        try:
            classification = await self.llm_classifier.classify(
                query,
                conversation_context,
            )

            result = DetectionResult(
                should_trigger=classification.should_trigger,
                confidence=classification.confidence,
                method="llm",
            )

            # Cache the result
            if self.cache:
                self.cache.set(
                    query,
                    json.dumps(classification.to_dict()),
                    conversation_context,
                )

            return result

        except ClassificationError as e:
            logger.warning(f"LLM classification failed: {e}, falling back to heuristic")
            # Fall back to heuristic result
            return DetectionResult(
                should_trigger=heuristic_result.should_trigger,
                confidence=heuristic_result.confidence,
                method="heuristic",
            )
        except Exception as e:
            logger.error(f"Unexpected error during LLM classification: {e}")
            # Fall back to heuristic result
            return DetectionResult(
                should_trigger=heuristic_result.should_trigger,
                confidence=heuristic_result.confidence,
                method="heuristic",
            )
