"""Authoritative tenant/project context used by trusted desktop sessions."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class WorkspaceContextErrorCode(StrEnum):
    """Protocol-stable failure codes shared by desktop identity adapters."""

    INVALID_INPUT = "workspace_context_invalid_input"
    UNAVAILABLE = "workspace_context_unavailable"
    MEMBERSHIP_REQUIRED = "workspace_context_membership_required"
    PROJECT_UNAVAILABLE = "workspace_context_project_unavailable"
    REVISION_CONFLICT = "workspace_context_revision_conflict"
    IDEMPOTENCY_CONFLICT = "workspace_context_idempotency_conflict"
    REVISION_EXHAUSTED = "workspace_context_revision_exhausted"


class WorkspaceContextError(Exception):
    """Typed workspace-context failure safe to map onto the public API contract."""

    def __init__(
        self,
        code: WorkspaceContextErrorCode,
        *,
        expected_revision: int | None = None,
        actual_revision: int | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision


@dataclass(frozen=True, kw_only=True)
class WorkspaceContextSnapshot:
    tenant_id: str
    project_id: str
    revision: int
    updated_at: datetime


@dataclass(frozen=True, kw_only=True)
class WorkspaceContextAccess:
    context: WorkspaceContextSnapshot
    membership_role: str


@dataclass(frozen=True, kw_only=True)
class WorkspaceContextSwitchRequest:
    tenant_id: str
    project_id: str
    expected_revision: int
    idempotency_key: str


@dataclass(frozen=True, kw_only=True)
class WorkspaceContextSwitchOutcome:
    context: WorkspaceContextSnapshot
    changed: bool
