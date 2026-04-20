"""Exhaustive tests for the task state machine (P2d M1).

Covers the full Cartesian product of (role × from × to) using the canonical
legal-transition table re-declared inline here as an independent spec source.
If this test's table and ``transitions.py``'s table ever disagree, the test
fails — that is the point.
"""

from __future__ import annotations

import pytest

from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus as S
from src.infrastructure.agent.workspace.state_machine import (
    IllegalTransitionError,
    TaskRole,
    allowed_next,
    can_transition,
    guard_reasons,
    transition,
)

# ---------------------------------------------------------------------------
# Independent spec table (duplicated intentionally — a failing test here means
# the implementation diverged from the documented contract).
# ---------------------------------------------------------------------------

LEGAL_ROOT: dict[S, frozenset[S]] = {
    S.TODO: frozenset({S.IN_PROGRESS, S.BLOCKED}),
    S.IN_PROGRESS: frozenset({S.DONE, S.BLOCKED}),
    S.BLOCKED: frozenset({S.IN_PROGRESS, S.DONE}),
    S.DONE: frozenset(),
    S.DISPATCHED: frozenset(),
    S.EXECUTING: frozenset(),
    S.REPORTED: frozenset(),
    S.ADJUDICATING: frozenset(),
}

LEGAL_EXECUTION: dict[S, frozenset[S]] = {
    S.TODO: frozenset({S.DISPATCHED, S.BLOCKED}),
    S.DISPATCHED: frozenset({S.EXECUTING, S.TODO, S.BLOCKED}),
    S.EXECUTING: frozenset({S.REPORTED, S.BLOCKED}),
    S.REPORTED: frozenset({S.ADJUDICATING, S.TODO, S.BLOCKED}),
    S.ADJUDICATING: frozenset({S.DONE, S.TODO, S.BLOCKED}),
    S.BLOCKED: frozenset({S.TODO}),
    S.DONE: frozenset(),
    S.IN_PROGRESS: frozenset(),
}

ILLEGAL_CURRENT_ROOT: frozenset[S] = frozenset(
    {S.DISPATCHED, S.EXECUTING, S.REPORTED, S.ADJUDICATING}
)
ILLEGAL_CURRENT_EXECUTION: frozenset[S] = frozenset({S.IN_PROGRESS})

ALL_STATUSES: list[S] = list(S)


def _legal_table(role: TaskRole) -> dict[S, frozenset[S]]:
    return LEGAL_ROOT if role is TaskRole.ROOT else LEGAL_EXECUTION


# ---------------------------------------------------------------------------
# allowed_next — table parity
# ---------------------------------------------------------------------------


class TestAllowedNext:
    @pytest.mark.parametrize("role", [TaskRole.ROOT, TaskRole.EXECUTION])
    @pytest.mark.parametrize("current", ALL_STATUSES)
    def test_allowed_next_matches_spec(self, role: TaskRole, current: S) -> None:
        expected = _legal_table(role)[current]
        assert allowed_next(role, current) == expected

    @pytest.mark.parametrize("current", [S.DISPATCHED, S.EXECUTING, S.REPORTED, S.ADJUDICATING])
    def test_root_orchestration_only_status_is_dead_end(self, current: S) -> None:
        assert allowed_next(TaskRole.ROOT, current) == frozenset()

    def test_execution_in_progress_is_dead_end(self) -> None:
        assert allowed_next(TaskRole.EXECUTION, S.IN_PROGRESS) == frozenset()


# ---------------------------------------------------------------------------
# can_transition — Cartesian product
# ---------------------------------------------------------------------------


def _all_triples() -> list[tuple[TaskRole, S, S]]:
    triples = []
    for role in (TaskRole.ROOT, TaskRole.EXECUTION):
        for cur in ALL_STATUSES:
            for tgt in ALL_STATUSES:
                triples.append((role, cur, tgt))
    return triples


class TestCanTransition:
    @pytest.mark.parametrize(("role", "cur", "tgt"), _all_triples())
    def test_can_transition_matches_spec(self, role: TaskRole, cur: S, tgt: S) -> None:
        expected = tgt in _legal_table(role)[cur]
        assert can_transition(role, cur, tgt) is expected


# ---------------------------------------------------------------------------
# guard_reasons — legal ⇔ empty
# ---------------------------------------------------------------------------


