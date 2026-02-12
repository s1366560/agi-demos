"""Plan Mode detector - decides whether to suggest Plan Mode for a query."""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Keywords that suggest a complex task needing planning
_COMPLEX_KEYWORDS = [
    "refactor", "redesign", "implement", "migrate", "upgrade",
    "重构", "重新设计", "实现", "迁移", "升级",
    "add feature", "new feature", "build", "create system",
    "添加功能", "新功能", "构建", "创建系统",
    "integrate", "optimize", "overhaul", "architecture",
    "集成", "优化", "全面改造", "架构",
]

# Patterns that indicate multi-step work
_MULTI_STEP_PATTERNS = [
    r"\d+\.\s",  # Numbered lists
    r"(?:first|then|after|finally|next)",
    r"(?:首先|然后|接着|最后|其次)",
    r"multiple\s+(?:files|components|modules)",
    r"多个\s*(?:文件|组件|模块)",
]


@dataclass(frozen=True)
class PlanSuggestion:
    """Result of plan mode detection."""

    should_suggest: bool
    reason: str
    confidence: float  # 0.0 to 1.0


class PlanDetector:
    """Lightweight heuristic detector for when to suggest Plan Mode.

    Uses simple keyword and pattern matching. No LLM calls needed.
    The threshold is intentionally lenient - the user always confirms.
    """

    def __init__(self, min_confidence: float = 0.4) -> None:
        self._min_confidence = min_confidence

    def detect(self, query: str) -> PlanSuggestion:
        """Analyze a user query and decide if Plan Mode should be suggested."""
        if len(query.strip()) < 20:
            return PlanSuggestion(
                should_suggest=False,
                reason="Query too short for planning",
                confidence=0.0,
            )

        score = 0.0
        reasons: list[str] = []

        # Check for complexity keywords
        query_lower = query.lower()
        keyword_matches = sum(1 for kw in _COMPLEX_KEYWORDS if kw in query_lower)
        if keyword_matches > 0:
            keyword_score = min(keyword_matches * 0.15, 0.45)
            score += keyword_score
            reasons.append(f"complexity keywords ({keyword_matches})")

        # Check for multi-step patterns
        pattern_matches = sum(
            1 for p in _MULTI_STEP_PATTERNS if re.search(p, query, re.IGNORECASE)
        )
        if pattern_matches > 0:
            pattern_score = min(pattern_matches * 0.15, 0.3)
            score += pattern_score
            reasons.append(f"multi-step patterns ({pattern_matches})")

        # Length-based heuristic (longer queries tend to be more complex)
        if len(query) > 200:
            score += 0.15
            reasons.append("detailed description")
        elif len(query) > 100:
            score += 0.08

        # Question mark penalty (questions are usually not planning tasks)
        if query.strip().endswith("?") and score < 0.5:
            score *= 0.5
            reasons.append("likely a question")

        score = min(score, 1.0)
        should_suggest = score >= self._min_confidence

        reason = ", ".join(reasons) if reasons else "no planning indicators"

        logger.debug(
            f"Plan detection: score={score:.2f}, suggest={should_suggest}, reasons={reason}"
        )

        return PlanSuggestion(
            should_suggest=should_suggest,
            reason=reason,
            confidence=score,
        )
