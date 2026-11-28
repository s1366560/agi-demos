"""Shared structural authority checks for Cloud run routers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from src.application.services.agent.run_input_dispatch import _canonical_hash
from src.host.identity.run_access import load_scoped_run as _load_scoped_run
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentRunAuthorityModel,
)


def _explicit_change_payloads(event: AgentExecutionEvent) -> list[dict[str, Any]]:
    data = dict(event.event_data)
    changes = data.get("changes")
    if isinstance(changes, list):
        return [dict(item) for item in changes if isinstance(item, dict)]
    tool_input = data.get("tool_input")
    if isinstance(tool_input, dict) and _has_explicit_change_shape(tool_input):
        return [dict(tool_input)]
    if _has_explicit_change_shape(data):
        return [data]
    return []


def _has_explicit_change_shape(payload: dict[str, Any]) -> bool:
    """Reject generic file activity unless a persisted change marker is present."""

    return (
        isinstance(payload.get("hunk_id"), str)
        or isinstance(payload.get("patch_digest"), str)
        or isinstance(payload.get("hunks"), list)
        or (
            isinstance(payload.get("file_path") or payload.get("path"), str)
            and any(
                isinstance(payload.get(key), int) and not isinstance(payload.get(key), bool)
                for key in ("additions", "deletions")
            )
        )
    )


SessionBaselineFailure = Literal[
    "session_baseline_unavailable",
    "session_baseline_environment_mismatch",
]

_SESSION_WORKSPACE_KEYS = ("repository_root", "workspace_path")


@dataclass(frozen=True)
class SessionBaseline:
    """Session-level change anchor derived from persisted run environments."""

    environment_id: str | None
    repository_root: str | None
    workspace_path: str | None
    branch: str | None
    base_revision: str


def _run_environment(run: AgentRunAuthorityModel) -> Mapping[str, Any]:
    environment = run.authorization_snapshot.get("environment")
    if not isinstance(environment, Mapping):
        return {}
    return environment


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def resolve_session_baseline(
    runs: Sequence[AgentRunAuthorityModel],
) -> SessionBaseline | SessionBaselineFailure:
    """Anchor a session-scoped change view to the first run that touched a workspace.

    ``runs`` must be ordered by creation. The anchor is the earliest run with a
    persisted ``environment`` binding; its ``base_commit`` is the honest session
    baseline. The view fails closed when the first workspace run recorded no
    base commit, when no run touched a workspace at all, or when the session's
    runs span multiple repository roots or workspace paths — in those cases a
    single session diff cannot be produced honestly.
    """

    anchor: SessionBaseline | None = None
    for run in runs:
        environment = _run_environment(run)
        if not environment:
            continue
        if anchor is None:
            base_commit = _optional_str(environment.get("base_commit"))
            if base_commit is None:
                return "session_baseline_unavailable"
            anchor = SessionBaseline(
                environment_id=_optional_str(environment.get("id")),
                repository_root=_optional_str(environment.get("repository_root")),
                workspace_path=_optional_str(environment.get("workspace_path")),
                branch=_optional_str(environment.get("branch")),
                base_revision=base_commit,
            )
            continue
        for key in _SESSION_WORKSPACE_KEYS:
            anchored = getattr(anchor, key)
            candidate = _optional_str(environment.get(key))
            if anchored is not None and candidate is not None and candidate != anchored:
                return "session_baseline_environment_mismatch"
    if anchor is None:
        return "session_baseline_unavailable"
    return anchor


__all__ = [
    "SessionBaseline",
    "SessionBaselineFailure",
    "_canonical_hash",
    "_explicit_change_payloads",
    "_load_scoped_run",
    "resolve_session_baseline",
]
