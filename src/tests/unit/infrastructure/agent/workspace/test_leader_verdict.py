"""Unit tests for the leader verdict module (P2d M3)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.domain.model.workspace.workspace_task import (
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
from src.infrastructure.agent.workspace.adjudicator import (
    LEADER_VERDICT_STATUSES,
    LeaderVerdict,
    action_for,
    build_adjudication_metadata,
    execution_state_reason,
    phase_for,
)

# ---------------------------------------------------------------------------
# Pure mappings
# ---------------------------------------------------------------------------


class TestPhaseAction:
    @pytest.mark.parametrize(
        ("status", "expected_phase", "expected_action"),
        [
            (WorkspaceTaskStatus.TODO, "todo", "reprioritized"),
            (WorkspaceTaskStatus.IN_PROGRESS, "in_progress", "start"),
            (WorkspaceTaskStatus.BLOCKED, "blocked", "blocked"),
            (WorkspaceTaskStatus.DONE, "done", "completed"),
        ],
    )
    def test_valid_statuses(
        self,
        status: WorkspaceTaskStatus,
        expected_phase: str,
        expected_action: str,
    ) -> None:
        assert phase_for(status) == expected_phase
        assert action_for(status) == expected_action

    @pytest.mark.parametrize(
        "invalid_status",
        [
            WorkspaceTaskStatus.DISPATCHED,
            WorkspaceTaskStatus.EXECUTING,
            WorkspaceTaskStatus.REPORTED,
            WorkspaceTaskStatus.ADJUDICATING,
        ],
    )
    def test_orchestration_statuses_rejected(self, invalid_status: WorkspaceTaskStatus) -> None:
        with pytest.raises(ValueError, match="not a valid leader verdict status"):
            phase_for(invalid_status)
        with pytest.raises(ValueError, match="not a valid leader verdict status"):
            action_for(invalid_status)

    def test_leader_verdict_status_set(self) -> None:
        assert (
            frozenset(
                {
                    WorkspaceTaskStatus.TODO,
                    WorkspaceTaskStatus.IN_PROGRESS,
                    WorkspaceTaskStatus.BLOCKED,
                    WorkspaceTaskStatus.DONE,
                }
            )
            == LEADER_VERDICT_STATUSES
        )


# ---------------------------------------------------------------------------
# LeaderVerdict
# ---------------------------------------------------------------------------


class TestLeaderVerdict:
    @pytest.mark.parametrize("status", list(LEADER_VERDICT_STATUSES))
    def test_valid_statuses(self, status: WorkspaceTaskStatus) -> None:
        v = LeaderVerdict(status=status, summary="ok", actor_user_id="u1")
        assert v.status == status
        assert v.summary == "ok"
        assert v.actor_user_id == "u1"
        assert v.leader_agent_id is None
        assert v.attempt_id is None
        assert v.title is None
        assert v.priority is None

    @pytest.mark.parametrize(
        "invalid_status",
        [
            WorkspaceTaskStatus.DISPATCHED,
            WorkspaceTaskStatus.EXECUTING,
            WorkspaceTaskStatus.REPORTED,
            WorkspaceTaskStatus.ADJUDICATING,
        ],
    )
    def test_orchestration_statuses_rejected(self, invalid_status: WorkspaceTaskStatus) -> None:
        with pytest.raises(ValueError, match="LeaderVerdict.status"):
            LeaderVerdict(status=invalid_status, summary="", actor_user_id="u1")

    def test_empty_actor_user_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="actor_user_id"):
            LeaderVerdict(status=WorkspaceTaskStatus.DONE, summary="", actor_user_id="")

    def test_non_str_summary_rejected(self) -> None:
        with pytest.raises(ValueError, match="summary"):
            LeaderVerdict(
                status=WorkspaceTaskStatus.DONE,
                summary=None,  # type: ignore[arg-type]
                actor_user_id="u1",
            )

    def test_phase_action_shortcuts(self) -> None:
        v = LeaderVerdict(
            status=WorkspaceTaskStatus.IN_PROGRESS,
            summary="rework",
            actor_user_id="u1",
        )
        assert v.phase == "in_progress"
        assert v.action == "start"

    def test_frozen(self) -> None:
        v = LeaderVerdict(status=WorkspaceTaskStatus.DONE, summary="", actor_user_id="u1")
        with pytest.raises(Exception):
            v.summary = "mutated"  # type: ignore[misc]

    def test_full_payload(self) -> None:
        v = LeaderVerdict(
            status=WorkspaceTaskStatus.BLOCKED,
            summary="needs env",
            actor_user_id="u1",
            leader_agent_id="agent-leader",
            attempt_id="att-42",
            title="Do X",
            priority=WorkspaceTaskPriority.P2,
        )
        assert v.leader_agent_id == "agent-leader"
        assert v.attempt_id == "att-42"
        assert v.title == "Do X"
        assert v.priority == WorkspaceTaskPriority.P2


# ---------------------------------------------------------------------------
# build_adjudication_metadata
# ---------------------------------------------------------------------------


class TestBuildAdjudicationMetadata:
    def _verdict(
        self,
        *,
        status: WorkspaceTaskStatus = WorkspaceTaskStatus.DONE,
        summary: str = "all good",
    ) -> LeaderVerdict:
        return LeaderVerdict(
            status=status,
            summary=summary,
            actor_user_id="u1",
            leader_agent_id="agent-leader",
        )

    def test_clears_pending_flag(self) -> None:
        prior = {"pending_leader_adjudication": True, "other": "keep"}
        now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
        out = build_adjudication_metadata(
            verdict=self._verdict(),
            prior_metadata=prior,
            task_title="task",
            now=now,
        )
        assert out["pending_leader_adjudication"] is False
        assert out["other"] == "keep"

    def test_does_not_add_pending_flag_when_absent(self) -> None:
        prior: dict[str, object] = {}
        now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
        out = build_adjudication_metadata(
            verdict=self._verdict(),
            prior_metadata=prior,
            task_title="task",
            now=now,
        )
        # Current behavior: only touches flag if it was True.
        assert (
            "pending_leader_adjudication" not in out
            or out["pending_leader_adjudication"] is not True
        )

    def test_does_not_clear_false_pending_flag(self) -> None:
        # Only `is True` triggers clearing (False stays False).
        prior = {"pending_leader_adjudication": False}
        now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
        out = build_adjudication_metadata(
            verdict=self._verdict(),
            prior_metadata=prior,
            task_title="task",
            now=now,
        )
        assert out["pending_leader_adjudication"] is False

    def test_stamps_status_and_timestamp(self) -> None:
        prior: dict[str, object] = {}
        now = datetime(2026, 4, 20, 12, 34, 56, tzinfo=UTC)
        out = build_adjudication_metadata(
            verdict=self._verdict(status=WorkspaceTaskStatus.BLOCKED, summary="stuck"),
            prior_metadata=prior,
            task_title="Do X",
            now=now,
        )
        assert out["last_leader_adjudication_status"] == "blocked"
        assert out["last_leader_adjudicated_at"] == "2026-04-20T12:34:56Z"

    def test_does_not_mutate_input(self) -> None:
        prior = {"pending_leader_adjudication": True, "other": "v"}
        snapshot = dict(prior)
        now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
        _ = build_adjudication_metadata(
            verdict=self._verdict(),
            prior_metadata=prior,
            task_title="task",
            now=now,
        )
        assert prior == snapshot

    def test_iso_z_format(self) -> None:
        # Ensure we always get trailing Z, not +00:00.
        now = datetime(2030, 1, 1, tzinfo=UTC)
        out = build_adjudication_metadata(
            verdict=self._verdict(),
            prior_metadata={},
            task_title="t",
            now=now,
        )
        stamp = out["last_leader_adjudicated_at"]
        assert isinstance(stamp, str)
        assert stamp.endswith("Z")
        assert "+00:00" not in stamp

    def test_default_now_is_utc(self) -> None:
        # No explicit now → still produces an ISO Z string.
        out = build_adjudication_metadata(
            verdict=self._verdict(),
            prior_metadata={},
            task_title="t",
        )
        stamp = out["last_leader_adjudicated_at"]
        assert isinstance(stamp, str)
        assert stamp.endswith("Z")


# ---------------------------------------------------------------------------
# execution_state_reason
# ---------------------------------------------------------------------------


class TestExecutionStateReason:
    def test_with_summary(self) -> None:
        v = LeaderVerdict(
            status=WorkspaceTaskStatus.DONE,
            summary="shipped it",
            actor_user_id="u1",
        )
        assert execution_state_reason(verdict=v, task_title="Ignore") == (
            "workspace_goal_runtime.leader_adjudication.done:shipped it"
        )

    def test_empty_summary_falls_back_to_title(self) -> None:
        v = LeaderVerdict(
            status=WorkspaceTaskStatus.BLOCKED,
            summary="",
            actor_user_id="u1",
        )
        assert execution_state_reason(verdict=v, task_title="Do X") == (
            "workspace_goal_runtime.leader_adjudication.blocked:Do X"
        )

    @pytest.mark.parametrize(
        "status",
        list(LEADER_VERDICT_STATUSES),
    )
    def test_all_statuses(self, status: WorkspaceTaskStatus) -> None:
        v = LeaderVerdict(status=status, summary="s", actor_user_id="u1")
        result = execution_state_reason(verdict=v, task_title="t")
        assert status.value in result
        assert result.startswith("workspace_goal_runtime.leader_adjudication.")
