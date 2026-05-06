"""Lane transition artifact gate.

Distilled from routa's "evidence required to advance" model. A lane may
declare a set of *semantic* artifact kinds it expects on the card before
the user can move it to the next lane. This complements the
:class:`GateCheck` body-section checks already in ``contract.py`` — those
verify the *narrative* is present, this verifies the *evidence* is.

Only structural set-membership checks live here. Whether an artifact is
"good enough" is a subjective verdict and must be made by an agent
tool-call (per Agent-First).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.domain.shared_kernel import ValueObject


class RequiredArtifactKind(str, Enum):
    """Semantic categories of evidence a lane may require.

    Distinct from :class:`ArtifactCategory` (which is a storage / MIME
    classification). A single PNG file may simultaneously be category
    ``IMAGE`` and kind ``SCREENSHOT_RUNTIME``.
    """

    EXECUTION_PLAN = "execution_plan"
    DEV_EVIDENCE = "dev_evidence"
    CHANGED_FILES_LIST = "changed_files_list"
    TEST_REPORT = "test_report"
    REVIEW_VERDICT = "review_verdict"
    COMPLETION_SUMMARY = "completion_summary"
    SCREENSHOT_RUNTIME = "screenshot_runtime"
    DELIVERY_BRANCH_REPORT = "delivery_branch_report"


@dataclass(frozen=True, kw_only=True)
class ArtifactGapReport(ValueObject):
    """Pure result of evaluating an artifact gate."""

    lane_id: str
    next_lane_id: str | None
    required: tuple[RequiredArtifactKind, ...]
    present: tuple[RequiredArtifactKind, ...]
    missing: tuple[RequiredArtifactKind, ...]

    @property
    def ready(self) -> bool:
        return len(self.missing) == 0


@dataclass(frozen=True, kw_only=True)
class LaneArtifactRequirement(ValueObject):
    """How many / which artifact kinds a lane needs to allow exit."""

    lane_id: str
    next_lane_id: str | None
    required: tuple[RequiredArtifactKind, ...] = field(default_factory=tuple)


def evaluate_artifact_gap(
    requirement: LaneArtifactRequirement,
    *,
    present: frozenset[RequiredArtifactKind],
) -> ArtifactGapReport:
    """Pure structural diff: declared - present = missing."""
    required_set = frozenset(requirement.required)
    actually_present = required_set & present
    missing = required_set - present
    return ArtifactGapReport(
        lane_id=requirement.lane_id,
        next_lane_id=requirement.next_lane_id,
        required=requirement.required,
        present=tuple(sorted(actually_present, key=lambda k: k.value)),
        missing=tuple(sorted(missing, key=lambda k: k.value)),
    )


def default_lane_artifact_requirements() -> tuple[LaneArtifactRequirement, ...]:
    """Default semantic artifact requirements per Kanban lane."""
    return (
        LaneArtifactRequirement(
            lane_id="backlog",
            next_lane_id="todo",
            required=(),
        ),
        LaneArtifactRequirement(
            lane_id="todo",
            next_lane_id="dev",
            required=(RequiredArtifactKind.EXECUTION_PLAN,),
        ),
        LaneArtifactRequirement(
            lane_id="dev",
            next_lane_id="review",
            required=(
                RequiredArtifactKind.DEV_EVIDENCE,
                RequiredArtifactKind.CHANGED_FILES_LIST,
                RequiredArtifactKind.TEST_REPORT,
            ),
        ),
        LaneArtifactRequirement(
            lane_id="review",
            next_lane_id="done",
            required=(RequiredArtifactKind.REVIEW_VERDICT,),
        ),
        LaneArtifactRequirement(
            lane_id="done",
            next_lane_id=None,
            required=(RequiredArtifactKind.COMPLETION_SUMMARY,),
        ),
    )


__all__ = [
    "ArtifactGapReport",
    "LaneArtifactRequirement",
    "RequiredArtifactKind",
    "default_lane_artifact_requirements",
    "evaluate_artifact_gap",
]
