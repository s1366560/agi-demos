"""
Fast Heuristic Detector for Plan Mode triggering.

This module provides the FastHeuristicDetector class which uses
fast, rule-based heuristics to determine if a query should trigger
Plan Mode without calling an LLM.

The detection is based on three scoring components:
1. Length score (0 to 0.3): Longer queries are more likely to need planning
2. Keyword score (0 to 0.4): Presence of complexity-indicating keywords
3. Structural score (0 to 0.3): Multi-sentence, numbered steps, dependency markers

Total score range: 0.0 to 1.0

Detection thresholds:
- Score > high_threshold (0.8): Auto-accept (fast path)
- Score < low_threshold (0.2): Auto-reject (fast path)
- 0.2 <= Score <= 0.8: Ambiguous, requires LLM classification
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectionResult:
    """
    Result of plan mode detection.

    Attributes:
        should_trigger: Whether Plan Mode should be triggered
        confidence: Confidence score (0.0 to 1.0)
        method: Detection method used ("heuristic", "llm", "cache")
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


class FastHeuristicDetector:
    """
    Fast heuristic-based detector for Plan Mode triggering.

    Uses rule-based scoring to quickly determine if a query needs Plan Mode.
    This is Layer 1 of the Hybrid Detection Strategy.

    Scoring components:
    - Length: 0-0.3 points (longer queries = more complex)
    - Keywords: 0-0.4 points (complexity indicators)
    - Structure: 0-0.3 points (multi-part, dependencies)

    Total: 0.0 to 1.0

    Attributes:
        high_threshold: Score above which to auto-accept (default: 0.8)
        low_threshold: Score below which to auto-reject (default: 0.2)
        min_length: Minimum character length for consideration (default: 30)
    """

    # Complexity keywords that indicate planning is needed
    COMPLEXITY_KEYWORDS = [
        # Action verbs indicating multi-step work
        "implement",
        "create",
        "build",
        "develop",
        "design",
        "analyze",
        "refactor",
        "optimize",
        "integrate",
        "migrate",
        "rewrite",
        "restructure",
        "architect",
        "engineer",
        "construct",
        "assemble",
        "deploy",
        "configure",
        "setup",
        "establish",
        # Multi-step indicators
        "multiple",
        "several",
        "various",
        "complex",
        "comprehensive",
        "complete",
        "full",
        "entire",
        "whole",
        "end-to-end",
        "step by step",
        "step-by-step",
        "systematic",
        "system",
        "feature",
        "module",
        "component",
        "service",
        "application",
        "framework",
        "architecture",
        "workflow",
        "pipeline",
        # Testing and quality
        "test",
        "verify",
        "validate",
        "ensure",
        "guarantee",
        "check",
        "review",
        "audit",
        "inspect",
    ]

    # Dependency/sequence markers indicating multi-part work
    DEPENDENCY_PATTERNS = [
        r"\bfirst\b.*\bthen\b",
        r"\bafter\b",
        r"\bbefore\b",
        r"\bonce\b.*\bthen\b",
        r"\bwhen\b.*\bthen\b",
        r"\bnext\b",
        r"\bthen\b",
        r"\bfinally\b",
        r"\blastly\b",
        r"\bsubsequent\b",
        r"\bfollowing\b",
    ]

    # Numbered step patterns
    STEP_PATTERNS = [
        r"^\d+\.",  # "1.", "2.", etc.
        r"^\d+\)",  # "1)", "2)", etc.
        r"^[a-zA-Z]\)",  # "a)", "b)", etc.
        r"\bstep\s+\d+",
        r"\bphase\s+\d+",
        r"\bstage\s+\d+",
    ]

    def __init__(
        self,
        high_threshold: float = 0.8,
        low_threshold: float = 0.2,
        min_length: int = 30,
    ) -> None:
        """
        Initialize the FastHeuristicDetector.

        Args:
            high_threshold: Score above which to auto-trigger (default: 0.8)
            low_threshold: Score below which to auto-reject (default: 0.2)
            min_length: Minimum character length for consideration (default: 30)
        """
        if high_threshold <= low_threshold:
            raise ValueError(
                f"high_threshold ({high_threshold}) must be > low_threshold ({low_threshold})"
            )
        if not 0 <= low_threshold <= high_threshold <= 1:
            raise ValueError(
                f"Thresholds must be in [0, 1]: low={low_threshold}, high={high_threshold}"
            )

        self.high_threshold = high_threshold
        self.low_threshold = low_threshold
        self.min_length = min_length

        # Pre-compile regex patterns for performance
        self._dependency_regex = re.compile(
            "|".join(self.DEPENDENCY_PATTERNS), re.IGNORECASE
        )
        self._step_regex = re.compile(
            "|".join(self.STEP_PATTERNS), re.IGNORECASE | re.MULTILINE
        )

    def get_length_score(self, query: Optional[str]) -> float:
        """
        Calculate length-based complexity score.

        Score ranges from 0 to 0.3 (30% weight).

        Scoring:
        - < 30 chars: 0
        - 30-100 chars: linear 0 to 0.15
        - 100-200 chars: linear 0.15 to 0.25
        - >= 200 chars: 0.3 (max)

        Args:
            query: The user query to score

        Returns:
            Length score (0.0 to 0.3)
        """
        if not query:
            return 0.0

        length = len(query.strip())

        if length < self.min_length:
            return 0.0
        elif length < 100:
            # Linear: 30 -> 0, 100 -> 0.15
            return 0.15 * (length - self.min_length) / (100 - self.min_length)
        elif length < 200:
            # Linear: 100 -> 0.15, 200 -> 0.25
            return 0.15 + 0.10 * (length - 100) / 100
        else:
            return 0.3  # Max length score

    def get_keyword_score(self, query: Optional[str]) -> float:
        """
        Calculate keyword-based complexity score.

        Score ranges from 0 to 0.4 (40% weight).

        Each complexity keyword contributes to the score.
        More unique keywords = higher score.

        Args:
            query: The user query to score

        Returns:
            Keyword score (0.0 to 0.4)
        """
        if not query:
            return 0.0

        query_lower = query.lower()
        keywords_found = set()

        for keyword in self.COMPLEXITY_KEYWORDS:
            if keyword in query_lower:
                keywords_found.add(keyword)

        # Each keyword adds points, capped at 0.4
        # 1-2 keywords: ~0.1-0.2
        # 3-5 keywords: ~0.25-0.35
        # 6+ keywords: 0.4 (max)
        score = min(0.4, len(keywords_found) * 0.07)

        return score

    def get_structural_score(self, query: Optional[str]) -> float:
        """
        Calculate structure-based complexity score.

        Score ranges from 0 to 0.3 (30% weight).

        Structural indicators:
        - Multiple sentences (periods, newlines)
        - Dependency markers ("first...then", "after...then")
        - Numbered steps ("1.", "step 1")

        Args:
            query: The user query to score

        Returns:
            Structural score (0.0 to 0.3)
        """
        if not query:
            return 0.0

        score = 0.0
        query_stripped = query.strip()

        # Count sentences (periods, newlines, question marks)
        sentences = re.split(r"[.!?]\s+|\n", query_stripped)
        non_empty_sentences = [s.strip() for s in sentences if s.strip()]
        sentence_count = len(non_empty_sentences)

        # Multiple sentences add up to 0.15
        if sentence_count >= 2:
            score += min(0.15, (sentence_count - 1) * 0.05)

        # Dependency patterns add up to 0.1
        if self._dependency_regex.search(query_stripped):
            score += 0.1

        # Numbered steps add up to 0.05
        step_matches = self._step_regex.findall(query_stripped)
        if step_matches:
            score += min(0.05, len(step_matches) * 0.02)

        return min(0.3, score)

    def get_complexity_score(self, query: Optional[str]) -> float:
        """
        Calculate overall complexity score.

        Combines length, keyword, and structural scores.

        Args:
            query: The user query to score

        Returns:
            Overall complexity score (0.0 to 1.0)
        """
        if not query:
            return 0.0

        if not query.strip():
            return 0.0

        length_score = self.get_length_score(query)
        keyword_score = self.get_keyword_score(query)
        structural_score = self.get_structural_score(query)

        total = length_score + keyword_score + structural_score

        return min(1.0, total)

    def detect(self, query: Optional[str]) -> DetectionResult:
        """
        Detect if Plan Mode should be triggered for the query.

        Args:
            query: The user query to analyze

        Returns:
            DetectionResult with should_trigger, confidence, and method
        """
        score = self.get_complexity_score(query)

        # Determine if should trigger based on thresholds
        # Note: This is Layer 1 only, so we return the heuristic result
        # The HybridDetector will decide whether to use Layer 3 (LLM)
        # based on the score being in the ambiguous range
        should_trigger = score >= self.high_threshold

        return DetectionResult(
            should_trigger=should_trigger,
            confidence=score,
            method="heuristic",
        )
