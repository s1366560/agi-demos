"""Read models for the project-scoped My Work queue."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

MyWorkAuthorityKind = Literal["desktop_run", "workspace_attempt", "hitl_request"]
MyWorkCapabilityMode = Literal["work", "code"]
MyWorkGroup = Literal["needs_input", "needs_approval", "running", "ready_review"]
MyWorkStatus = Literal["running", "failed", "needs_input", "needs_approval"]
MyWorkRequiredAction = Literal[
    "provide_input",
    "review_approval",
    "observe",
    "inspect_failure",
]
MyWorkPermissionProfile = Literal["read_only", "workspace_write", "full_access"]


class ProjectWorkItem(BaseModel):
    """One persisted authority currently requiring attention or observation."""

    id: str
    authority_kind: MyWorkAuthorityKind
    authority_id: str
    run_id: str | None = None
    conversation_id: str
    workspace_id: str
    project_id: str
    title: str
    capability_mode: MyWorkCapabilityMode | None = None
    group: MyWorkGroup
    status: MyWorkStatus
    required_action: MyWorkRequiredAction
    revision: int | None = None
    permission_profile: MyWorkPermissionProfile | None = None
    environment: str | None = None
    error: str | None = None
    attempt_number: int | None = None
    created_at: datetime
    updated_at: datetime
    last_heartbeat_at: datetime | None = None


class ProjectMyWorkResponse(BaseModel):
    """Project-scoped My Work response."""

    project_id: str
    items: list[ProjectWorkItem]
    total: int
