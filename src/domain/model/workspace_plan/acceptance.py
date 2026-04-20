"""Acceptance criteria and verification reports.

Replaces the legacy "leader LLM subjectively declares done" path with
machine-checkable criteria. The kinds here are deliberately conservative so
that most can be executed without any LLM at all (``cmd``, ``schema``,
``file_exists``, ``regex``). ``llm_judge`` is provided for subjective
criteria but must carry a confidence threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class CriterionKind(str, Enum):
    """Machine-checkable acceptance criterion kinds.

    * ``CMD``         — run a command in a sandbox; pass iff exit code <= max_exit
    * ``SCHEMA``      — validate an output against a JSON-Schema
    * ``FILE_EXISTS`` — assert a file exists (and optionally non-empty)
    * ``REGEX``       — regex-match an artifact blob / output string
    * ``LLM_JUDGE``   — ask an LLM judge; requires ``min_confidence``
    * ``CUSTOM``      — call a registered custom verifier by name
    """

    CMD = "cmd"
    SCHEMA = "schema"
    FILE_EXISTS = "file_exists"
    REGEX = "regex"
    LLM_JUDGE = "llm_judge"
    CUSTOM = "custom"


@dataclass(frozen=True)
class AcceptanceCriterion:
    """A single completion criterion attached to a :class:`PlanNode`.

    The ``spec`` dict is kind-specific — runners know the schema. We keep it
    dict-typed so planners can emit them from JSON without a custom class
    per kind.
    """

    kind: CriterionKind
    spec: dict[str, Any] = field(default_factory=dict)
    required: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.spec, dict):
            raise ValueError("AcceptanceCriterion.spec must be a dict")
        # Per-kind shallow validation — catches typos early.
        if self.kind is CriterionKind.CMD and not self.spec.get("cmd"):
            raise ValueError("CriterionKind.CMD requires spec.cmd")
        if self.kind is CriterionKind.SCHEMA and not self.spec.get("schema"):
            raise ValueError("CriterionKind.SCHEMA requires spec.schema (JSON Schema)")
        if self.kind is CriterionKind.FILE_EXISTS and not self.spec.get("path"):
            raise ValueError("CriterionKind.FILE_EXISTS requires spec.path")
        if self.kind is CriterionKind.REGEX and not self.spec.get("pattern"):
            raise ValueError("CriterionKind.REGEX requires spec.pattern")
        if self.kind is CriterionKind.LLM_JUDGE:
            conf = self.spec.get("min_confidence")
            if not isinstance(conf, (int, float)) or not 0.0 < conf <= 1.0:
                raise ValueError("CriterionKind.LLM_JUDGE requires spec.min_confidence in (0,1]")
        if self.kind is CriterionKind.CUSTOM and not self.spec.get("name"):
            raise ValueError("CriterionKind.CUSTOM requires spec.name")


@dataclass(frozen=True)
class EvidenceRef:
    """Pointer to evidence supporting a verification outcome.

    ``kind`` is a short tag like ``"artifact"``, ``"log"``, ``"stdout"``,
    ``"file"``. ``ref`` is a resolver-specific string (URL, file path, id).
    """

    kind: str
    ref: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("EvidenceRef.kind cannot be empty")
        if not self.ref:
            raise ValueError("EvidenceRef.ref cannot be empty")


@dataclass(frozen=True)
class CriterionResult:
    """Result of running one :class:`AcceptanceCriterion`."""

    criterion: AcceptanceCriterion
    passed: bool
    confidence: float = 1.0  # 0..1 — 1.0 for deterministic checks
    message: str = ""
    evidence: tuple[EvidenceRef, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("CriterionResult.confidence must be in [0,1]")


@dataclass(frozen=True)
class VerificationReport:
    """Aggregate verdict from running all criteria on a PlanNode attempt."""

    node_id: str
    attempt_id: str | None
    results: tuple[CriterionResult, ...]
    ran_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def passed(self) -> bool:
        """True iff every *required* criterion passed."""
        return all(r.passed for r in self.results if r.criterion.required)

    @property
    def hard_fail(self) -> bool:
        """True iff any required criterion failed with high confidence (>= 0.9).

        Hard failures justify transitioning to ``BLOCKED`` instead of replan.
        """
        return any(
            (not r.passed) and r.criterion.required and r.confidence >= 0.9 for r in self.results
        )

    @property
    def failed_required(self) -> tuple[CriterionResult, ...]:
        return tuple(r for r in self.results if r.criterion.required and not r.passed)

    @property
    def evidence(self) -> tuple[EvidenceRef, ...]:
        out: list[EvidenceRef] = []
        for r in self.results:
            out.extend(r.evidence)
        return tuple(out)

    def summary(self) -> str:
        """Human-readable summary for leader LLM context or UI."""
        if self.passed:
            return f"verified ({len(self.results)} criteria passed)"
        fails = self.failed_required
        lines = [
            f"verification failed: {len(fails)}/{len(self.results)} required criteria did not pass"
        ]
        for r in fails[:5]:
            lines.append(f"  - [{r.criterion.kind.value}] {r.message or 'failed'}")
        return "\n".join(lines)
