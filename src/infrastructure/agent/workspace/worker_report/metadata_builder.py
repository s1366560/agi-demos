"""Pure-logic builder for worker-report metadata patches (P2d M6).

This module encapsulates the metadata-shuffling portion of
:func:`workspace_goal_runtime.apply_workspace_worker_report` — lines that
previously forced the caller to suppress ``C901 / PLR0912 / PLR0915`` lint
complaints.

The builder is side-effect-free apart from reading the clock (which can be
injected via ``now=`` for deterministic testing).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttemptStatus,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    CURRENT_ATTEMPT_ID,
    CURRENT_ATTEMPT_WORKER_BINDING_ID,
    EXECUTION_STATE,
    LAST_WORKER_REPORT_SUMMARY,
    PENDING_LEADER_ADJUDICATION,
)

from ..workspace_goal_runtime import (
    _WORKER_TERMINAL_REPORT_TYPES,
    _build_execution_state,
    _build_worker_report_fingerprint,
    _parse_worker_report_payload,
)

__all__ = ["WorkerReportPatch", "build_worker_report_patch"]


@dataclass(frozen=True)
class WorkerReportPatch:
    """Result of building a worker-report metadata patch."""

    patch: dict[str, Any] = field(default_factory=dict)
    normalized_summary: str = ""
    merged_artifacts: list[str] = field(default_factory=list)
    merged_verifications: list[str] = field(default_factory=list)
    report_verifications: list[str] = field(default_factory=list)
    fingerprint: str = ""
    duplicate: bool = False


def _prior_list(task_metadata: Mapping[str, Any], key: str) -> list[str]:
    value = task_metadata.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


def build_worker_report_patch(
    *,
    task_metadata: Mapping[str, Any],
    report_type: str,
    summary: str,
    artifacts: Sequence[str],
    report_id: str | None,
    resolved_attempt_id: str,
    resolved_attempt_number: int,
    effective_worker_agent_id: str,
    now: datetime | None = None,
) -> WorkerReportPatch:
    """Build a metadata patch for a worker execution report.

    Preserves ``apply_workspace_worker_report`` behavior: artifacts merge with prior
    ``evidence_refs``, verifications merge with prior
    ``execution_verifications``, ``pending_leader_adjudication`` flips for
    terminal report types, ``last_attempt_status`` + ``execution_state`` are
    populated, and duplicate fingerprints short-circuit.
    """
    if not report_type:
        raise ValueError("report_type must be a non-empty string")
    if not resolved_attempt_id:
        raise ValueError("resolved_attempt_id must be a non-empty string")
    if not effective_worker_agent_id:
        raise ValueError("effective_worker_agent_id must be a non-empty string")

    prior_artifacts = _prior_list(task_metadata, "evidence_refs")
    prior_verifications = _prior_list(task_metadata, "execution_verifications")

    inbound = [str(a) for a in artifacts if a]
    pre_merge_artifacts = list(dict.fromkeys([*prior_artifacts, *inbound]))

    normalized_summary, merged_artifacts, report_verifications = _parse_worker_report_payload(
        report_type=report_type,
        summary=summary,
        artifacts=pre_merge_artifacts,
    )
    fingerprint = _build_worker_report_fingerprint(
        report_type=report_type,
        summary=normalized_summary,
        artifacts=merged_artifacts,
        verifications=report_verifications,
        report_id=report_id,
    )

    if task_metadata.get("last_worker_report_fingerprint") == fingerprint:
        return WorkerReportPatch(
            patch={},
            normalized_summary=normalized_summary,
            merged_artifacts=merged_artifacts,
            merged_verifications=list(dict.fromkeys([*prior_verifications, *report_verifications])),
            report_verifications=report_verifications,
            fingerprint=fingerprint,
            duplicate=True,
        )

    is_terminal = report_type in _WORKER_TERMINAL_REPORT_TYPES
    merged_verifications = list(dict.fromkeys([*prior_verifications, *report_verifications]))
    reported_at = (now or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    worker_binding_id = task_metadata.get("workspace_agent_binding_id")
    if not isinstance(worker_binding_id, str) or not worker_binding_id:
        worker_binding_id = task_metadata.get(CURRENT_ATTEMPT_WORKER_BINDING_ID)
        if not isinstance(worker_binding_id, str) or not worker_binding_id:
            worker_binding_id = None

    patch: dict[str, Any] = {
        "evidence_refs": merged_artifacts,
        "execution_verifications": merged_verifications,
        "last_worker_report_type": report_type,
        LAST_WORKER_REPORT_SUMMARY: normalized_summary,
        "last_worker_report_artifacts": list(merged_artifacts),
        "last_worker_report_verifications": list(report_verifications),
        "last_worker_reported_at": reported_at,
        "last_worker_report_fingerprint": fingerprint,
        PENDING_LEADER_ADJUDICATION: is_terminal,
        CURRENT_ATTEMPT_ID: resolved_attempt_id,
        "last_attempt_id": resolved_attempt_id,
        "current_attempt_number": resolved_attempt_number,
        "last_attempt_status": (
            WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION.value
            if is_terminal
            else WorkspaceTaskSessionAttemptStatus.RUNNING.value
        ),
        EXECUTION_STATE: _build_execution_state(
            phase="in_progress",
            reason=f"workspace_goal_runtime.worker_report.{report_type}:{normalized_summary}",
            action="await_leader_adjudication" if is_terminal else "start",
            actor_id=effective_worker_agent_id,
        ),
    }
    if worker_binding_id:
        patch[CURRENT_ATTEMPT_WORKER_BINDING_ID] = worker_binding_id
    if report_id:
        patch["last_worker_report_id"] = report_id

    return WorkerReportPatch(
        patch=patch,
        normalized_summary=normalized_summary,
        merged_artifacts=merged_artifacts,
        merged_verifications=merged_verifications,
        report_verifications=report_verifications,
        fingerprint=fingerprint,
        duplicate=False,
    )
