"""Tests for the lane artifact gap evaluator (P1-Art)."""

from __future__ import annotations

import pytest

from src.domain.model.lane_contract.artifact_gate import (
    LaneArtifactRequirement,
    RequiredArtifactKind,
    default_lane_artifact_requirements,
    evaluate_artifact_gap,
)


@pytest.mark.unit
class TestArtifactGapEvaluator:
    def test_no_required_artifacts_is_always_ready(self) -> None:
        req = LaneArtifactRequirement(lane_id="backlog", next_lane_id="todo", required=())
        report = evaluate_artifact_gap(req, present=frozenset())
        assert report.ready is True
        assert report.missing == ()

    def test_all_required_present_is_ready(self) -> None:
        req = LaneArtifactRequirement(
            lane_id="todo",
            next_lane_id="dev",
            required=(RequiredArtifactKind.EXECUTION_PLAN,),
        )
        report = evaluate_artifact_gap(
            req, present=frozenset({RequiredArtifactKind.EXECUTION_PLAN})
        )
        assert report.ready is True
        assert report.present == (RequiredArtifactKind.EXECUTION_PLAN,)

    def test_missing_kinds_returned_sorted(self) -> None:
        req = LaneArtifactRequirement(
            lane_id="dev",
            next_lane_id="review",
            required=(
                RequiredArtifactKind.DEV_EVIDENCE,
                RequiredArtifactKind.TEST_REPORT,
                RequiredArtifactKind.CHANGED_FILES_LIST,
            ),
        )
        report = evaluate_artifact_gap(req, present=frozenset())
        assert report.ready is False
        assert report.missing == (
            RequiredArtifactKind.CHANGED_FILES_LIST,
            RequiredArtifactKind.DEV_EVIDENCE,
            RequiredArtifactKind.TEST_REPORT,
        )

    def test_partial_present_split_correctly(self) -> None:
        req = LaneArtifactRequirement(
            lane_id="dev",
            next_lane_id="review",
            required=(
                RequiredArtifactKind.DEV_EVIDENCE,
                RequiredArtifactKind.TEST_REPORT,
            ),
        )
        report = evaluate_artifact_gap(
            req, present=frozenset({RequiredArtifactKind.TEST_REPORT})
        )
        assert report.present == (RequiredArtifactKind.TEST_REPORT,)
        assert report.missing == (RequiredArtifactKind.DEV_EVIDENCE,)
        assert report.ready is False

    def test_extra_present_artifacts_are_ignored(self) -> None:
        req = LaneArtifactRequirement(
            lane_id="todo",
            next_lane_id="dev",
            required=(RequiredArtifactKind.EXECUTION_PLAN,),
        )
        report = evaluate_artifact_gap(
            req,
            present=frozenset(
                {
                    RequiredArtifactKind.EXECUTION_PLAN,
                    RequiredArtifactKind.SCREENSHOT_RUNTIME,  # not required, ignored
                }
            ),
        )
        assert report.ready is True
        assert RequiredArtifactKind.SCREENSHOT_RUNTIME not in report.present

    def test_default_requirements_cover_all_active_lanes(self) -> None:
        defaults = default_lane_artifact_requirements()
        ids = {r.lane_id for r in defaults}
        assert {"backlog", "todo", "dev", "review", "done"} <= ids
