"""Deterministic review-finding filter.

Distilled from routa's ``validateReviewFinding()`` in
``src/core/review/multi-phase-review.ts``. This is the *guardrail* pass that
runs **before** the LLM gate verdict, so we don't spend tokens deliberating
on findings that are structurally noise:

- validation/error-handling findings inside a test file
- findings in a category the linter already enforces
- framework-handled categories (XSS in React templating, body parsing in
  Next.js API routes, etc.)
- weasel-word descriptions (theoretical / speculative / could potentially)
- ``TODO``/``FIXME``/``HACK`` style findings (track in backlog, not review)
- pure logging / telemetry suggestions when severity is < CRITICAL

Per Agent-First: this filter only encodes *categorical* facts. Any
remaining finding still requires an agent verdict for severity + action.
"""

from __future__ import annotations

import re

from src.domain.model.review.review_finding import (
    FindingVerdict,
    RawReviewFinding,
    ReviewFindingContext,
    ReviewSeverity,
    ValidatedReviewFinding,
)

_TEST_FILE_RE = re.compile(
    r"(/|^)(tests?|__tests__|e2e)(/|$)|\.(test|spec)\.[A-Za-z]+$",
    re.IGNORECASE,
)

_STYLE_CATEGORY_KEYWORDS: tuple[str, ...] = (
    "style",
    "format",
    "naming",
    "lint",
    "typescript type",
)

_FRAMEWORK_HANDLED_KEYWORDS: tuple[str, ...] = (
    "xss",
    "body parsing",
    "next.js api",
    "react",
    "framework",
    "dangerouslysetinnerhtml",
)

_NON_ACTIONABLE_KEYWORDS: tuple[str, ...] = (
    "theoretical",
    "speculative",
    "could potentially",
    "might",
    "possible",
)

_TODO_KEYWORDS: tuple[str, ...] = ("todo", "fixme", "hack")
_LOGGING_KEYWORDS: tuple[str, ...] = ("logging", "audit trail", "telemetry")
_VALIDATION_PHRASES: tuple[str, ...] = (
    "validation",
    "missing error handling",
    "missing input validation",
)


def is_test_file(file_path: str) -> bool:
    """Return ``True`` if the path looks like a test file."""
    return bool(_TEST_FILE_RE.search(file_path))


def _clamp(value: int, low: int = 1, high: int = 10) -> int:
    return max(low, min(high, value))


def _normalize(text: str) -> str:
    return text.lower()


def _matches_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(token in haystack for token in needles)


def validate_finding(  # noqa: PLR0911 - one return per exclusion rule on purpose
    finding: RawReviewFinding,
    context: ReviewFindingContext | None = None,
) -> ValidatedReviewFinding:
    """Apply the deterministic guardrail filter to one finding.

    Pure function; idempotent; no I/O. Mirrors the structure of routa's
    ``validateReviewFinding`` so test parity is straightforward.
    """
    ctx = context or ReviewFindingContext()
    cat = _normalize(finding.category)
    desc = _normalize(finding.description)
    sug = _normalize(finding.suggestion)

    def _decide(
        validated_confidence: int,
        verdict: FindingVerdict,
        reasoning: str,
    ) -> ValidatedReviewFinding:
        return ValidatedReviewFinding(
            file=finding.file,
            line=finding.line,
            category=finding.category,
            severity=finding.severity,
            raw_confidence=_clamp(finding.raw_confidence),
            description=finding.description,
            suggestion=finding.suggestion,
            concrete_evidence=finding.concrete_evidence,
            validated_confidence=validated_confidence,
            verdict=verdict,
            reasoning=reasoning,
        )

    # 1. Test-file validation noise.
    if is_test_file(finding.file) and (
        "validation" in cat or _matches_any(desc, _VALIDATION_PHRASES)
    ):
        return _decide(
            3,
            FindingVerdict.REJECT,
            "Test file finding about validation/error handling is an "
            "explicit hard exclusion.",
        )

    # 2. Lint-covered or stylistic categories.
    covered = {c.lower() for c in ctx.linter_covered_categories}
    if cat in covered or _matches_any(cat, _STYLE_CATEGORY_KEYWORDS):
        return _decide(
            2,
            FindingVerdict.REJECT,
            "Stylistic/lint category already enforced by deterministic "
            "tooling; reviewer should not duplicate it.",
        )

    # 3. Framework-handled vulnerabilities.
    if _matches_any(cat, _FRAMEWORK_HANDLED_KEYWORDS) or _matches_any(
        desc, _FRAMEWORK_HANDLED_KEYWORDS
    ):
        return _decide(
            3,
            FindingVerdict.REJECT,
            "Category is handled by the framework's default behavior; "
            "elevate only with concrete bypass evidence.",
        )

    # 4. Speculative / non-actionable language.
    if _matches_any(desc, _NON_ACTIONABLE_KEYWORDS) and not finding.concrete_evidence:
        return _decide(
            3,
            FindingVerdict.REJECT,
            "Description uses speculative language without concrete "
            "evidence; reject as low-signal.",
        )

    # 5. TODO/FIXME/HACK style.
    if _matches_any(desc, _TODO_KEYWORDS) or _matches_any(sug, _TODO_KEYWORDS):
        return _decide(
            4,
            FindingVerdict.REJECT,
            "TODO/FIXME/HACK markers belong on the backlog, not the "
            "review gate.",
        )

    # 6. Pure logging/telemetry suggestion below CRITICAL.
    if finding.severity is not ReviewSeverity.CRITICAL and (
        _matches_any(cat, _LOGGING_KEYWORDS) or _matches_any(desc, _LOGGING_KEYWORDS)
    ):
        return _decide(
            4,
            FindingVerdict.REJECT,
            "Logging/telemetry suggestion below CRITICAL is not blocking.",
        )

    # Default — survives the deterministic filter; downstream agent renders
    # the final verdict.
    bonus = 1 if finding.concrete_evidence else 0
    return _decide(
        _clamp(finding.raw_confidence + bonus),
        FindingVerdict.KEEP,
        "Survived deterministic guardrails; defer severity decision to "
        "the gate specialist.",
    )


def filter_findings(
    findings: list[RawReviewFinding],
    context: ReviewFindingContext | None = None,
) -> list[ValidatedReviewFinding]:
    """Apply :func:`validate_finding` to a batch."""
    return [validate_finding(item, context) for item in findings]


__all__ = [
    "filter_findings",
    "is_test_file",
    "validate_finding",
]
