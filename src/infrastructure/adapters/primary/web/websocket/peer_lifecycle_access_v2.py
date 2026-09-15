"""Fresh owner and canonical-run checks for parent-visible peer terminal notifications."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentRunAuthorityModel,
    Conversation,
    User,
)

if TYPE_CHECKING:
    from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext


async def peer_lifecycle_access_v2(  # noqa: PLR0911
    context: MessageContext, project_id: str, message: dict[str, Any]
) -> bool:
    raw_event = message.get("data")
    if not isinstance(raw_event, dict):
        return False
    event = cast(dict[str, Any], raw_event)
    if event.get("type") not in {"agent_completed", "agent_stopped"}:
        return False
    raw_data = event.get("data")
    if not isinstance(raw_data, dict):
        return False
    data = cast(dict[str, Any], raw_data)
    parent_id, child_id, run_id, spawn_id = (
        data.get("parent_session_id"),
        data.get("child_session_id"),
        data.get("child_run_id"),
        data.get("spawn_id"),
    )
    if not all(isinstance(x, str) and x.strip() for x in (parent_id, child_id, run_id, spawn_id)):
        return False
    if data.get("session_id") != child_id or message.get("conversation_id") != parent_id:
        return False
    expected_type = "agent_stopped" if data.get("status") == "cancelled" else "agent_completed"
    if event["type"] != expected_type or data.get("status") not in {
        "completed",
        "failed",
        "cancelled",
    }:
        return False
    async with context.fresh_db_context() as scoped:
        parent = await scoped.db.get(Conversation, parent_id)
        child = await scoped.db.get(Conversation, child_id)
        user = await scoped.db.get(User, context.user_id)
        run = await scoped.db.get(AgentRunAuthorityModel, run_id)
        if (
            parent is None
            or child is None
            or user is None
            or not user.is_active
            or run is None
            or child.parent_conversation_id != parent.id
            or run.conversation_id != child.id
            or run.status != data["status"]
            or run.tenant_id != context.tenant_id
            or run.project_id != project_id
        ):
            return False
        if any(
            c.tenant_id != context.tenant_id
            or c.project_id != project_id
            or c.user_id != context.user_id
            for c in (parent, child)
        ):
            return False
        rows = await scoped.db.scalars(
            select(AgentExecutionEvent.event_data).where(
                AgentExecutionEvent.conversation_id == parent_id,
                AgentExecutionEvent.message_id == f"peer-terminal:{run_id}",
                AgentExecutionEvent.event_type == event["type"],
            )
        )
        return any(
            all(
                row.get(key) == data.get(key)
                for key in (
                    "agent_id",
                    "parent_agent_id",
                    "session_id",
                    "child_run_id",
                    "child_session_id",
                    "parent_session_id",
                    "spawn_id",
                    "status",
                    "success",
                    "result",
                    "artifacts",
                    "source",
                )
            )
            for row in rows
        )
