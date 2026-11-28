"""Workspace command models and allow-lists. This module does not open the relational store."""

from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.infrastructure.i18n import gettext as _

_SCOPED = frozenset(
    {
        "",
        "members",
        "agents",
        "objectives",
        "genes",
        "messages",
        "collaboration/authority",
        "blackboard/posts",
        "blackboard/posts/:id/replies",
        "blackboard/execution-diagnostics",
        "blackboard/files",
    }
)
_ROOT = frozenset(
    {
        "tasks",
        "plan",
        "topology/nodes",
        "topology/edges",
        "autonomy/attentions",
        "tasks/:id/experience",
        "tasks/:id/execution-session",
    }
)
_WRITES = {
    "POST": frozenset(
        {
            "blackboard/posts",
            "blackboard/posts/:id/replies",
            "blackboard/posts/:id/pin",
            "blackboard/posts/:id/unpin",
            "objectives",
            "objectives/:id/project-to-task",
            "genes",
            "tasks",
            "topology/nodes",
            "topology/edges",
            "messages",
            "collaboration/mutations",
            "members",
            "agents",
            "autonomy/tick",
            "tasks/:id/recovery-actions",
            "tasks/:id/assign-agent",
            "tasks/:id/unassign-agent",
            "plan/outbox/:id/retry",
            "plan/recover-stale-attempts",
            "plan/nodes/:id/request-replan",
            "plan/nodes/:id/reopen",
            "plan/nodes/:id/accept-review",
            "plan/iteration/pause",
            "plan/iteration/resume",
            "plan/iteration/trigger-next",
            "plan/delivery/run-pipeline",
            "plan/delivery/regenerate-contract",
            "blackboard/files/mkdir",
            "blackboard/files/:id/copy",
        }
    ),
    "PATCH": frozenset(
        {
            "",
            "members/:id",
            "agents/:id",
            "blackboard/files/:id",
            "blackboard/posts/:id",
            "blackboard/posts/:id/replies/:id",
            "objectives/:id",
            "genes/:id",
            "tasks/:id",
            "topology/nodes/:id",
            "topology/edges/:id",
        }
    ),
    "DELETE": frozenset(
        {
            "",
            "members/:id",
            "agents/:id",
            "blackboard/files/:id",
            "blackboard/posts/:id",
            "blackboard/posts/:id/replies/:id",
            "objectives/:id",
            "genes/:id",
            "tasks/:id",
            "topology/nodes/:id",
            "topology/edges/:id",
        }
    ),
}

WorkspaceUseCase = Literal["general", "programming", "conversation", "research", "operations"]
WorkspaceCollaborationMode = Literal[
    "single_agent", "multi_agent_shared", "multi_agent_isolated", "autonomous"
]
WorkspaceType = Literal["general", "software_development", "research", "operations"]
VerificationGrade = Literal["pass", "warn", "fail"]


class _Completion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    debug: dict[str, Any] | None = None
    allow_internal_task_artifacts: bool | None = None
    required_artifact_prefixes: list[str] | None = None
    requires_external_artifact: bool | None = None
    minimum_verification_grade: VerificationGrade | None = None


class _Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    debug: dict[str, Any] | None = None
    workspace_type: WorkspaceType | None = None
    completion_policy: _Completion | None = None


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    workspace_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    include_revision: bool = False


class CreateWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    use_case: WorkspaceUseCase | None = None
    collaboration_mode: WorkspaceCollaborationMode | None = None
    autonomy_profile: _Profile | None = None
    sandbox_code_root: str | None = None
    request_id: UUID


class UpdateWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)
    workspace_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    is_archived: bool | None = None
    metadata: dict[str, Any] | None = None
    request_id: UUID
    expected_revision: int = Field(ge=0)


class SummaryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary_for: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")


class Card(BaseModel):
    tenant_id: str
    project_id: str
    created_by: str
    id: str
    name: str
    office_status: str
    is_archived: bool
    description: str | None = None
    created_at: str
    updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CatalogSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=50)
    search: str = Field(default="", max_length=250)


class RosterPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


def directory_card(card: Card, scope: object) -> dict[str, Any]:
    tenant, project = scope.tenant_id, scope.project_id
    if (card.tenant_id, card.project_id) != (tenant, project):
        raise HTTPException(403, _("Workspace directory scope mismatch"))
    data = card.model_dump(exclude={"metadata"})
    data["metadata"] = {
        key: value
        for key in (
            "workspace_use_case",
            "workspace_type",
            "collaboration_mode",
            "agent_conversation_mode",
            "sandbox_code_root",
        )
        if isinstance(value := card.metadata.get(key), str)
    }
    context = card.metadata.get("code_context")
    if isinstance(context, dict) and isinstance(root := context.get("sandbox_code_root"), str):
        data["metadata"]["code_context"] = {"sandbox_code_root": root}
    return data
