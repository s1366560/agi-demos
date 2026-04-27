"""Leader verdict value object and pure metadata mappings (P2d M3).

Distills the leader-adjudication decision into three pure units:

1. :class:`LeaderVerdict` — a frozen value object that captures everything the
   leader has decided about a worker's report. Validation rules live in
   ``__post_init__``.
2. :func:`phase_for` / :func:`action_for` — pure mappings from verdict status
   to the strings previously encoded as inline dicts in
   ``adjudicate_workspace_worker_report``.
3. :func:`build_adjudication_metadata` — pure constructor for the metadata
   patch the command service will persist. Deterministic modulo a caller-
   supplied ``now`` for test control.

The LLM call that *produces* the verdict is not in this module — that lives
in the leader agent's ``todowrite`` path. M3 is a structural refactor to
unblock later work (e.g. replacing the big if/elif chain with a dispatch
table keyed on ``LeaderVerdict.status``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.domain.model.workspace.workspace_task import (
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    LAST_LEADER_ADJUDICATION_STATUS,
    PENDING_LEADER_ADJUDICATION,
)

__all__ = [
    "LEADER_VERDICT_STATUSES",
    "LeaderVerdict",
    "action_for",
    "build_adjudication_metadata",
    "execution_state_reason",
    "phase_for",
]


# The four statuses a leader verdict can take. Orchestration-only statuses
# (DISPATCHED / EXECUTING / REPORTED / ADJUDICATING) are never the result of
# a leader decision — those are transient runtime states.
LEADER_VERDICT_STATUSES: frozenset[WorkspaceTaskStatus] = frozenset(
    {
        WorkspaceTaskStatus.TODO,
        WorkspaceTaskStatus.IN_PROGRESS,
        WorkspaceTaskStatus.BLOCKED,
        WorkspaceTaskStatus.DONE,
    }
)


_PHASE_MAP: dict[WorkspaceTaskStatus, str] = {
    WorkspaceTaskStatus.TODO: "todo",
    WorkspaceTaskStatus.IN_PROGRESS: "in_progress",
    WorkspaceTaskStatus.BLOCKED: "blocked",
    WorkspaceTaskStatus.DONE: "done",
}

_ACTION_MAP: dict[WorkspaceTaskStatus, str] = {
    WorkspaceTaskStatus.TODO: "reprioritized",
    WorkspaceTaskStatus.IN_PROGRESS: "start",
    WorkspaceTaskStatus.BLOCKED: "blocked",
    WorkspaceTaskStatus.DONE: "completed",
}


def phase_for(status: WorkspaceTaskStatus) -> str:
    """Return the execution-state phase name for a leader verdict status.

    Raises ``ValueError`` if ``status`` is not a valid leader verdict status.
    """
    try:
        return _PHASE_MAP[status]
    except KeyError as err:
        raise ValueError(
            f"status {status!r} is not a valid leader verdict status; "
            f"expected one of {sorted(s.value for s in LEADER_VERDICT_STATUSES)}"
        ) from err


def action_for(status: WorkspaceTaskStatus) -> str:
    """Return the execution-state action name for a leader verdict status.

    Raises ``ValueError`` if ``status`` is not a valid leader verdict status.
    """
    try:
        return _ACTION_MAP[status]
    except KeyError as err:
        raise ValueError(
            f"status {status!r} is not a valid leader verdict status; "
            f"expected one of {sorted(s.value for s in LEADER_VERDICT_STATUSES)}"
        ) from err


@dataclass(frozen=True, kw_only=True)
class LeaderVerdict:
    """Snapshot of the leader's adjudication decision. Pure value object.

    Fields
    ------
    status:
        Final status the leader has assigned to the execution task. Must be
        one of TODO / IN_PROGRESS / BLOCKED / DONE (see
        ``LEADER_VERDICT_STATUSES``).
    summary:
        Human-readable reason the leader attached to the verdict. May be
        empty string; never ``None``.
    actor_user_id:
        The user on whose behalf the leader agent is acting. Required for
        downstream attribution.
    leader_agent_id:
        Agent ID of the leader that produced the verdict. ``None`` is accepted
        for transitional callers where the leader is unbound, though in
        practice the command service requires one.
    attempt_id:
        The attempt ID being adjudicated (may be ``None`` when the task has
        no active attempt).
    title / priority:
        Optional overrides the leader may apply alongside the status change.
    """

    status: WorkspaceTaskStatus
    summary: str
    actor_user_id: str
    leader_agent_id: str | None = None
    attempt_id: str | None = None
    title: str | None = None
    priority: WorkspaceTaskPriority | None = None

    def __post_init__(self) -> None:
        if self.status not in LEADER_VERDICT_STATUSES:
            valid = sorted(s.value for s in LEADER_VERDICT_STATUSES)
            raise ValueError(f"LeaderVerdict.status must be one of {valid}; got {self.status!r}")
        if not isinstance(self.actor_user_id, str) or not self.actor_user_id:
            raise ValueError("LeaderVerdict.actor_user_id must be a non-empty str")
        # ``summary`` may be empty but must be a string.
        if not isinstance(self.summary, str):
            raise ValueError("LeaderVerdict.summary must be a str (empty allowed)")

    # Convenience accessors that mirror the pure mappings without leaking
    # enum dispatch logic to callers.
    @property
    def phase(self) -> str:
        return phase_for(self.status)

    @property
    def action(self) -> str:
        return action_for(self.status)


def _isoformat_z(dt: datetime) -> str:
    """Format ``dt`` in ISO-8601 with a trailing Z."""
    iso = dt.isoformat()
    return iso.replace("+00:00", "Z")


def build_adjudication_metadata(
    *,
    verdict: LeaderVerdict,
    prior_metadata: Mapping[str, Any],
    task_title: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the metadata patch persisted after a leader adjudication. Pure.

    Mirrors ``adjudicate_workspace_worker_report`` behavior:

    * copies ``prior_metadata``;
    * clears ``pending_leader_adjudication`` if it was set;
    * stamps ``last_leader_adjudication_status`` and
      ``last_leader_adjudicated_at`` (ISO-8601 Z);
    * rebuilds ``execution_state`` via the same phase/action mapping used by
      the runtime code.

    The ``now`` parameter is injected for test determinism; production
    callers may omit it to default to ``datetime.now(UTC)``.

    The caller of this function is responsible for calling
    ``_build_execution_state`` outside this module and merging its output in
    — we keep this helper focused on the leader-verdict-only fields and
    return a dict the caller can update with ``execution_state``.
    """
    stamped_at = _isoformat_z(now if now is not None else datetime.now(UTC))

    metadata: dict[str, Any] = dict(prior_metadata)
    if metadata.get(PENDING_LEADER_ADJUDICATION) is True:
        metadata[PENDING_LEADER_ADJUDICATION] = False
    metadata[LAST_LEADER_ADJUDICATION_STATUS] = verdict.status.value
    metadata["last_leader_adjudicated_at"] = stamped_at

    # Callers that need the execution_state fragment compose it themselves
    # using phase_for / action_for / execution_state_reason; they own the
    # execution_state builder (which depends on infrastructure-level state
    # we do not import here).
    return metadata


def execution_state_reason(*, verdict: LeaderVerdict, task_title: str) -> str:
    """Compose the ``reason`` string passed to ``_build_execution_state``.

    Pure. Keeps the existing reason format:
    ``workspace_goal_runtime.leader_adjudication.<status>:<summary-or-title>``.
    """
    return (
        "workspace_goal_runtime.leader_adjudication."
        f"{verdict.status.value}:{verdict.summary or task_title}"
    )
