"""Explicit sandbox image staleness and migration planning.

``source_digest`` compares container image source bytes recorded on a label.
A mismatch is reported as stale for that image. It does not attest which
tool-server process loaded modules for a call. Replacing a container requires
a human request and no active run. This module does not build or recreate
containers.
"""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

SOURCE_DIGEST_LABEL = "org.memstack.sandbox.source_digest"
ACTIVE_RUN_LABEL = "org.memstack.sandbox.active_run"
IMAGE_DIGEST_SCOPE = (
    "org.memstack.sandbox.source_digest identifies container image source bytes. "
    "It does not attest the Python modules loaded by the tool server process. "
    "File mtime under /opt/sandbox-mcp-venv does not by itself prove that loaded hash. "
    "Runtime attestation has to name the listening process and its loaded component. "
    "Missing .py mappings do not establish an exact in-memory hash."
)


@dataclass(frozen=True, kw_only=True)
class SandboxImageStatus:
    recorded_digest: str | None
    current_digest: str | None
    stale: bool
    reason: str


@dataclass(frozen=True, kw_only=True)
class SandboxMigrationPlan:
    allowed: bool
    refusal: str | None
    sandbox_id: str
    project_id: str
    workspace_path: str
    permission_mode: str
    target_digest: str
    preserve_workspace: bool = True
    recreate_live_container: bool = False
    upgrade_performed: bool = False
    stage: str = "plan_only"


def fingerprint_sources(parts: Mapping[str, bytes]) -> str:
    """Hash named source bytes. The names are part of the digest."""
    hasher = hashlib.sha256()
    for name in sorted(parts):
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(parts[name])
        hasher.update(b"\0")
    return hasher.hexdigest()


def image_status(
    labels: Mapping[str, str],
    current_digest: str | None,
) -> SandboxImageStatus:
    """Compare container image labels. See ``IMAGE_DIGEST_SCOPE`` for the limit."""
    recorded = labels.get(SOURCE_DIGEST_LABEL) or None
    if not recorded or not current_digest:
        return SandboxImageStatus(
            recorded_digest=recorded,
            current_digest=current_digest,
            stale=False,
            reason="unknown",
        )
    stale = recorded != current_digest
    return SandboxImageStatus(
        recorded_digest=recorded,
        current_digest=current_digest,
        stale=stale,
        reason="stale" if stale else "current",
    )


def container_marks_active_run(labels: Mapping[str, str]) -> bool:
    return labels.get(ACTIVE_RUN_LABEL) == "true"


def automatic_rebuild_allowed(*, run_state: str) -> bool:
    """Replace an idle container only. Active and unknown states both refuse."""
    return run_state == "idle"


_ACTIVE_AUTHORITY = ("queued", "running")
_project_run_marks: set[str] = set()


def note_project_run(project_id: str, *, active: bool) -> None:
    """Record a run transition from the canonical authority lifecycle."""
    if not project_id:
        return
    if active:
        _project_run_marks.add(project_id)
        return
    _project_run_marks.discard(project_id)


def project_run_mark(project_id: str) -> bool:
    return project_id in _project_run_marks


async def project_run_state(session_factory: object, project_id: str | None) -> str:
    """Read canonical run authority. A failed read is unknown, not idle."""
    if not project_id:
        return "unknown"
    if project_run_mark(project_id):
        return "active"
    if not callable(session_factory):
        return "unknown"
    try:
        from sqlalchemy import func, select

        from src.infrastructure.adapters.secondary.persistence.models import (
            AgentRunAuthorityModel,
        )

        session = cast("AsyncSession", session_factory())
        try:
            count = await session.scalar(
                select(func.count())
                .select_from(AgentRunAuthorityModel)
                .where(
                    AgentRunAuthorityModel.project_id == project_id,
                    AgentRunAuthorityModel.status.in_(_ACTIVE_AUTHORITY),
                )
            )
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result
    except Exception:
        return "unknown"
    if count is None:
        return "unknown"
    return "active" if int(count) > 0 else "idle"


def plan_explicit_migration(
    *,
    sandbox_id: str,
    project_id: str,
    workspace_path: str,
    permission_mode: str,
    target_digest: str,
    active_run: bool,
    human_requested: bool,
) -> SandboxMigrationPlan:
    """Describe a human-triggered migration that keeps the workspace and permissions."""
    refusal = None
    if not human_requested:
        refusal = "human_request_required"
    elif active_run:
        refusal = "active_run"
    elif not target_digest:
        refusal = "digest_required"
    elif not workspace_path:
        refusal = "workspace_required"
    return SandboxMigrationPlan(
        allowed=refusal is None,
        refusal=refusal,
        sandbox_id=sandbox_id,
        project_id=project_id,
        workspace_path=workspace_path,
        permission_mode=permission_mode,
        target_digest=target_digest,
    )
