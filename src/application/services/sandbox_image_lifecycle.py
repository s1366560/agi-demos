"""Explicit sandbox image staleness and migration planning.

The running container is identified by the digest recorded on its labels.
A mismatch is reported as stale. Replacing that container requires a human
request and no active run. This module does not build or recreate containers.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

SOURCE_DIGEST_LABEL = "org.memstack.sandbox.source_digest"
ACTIVE_RUN_LABEL = "org.memstack.sandbox.active_run"


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


def automatic_rebuild_allowed(*, active_run: bool) -> bool:
    """Health recovery may replace an idle container. A live run blocks it."""
    return not active_run


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
