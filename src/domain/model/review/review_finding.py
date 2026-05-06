"""Review finding domain types — distilled from routa's ``multi-phase-review.ts``.

Routa runs a deterministic *guardrail* pass before the LLM verdict gate, so
agents do not waste tokens deciding whether a "missing input validation in
test file" finding is signal or noise. We mirror the same shape:

- ``RawReviewFinding``      — what an LLM reviewer first emits.
- ``ReviewFindingContext``  — environment hints (e.g. which categories the
  linter already covers).
- ``ValidatedReviewFinding`` — the same finding plus a structural
  ``KEEP``/``REJECT`` verdict and a deterministic ``reasoning``.

Per Agent-First: the *filter* below only encodes structural / categorical
exclusions (test-file noise, lint-covered categories, weasel-word phrasing
indicating low signal). The remaining KEEP findings still need an LLM
verdict to decide severity and final action. We never substitute heuristics
for that semantic call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.domain.shared_kernel import ValueObject


class ReviewSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    SUGGESTION = "SUGGESTION"


class FindingVerdict(str, Enum):
    """Deterministic guardrail verdict for a single review finding.

    Distinct from :class:`src.domain.model.review.ReviewVerdict`, which is the
    *gate-level* verdict for an entire change set.
    """

    KEEP = "KEEP"
    REJECT = "REJECT"


@dataclass(frozen=True, kw_only=True)
class RawReviewFinding(ValueObject):
    """A review finding before the deterministic guardrail pass."""

    file: str
    line: int
    category: str
    severity: ReviewSeverity
    raw_confidence: int
    description: str
    suggestion: str
    concrete_evidence: bool = False


@dataclass(frozen=True, kw_only=True)
class ReviewFindingContext(ValueObject):
    """Optional environmental hints used by the deterministic filter."""

    linter_covered_categories: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, kw_only=True)
class ValidatedReviewFinding(ValueObject):
    """A finding after the deterministic guardrail pass."""

    file: str
    line: int
    category: str
    severity: ReviewSeverity
    raw_confidence: int
    validated_confidence: int
    description: str
    suggestion: str
    concrete_evidence: bool
    verdict: FindingVerdict
    reasoning: str


__all__ = [
    "FindingVerdict",
    "RawReviewFinding",
    "ReviewFindingContext",
    "ReviewSeverity",
    "ValidatedReviewFinding",
]
