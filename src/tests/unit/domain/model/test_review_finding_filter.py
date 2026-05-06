"""Unit tests for the deterministic review-finding filter."""

from __future__ import annotations

import pytest

from src.domain.model.review.finding_filter import (
    filter_findings,
    is_test_file,
    validate_finding,
)
from src.domain.model.review.review_finding import (
    FindingVerdict,
    RawReviewFinding,
    ReviewFindingContext,
    ReviewSeverity,
)


def _raw(
    *,
    file: str = "src/services/auth.py",
    category: str = "security",
    severity: ReviewSeverity = ReviewSeverity.WARNING,
    description: str = "Suspicious password handling.",
    suggestion: str = "Hash with bcrypt before persistence.",
    raw_confidence: int = 7,
    concrete_evidence: bool = False,
) -> RawReviewFinding:
    return RawReviewFinding(
        file=file,
        line=42,
        category=category,
        severity=severity,
        raw_confidence=raw_confidence,
        description=description,
        suggestion=suggestion,
        concrete_evidence=concrete_evidence,
    )


@pytest.mark.parametrize(
    "path,expected",
    [
        ("src/tests/unit/test_foo.py", True),
        ("web/src/test/components/foo.spec.ts", True),
        ("e2e/login.spec.ts", True),
        ("__tests__/util.ts", True),
        ("src/services/auth.py", False),
        ("docs/notes.md", False),
    ],
)
def test_is_test_file(path: str, expected: bool) -> None:
    assert is_test_file(path) is expected


def test_rejects_validation_finding_in_test_file() -> None:
    finding = _raw(
        file="src/tests/unit/test_auth.py",
        category="validation",
        description="Missing input validation.",
    )
    result = validate_finding(finding)
    assert result.verdict is FindingVerdict.REJECT
    assert "Test file" in result.reasoning


def test_rejects_lint_covered_category() -> None:
    finding = _raw(category="formatting")
    result = validate_finding(finding)
    assert result.verdict is FindingVerdict.REJECT


def test_respects_external_linter_covered_set() -> None:
    finding = _raw(category="ImportOrder")
    result = validate_finding(
        finding,
        ReviewFindingContext(linter_covered_categories=("importorder",)),
    )
    assert result.verdict is FindingVerdict.REJECT


def test_rejects_framework_handled_xss() -> None:
    finding = _raw(
        category="XSS",
        description="React auto-escapes children but worth noting.",
    )
    result = validate_finding(finding)
    assert result.verdict is FindingVerdict.REJECT


def test_rejects_speculative_description_without_evidence() -> None:
    finding = _raw(
        description="This could potentially leak memory under load.",
        suggestion="Investigate.",
    )
    result = validate_finding(finding)
    assert result.verdict is FindingVerdict.REJECT


def test_keeps_speculative_description_when_evidence_attached() -> None:
    finding = _raw(
        description="This could potentially leak memory under load.",
        suggestion="Trace shows ref cycle in CacheLayer.",
        concrete_evidence=True,
    )
    result = validate_finding(finding)
    assert result.verdict is FindingVerdict.KEEP


def test_rejects_todo_marker_findings() -> None:
    finding = _raw(description="Adds a TODO comment for later.", suggestion="Track in backlog.")
    result = validate_finding(finding)
    assert result.verdict is FindingVerdict.REJECT


def test_rejects_logging_below_critical() -> None:
    finding = _raw(
        category="logging",
        severity=ReviewSeverity.SUGGESTION,
        description="Add audit trail for config changes.",
    )
    result = validate_finding(finding)
    assert result.verdict is FindingVerdict.REJECT


def test_keeps_logging_when_critical() -> None:
    finding = _raw(
        category="logging",
        severity=ReviewSeverity.CRITICAL,
        description="Audit trail missing for sensitive token rotation.",
    )
    result = validate_finding(finding)
    assert result.verdict is FindingVerdict.KEEP


def test_keep_path_bumps_confidence_when_concrete_evidence() -> None:
    finding = _raw(raw_confidence=5, concrete_evidence=True)
    result = validate_finding(finding)
    assert result.verdict is FindingVerdict.KEEP
    assert result.validated_confidence == 6


def test_filter_findings_batches() -> None:
    findings = [
        _raw(category="formatting"),
        _raw(category="security", description="Password stored in plaintext."),
    ]
    results = filter_findings(findings)
    assert [r.verdict for r in results] == [FindingVerdict.REJECT, FindingVerdict.KEEP]
