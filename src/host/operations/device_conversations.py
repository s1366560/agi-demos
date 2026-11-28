"""Cloud-owned journals for device-executed turns, shared by signed Agent pages."""

from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, tuple_

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentRunAuthorityModel,
    Conversation,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


type ConversationId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_:-]{1,128}$")]
type WorkspaceId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]


class ConversationList(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    workspace_id: WorkspaceId | None = None
    conversation_id: ConversationId | None = None


class DeviceConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=500)
    execution_target: Literal["cloud", "local"] = "cloud"
    workspace_id: WorkspaceId | None = None


class ConversationRename(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    conversation_id: ConversationId
    title: str = Field(min_length=1, max_length=500)


class Replay(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    conversation_id: str = Field(min_length=1, max_length=128)
    before_time_us: int | None = Field(default=None, ge=0)
    before_counter: int = Field(default=0, ge=0)


def _owned(ctx: "PackageOperationContext") -> tuple[Any, ...]:
    return (
        Conversation.tenant_id == ctx.scope.tenant_id,
        Conversation.project_id == ctx.scope.project_id,
        Conversation.user_id == ctx.user.id,
    )


async def _require_workspace(ctx: "PackageOperationContext", workspace_id: str) -> None:
    from src.infrastructure.adapters.primary.web.workspace_authority import require_workspace_scope

    await require_workspace_scope(
        ctx.request,
        tenant_id=ctx.scope.tenant_id,
        project_id=ctx.scope.project_id,
        workspace_id=workspace_id,
        user_id=ctx.user.id,
        is_superuser=ctx.user.is_superuser,
    )


async def list_owned(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    filters = ConversationList.model_validate(payload)
    if filters.workspace_id:
        await _require_workspace(ctx, filters.workspace_id)
    placement = (
        select(AgentRunAuthorityModel.execution_target)
        .where(AgentRunAuthorityModel.conversation_id == Conversation.id)
        .order_by(AgentRunAuthorityModel.created_at.desc(), AgentRunAuthorityModel.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    query = select(Conversation, placement).where(*_owned(ctx))
    if filters.workspace_id:
        query = query.where(Conversation.workspace_id == filters.workspace_id)
    if filters.conversation_id:
        query = query.order_by((Conversation.id == filters.conversation_id).desc())
    query = query.order_by(Conversation.created_at.desc(), Conversation.id.desc()).limit(100)
    rows = await ctx.db.execute(refresh_select_statement(query))
    return {
        "items": [
            {
                "id": row.id,
                "title": row.title,
                **({"workspace_id": row.workspace_id} if row.workspace_id else {}),
                "execution_target": target
                or (row.meta.get("execution_target", "cloud") if row.meta else "cloud"),
            }
            for row, target in rows
        ]
    }


async def create_owned(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    body = DeviceConversationCreate.model_validate(payload)
    if body.workspace_id:
        await _require_workspace(ctx, body.workspace_id)
    row = Conversation(
        id=str(uuid4()),
        workspace_id=body.workspace_id,
        project_id=ctx.scope.project_id,
        tenant_id=ctx.scope.tenant_id,
        user_id=ctx.user.id,
        title=body.title,
        meta={"execution_target": body.execution_target},
    )
    ctx.db.add(row)
    await ctx.db.commit()
    return {
        "id": row.id,
        "title": body.title,
        "execution_target": body.execution_target,
        **({"workspace_id": row.workspace_id} if row.workspace_id else {}),
    }


async def rename_owned(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    data = ConversationRename.model_validate(payload)
    row = await ctx.db.scalar(
        select(Conversation).where(*_owned(ctx), Conversation.id == data.conversation_id)
    )
    if row is None:
        raise OptionalBusinessError("forbidden", "conversation unavailable for this project")
    row.title = data.title
    await ctx.db.commit()
    return {"id": data.conversation_id, "title": data.title}


async def local_history(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    request = Replay.model_validate(payload)
    owner = await ctx.db.scalar(
        select(Conversation.id).where(*_owned(ctx), Conversation.id == request.conversation_id)
    )
    if not owner:
        raise OptionalBusinessError("forbidden", "conversation unavailable for this project")
    event = AgentExecutionEvent
    query = select(event).where(
        event.conversation_id == owner,
        event.event_type.in_(("user_message", "assistant_message")),
    )
    if request.before_time_us is not None:
        query = query.where(
            tuple_(event.event_time_us, event.event_counter)
            < (request.before_time_us, request.before_counter)
        )
    latest = (
        await ctx.db.scalars(
            query.order_by(event.event_time_us.desc(), event.event_counter.desc()).limit(101)
        )
    ).all()
    page = list(reversed(latest[:100]))
    messages: list[dict[str, str | int]] = []
    for row in page:
        data = row.event_data
        text = data.get("content")
        if not isinstance(text, str) and isinstance(data.get("payload"), dict):
            text = data["payload"].get("text", data["payload"].get("content"))
        if isinstance(text, str):
            messages.append(
                {
                    "id": row.id,
                    "role": row.event_type,
                    "content": text,
                    "eventTimeUs": row.event_time_us,
                    "timestamp": row.event_time_us // 1000
                    if row.event_time_us
                    else int(row.created_at.timestamp() * 1000),
                }
            )
    return {
        "messages": messages,
        "before": {"before_time_us": page[0].event_time_us, "before_counter": page[0].event_counter}
        if len(latest) > 100
        else None,
    }


DEVICE_HISTORY_OPERATIONS = {
    "app.agent.list": list_owned,
    "app.agent.create": create_owned,
    "app.agent.rename": rename_owned,
    "app.agent.history": local_history,
}
