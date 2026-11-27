"""Signed workspace collaboration commands backed by the existing Workspace Core authority."""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.domain.model.workspace.blackboard_post import BlackboardPostStatus
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext
    from src.infrastructure.plugins.v2.project_package_execution import Progress

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
Topic = Literal["members", "posts", "tasks"]


class CollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: Identifier
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)


class MemberFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: Identifier | None = None
    role: WorkspaceRole


class PostFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=65536)
    status: BlackboardPostStatus | None = None
    is_pinned: bool | None = None


class TaskFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=65536)
    status: WorkspaceTaskStatus | None = None


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: Identifier
    action: Literal["create", "update", "delete"]
    id: Identifier | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    request_id: UUID
    expected_revision: int = Field(ge=0)


_PATHS: dict[Topic, tuple[str, ...]] = {
    "members": ("members",),
    "posts": ("blackboard", "posts"),
    "tasks": ("tasks",),
}
_FIELDS: dict[Topic, type[BaseModel]] = {
    "members": MemberFields,
    "posts": PostFields,
    "tasks": TaskFields,
}


def _mutation(
    topic: Topic, args: Change
) -> tuple[Literal["POST", "PATCH", "DELETE"], dict[str, Any] | None]:
    creating = args.action == "create"
    if creating != (args.id is None):
        raise ValueError("Invalid item identity")
    if args.action == "delete":
        if args.fields:
            raise ValueError("Unexpected fields")
        return "DELETE", None
    data = _FIELDS[topic].model_validate(args.fields).model_dump(mode="json", exclude_none=True)
    if topic == "tasks" and creating and "status" in data:
        raise ValueError("A new task starts at todo")
    if topic == "members" and ("user_id" in data) != creating:
        raise ValueError("Invalid member identity")
    return ("POST" if creating else "PATCH"), data


def _operation(topic: Topic, *, write: bool) -> Callable[..., Awaitable[dict[str, Any]]]:
    async def invoke(
        ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
    ) -> dict[str, Any]:
        from plugins.business.workspace.guest.commands import collaboration_handler
        from src.host.operations.business_guest.loopback import call_in_guest

        return await call_in_guest(
            ctx, collaboration_handler(topic, write=write), payload, _progress
        )

    return invoke


WORKSPACE_COLLABORATION_OPERATIONS = {
    f"app.workspace.{topic}.{verb}": _operation(topic, write=verb == "write")
    for topic in _PATHS
    for verb in ("read", "write")
}
