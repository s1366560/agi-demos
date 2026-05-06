"""Review Gate domain types — 3-layer review architecture scaffold.

Distilled from routa's "Harness Monitor → Entrix Fitness → Gate Specialist"
review pipeline. This module defines pure value objects and verdict types
only; the actual evaluation lives behind ports in
``src/domain/ports/review/``.

Design contract:

- **Layer 1 — Harness Monitor** observes execution and reports *what
  happened* (objective signals). Never decides pass/fail.
- **Layer 2 — Entrix Fitness** runs deterministic hard gates (test exit
  codes, lint codes, artifact presence). Boolean + evidence only.
- **Layer 3 — Gate Specialist** is an agent. It synthesises layers 1 + 2
  with the canonical story's acceptance criteria and renders a final
  ``GateDecision``. Per the project's Agent First rule the verdict MUST
  come from a structured tool-call — never from regex on stdout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from src.domain.model.review.review_finding import (
    FindingVerdict,
    RawReviewFinding,
    ReviewFindingContext,
    ReviewSeverity,
    ValidatedReviewFinding,
)


class ReviewVerdict(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATE = "ESCALATE"


class CriterionStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNVERIFIED = "unverified"


# --------------------------- Layer 1: Harness ---------------------------


@dataclass(frozen=True, kw_only=True)
class HarnessSignal:
    """Objective execution observation (no verdict, no judgment)."""

    kind: str  # e.g. "test_run", "lint_run", "build", "manual_check"
    what_happened: str  # short, factual description
    artifact_refs: tuple[str, ...] = field(default_factory=tuple)
    started_at: datetime
    finished_at: datetime
    metadata: dict[str, str] = field(default_factory=dict)


# --------------------------- Layer 2: Fitness ---------------------------


@dataclass(frozen=True, kw_only=True)
class HardGateResult:
    """Single deterministic gate check (e.g. ``pytest exit 0``)."""

    name: str
    passed: bool
    evidence_ref: str | None = None
    detail: str = ""


@dataclass(frozen=True, kw_only=True)
class EntrixVerdict:
    """Aggregated result of all hard gates and required-evidence checks."""

    hard_gates_passed: bool
    evidence_present: bool
    gate_results: tuple[HardGateResult, ...] = field(default_factory=tuple)
    missing_evidence: tuple[str, ...] = field(default_factory=tuple)


# --------------------------- Layer 3: Specialist ---------------------------


@dataclass(frozen=True, kw_only=True)
class CriterionEvaluation:
    """Per-acceptance-criterion verdict authored by the Gate Specialist agent."""

    criterion_id: str
    status: CriterionStatus
    rationale: str
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, kw_only=True)
class GateDecision:
    """Final review verdict for a workspace task at a given gate.

    ``rationale`` and per-AC ``evaluations`` MUST be authored by the Gate
    Specialist agent via a structured tool-call; never by regex/keyword
    matching on harness output.
    """

    verdict: ReviewVerdict
    rationale: str
    evaluations: tuple[CriterionEvaluation, ...] = field(default_factory=tuple)
    decided_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    specialist_agent_id: str | None = None


__all__ = [
    "CriterionEvaluation",
    "CriterionStatus",
    "EntrixVerdict",
    "FindingVerdict",
    "GateDecision",
    "HardGateResult",
    "HarnessSignal",
    "RawReviewFinding",
    "ReviewFindingContext",
    "ReviewSeverity",
    "ReviewVerdict",
    "ValidatedReviewFinding",
]
