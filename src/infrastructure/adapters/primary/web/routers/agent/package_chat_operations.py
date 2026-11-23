"""Scoped application capabilities backed by the canonical Agent HTTP and WS authorities."""

from typing import TYPE_CHECKING, Annotated, Any

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    latest_execution_placements,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

from .package_chat_stream import stream_turn

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress

type Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Create(_Input):
    title: str = Field(min_length=1, max_length=500)


class ConversationInput(_Input):
    conversation_id: Identifier


class History(ConversationInput):
    before_time_us: int | None = Field(default=None, ge=0)
    before_counter: int = Field(default=0, ge=0)


class Turn(ConversationInput):
    message_id: Identifier
    message: str = Field(min_length=1, max_length=32000)


class Cancel(ConversationInput):
    run_id: Identifier
    expected_revision: int = Field(ge=1)


async def _own_conversation(ctx: "PackageOperationContext", conversation_id: str) -> None:
    match = await ctx.db.scalar(
        select(Conversation.id).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == ctx.scope.tenant_id,
            Conversation.project_id == ctx.scope.project_id,
            Conversation.user_id == ctx.user.id,
        )
    )
    if match is None:
        raise OptionalBusinessError("forbidden", "conversation unavailable for this project")


async def _canonical(
    ctx: "PackageOperationContext",
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    query: dict[str, int] | None = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ctx.request.app),
        base_url="http://localhost",
        headers={"authorization": ctx.request.headers.get("authorization", "")},
    ) as client:
        reply = await client.request(
            method,
            "/api/v1/agent/" + path,
            params={"project_id": ctx.scope.project_id, **(query or {})},
            json=body,
        )
    if reply.status_code >= 400:
        code = {403: "forbidden", 401: "forbidden", 404: "page_not_found", 409: "conflict"}.get(
            reply.status_code, "runtime_unavailable"
        )
        raise OptionalBusinessError(code, f"Agent authority returned HTTP {reply.status_code}")
    result = reply.json()
    if not isinstance(result, dict):
        raise OptionalBusinessError("runtime_unavailable", "Invalid Agent authority response")
    return result


def _conversation(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in ("id", "title", "execution_target")}


async def list_conversations(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    _Input.model_validate(payload)
    result = await _canonical(ctx, "GET", "conversations")
    return {"items": [_conversation(row) for row in result["items"]]}


async def create(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    data = Create.model_validate(payload)
    return _conversation(
        await _canonical(
            ctx,
            "POST",
            "conversations",
            body={"title": data.title, "project_id": ctx.scope.project_id},
        )
    )


async def history(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    data = History.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    query = (
        {"before_time_us": data.before_time_us, "before_counter": data.before_counter}
        if data.before_time_us is not None
        else None
    )
    result = await _canonical(
        ctx, "GET", f"conversations/{data.conversation_id}/messages", query=query
    )
    # P5 contains tool arguments and execution authorizations as well as messages.
    # Only return the text presentation that this capability promises.
    return {
        "before": {
            "before_time_us": result["first_time_us"],
            "before_counter": result["first_counter"],
        }
        if result["has_more"]
        else None,
        "messages": [
            {"role": row["type"], "content": row["content"]}
            for row in result["timeline"]
            if row.get("type") in {"user_message", "assistant_message"}
            and isinstance(row.get("content"), str)
        ],
    }


async def turn(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    data = Turn.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    placements = await latest_execution_placements(
        ctx.db,
        tenant_id=ctx.scope.tenant_id,
        project_id=ctx.scope.project_id,
        conversation_ids=[data.conversation_id],
    )
    previous = placements.get(data.conversation_id)
    if previous is not None and previous.execution_target == "local":
        raise OptionalBusinessError(
            "forbidden", "Local conversations support read-only cloud replay"
        )
    return await stream_turn(ctx, data.model_dump(), progress)


async def cancel(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    data = Cancel.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    run = await ctx.db.scalar(
        select(AgentRunAuthorityModel.id).where(
            AgentRunAuthorityModel.id == data.run_id,
            AgentRunAuthorityModel.conversation_id == data.conversation_id,
            AgentRunAuthorityModel.tenant_id == ctx.scope.tenant_id,
            AgentRunAuthorityModel.project_id == ctx.scope.project_id,
            AgentRunAuthorityModel.execution_target == "cloud",
        )
    )
    if run is None:
        raise OptionalBusinessError("forbidden", "cloud run unavailable for this conversation")
    result = await _canonical(
        ctx,
        "POST",
        f"runs/{data.run_id}/cancel",
        body={"expected_revision": data.expected_revision},
    )
    return {"status": result["status"]}


AGENT_OPERATIONS = {
    "app.agent.list": list_conversations,
    "app.agent.create": create,
    "app.agent.history": history,
    "app.agent.turn": turn,
    "app.agent.cancel": cancel,
}