class TestGuardReasons:
    @pytest.mark.parametrize(("role", "cur", "tgt"), _all_triples())
    def test_legal_iff_empty_reasons(self, role: TaskRole, cur: S, tgt: S) -> None:
        legal = tgt in _legal_table(role)[cur]
        reasons = guard_reasons(role, cur, tgt)
        assert (reasons == []) is legal

    @pytest.mark.parametrize("s", ALL_STATUSES)
    def test_noop_transition_is_rejected(self, s: S) -> None:
        # A → A is never a legal transition; guard_reasons calls it out explicitly.
        reasons = guard_reasons(TaskRole.ROOT, s, s)
        assert reasons
        assert any("no-op transition" in r for r in reasons)

    def test_terminal_done_reasons_mention_terminal(self) -> None:
        reasons = guard_reasons(TaskRole.EXECUTION, S.DONE, S.TODO)
        assert any("terminal" in r for r in reasons)

    def test_invalid_current_for_root_flagged(self) -> None:
        # DISPATCHED is never a valid current state for a root.
        reasons = guard_reasons(TaskRole.ROOT, S.DISPATCHED, S.DONE)
        assert any("not valid for role root" in r for r in reasons)

    def test_invalid_current_for_execution_flagged(self) -> None:
        # IN_PROGRESS is not used by execution tasks.
        reasons = guard_reasons(TaskRole.EXECUTION, S.IN_PROGRESS, S.DONE)
        assert any("not valid for role execution" in r for r in reasons)


# ---------------------------------------------------------------------------
# transition() — raises for illegal, returns target for legal
# ---------------------------------------------------------------------------


class TestTransition:
    def test_returns_target_for_legal(self) -> None:
        assert transition(TaskRole.ROOT, S.TODO, S.IN_PROGRESS) is S.IN_PROGRESS

    def test_raises_for_illegal(self) -> None:
        with pytest.raises(IllegalTransitionError) as exc_info:
            transition(TaskRole.ROOT, S.DONE, S.TODO)
        err = exc_info.value
        assert err.role is TaskRole.ROOT
        assert err.current is S.DONE
        assert err.target is S.TODO
        assert err.reasons  # non-empty
        # message should surface role + states
        msg = str(err)
        assert "root" in msg
        assert "done" in msg
        assert "todo" in msg

    def test_raises_for_noop(self) -> None:
        with pytest.raises(IllegalTransitionError):
            transition(TaskRole.EXECUTION, S.TODO, S.TODO)

    def test_raises_for_orchestration_status_on_root(self) -> None:
        with pytest.raises(IllegalTransitionError):
            transition(TaskRole.ROOT, S.EXECUTING, S.DONE)


# ---------------------------------------------------------------------------
# Happy path smoke tests — canonical lifecycles end-to-end
# ---------------------------------------------------------------------------


class TestCanonicalFlows:
    def test_root_happy_path(self) -> None:
        cur = S.TODO
        for nxt in (S.IN_PROGRESS, S.DONE):
            cur = transition(TaskRole.ROOT, cur, nxt)
        assert cur is S.DONE

    def test_execution_happy_path(self) -> None:
        cur = S.TODO
        for nxt in (S.DISPATCHED, S.EXECUTING, S.REPORTED, S.ADJUDICATING, S.DONE):
            cur = transition(TaskRole.EXECUTION, cur, nxt)
        assert cur is S.DONE

    def test_execution_adjudicator_rejects_then_replans(self) -> None:
        cur = S.TODO
        # first attempt fails at adjudication → back to TODO
        for nxt in (S.DISPATCHED, S.EXECUTING, S.REPORTED, S.ADJUDICATING, S.TODO):
            cur = transition(TaskRole.EXECUTION, cur, nxt)
        # second attempt succeeds
        for nxt in (S.DISPATCHED, S.EXECUTING, S.REPORTED, S.ADJUDICATING, S.DONE):
            cur = transition(TaskRole.EXECUTION, cur, nxt)
        assert cur is S.DONE

    def test_execution_blocked_then_unblocked(self) -> None:
        cur = transition(TaskRole.EXECUTION, S.EXECUTING, S.BLOCKED)
        assert cur is S.BLOCKED
        cur = transition(TaskRole.EXECUTION, cur, S.TODO)
        assert cur is S.TODO

    def test_root_blocked_then_resumed(self) -> None:
        cur = transition(TaskRole.ROOT, S.IN_PROGRESS, S.BLOCKED)
        cur = transition(TaskRole.ROOT, cur, S.IN_PROGRESS)
        cur = transition(TaskRole.ROOT, cur, S.DONE)
        assert cur is S.DONE


# ---------------------------------------------------------------------------
# Coverage summary: the Cartesian parametrization alone runs
# 2 roles × 8 statuses × 8 statuses = 128 cases per test function.
# ---------------------------------------------------------------------------
