"""Tenant-scoped session list, create, and open. No project is required to list."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from src.host.operations.agent_package.bridge import HostBridge
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    UserProject,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError


async def perform(bridge: HostBridge, op: str, payload: dict[str, Any]) -> dict[str, Any]:
    if bridge.project_id:
        raise OptionalBusinessError("forbidden", "Tenant installation required")
    if op == "list":
        limit = payload.get("limit", 50)
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise OptionalBusinessError("invalid_input", "invalid session page")
        rows = (
            await bridge.ctx.db.scalars(
                select(Conversation)
                .where(
                    Conversation.tenant_id == bridge.tenant_id,
                    Conversation.user_id == bridge.user_id,
                )
                .order_by(Conversation.updated_at.desc())
                .limit(limit)
            )
        ).all()
        return {
            "items": [
                {
                    "id": row.id,
                    "title": row.title,
                    "project_id": row.project_id,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }
                for row in rows
            ]
        }
    if op == "open":
        conversation_id = payload.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise OptionalBusinessError("invalid_input", "conversation is required")
        row = await bridge.ctx.db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == bridge.tenant_id,
                Conversation.user_id == bridge.user_id,
            )
        )
        if row is None:
            raise OptionalBusinessError("forbidden", "conversation unavailable for this tenant")
        return {"id": row.id, "title": row.title, "project_id": row.project_id}
    if op == "create":
        project_id = payload.get("project_id")
        title = payload.get("title")
        if not isinstance(project_id, str) or not project_id:
            raise OptionalBusinessError("invalid_input", "project is required")
        if not isinstance(title, str) or not 1 <= len(title) <= 500:
            raise OptionalBusinessError("invalid_input", "title is required")
        member = await bridge.ctx.db.scalar(
            select(UserProject.id).where(
                UserProject.user_id == bridge.user_id,
                UserProject.project_id == project_id,
            )
        )
        if member is None:
            raise OptionalBusinessError("forbidden", "project unavailable for this tenant")
        saved = bridge.project_id
        bridge.project_id = project_id
        try:
            created = await bridge.http(
                "POST",
                "conversations",
                body={"title": title, "project_id": project_id},
            )
        finally:
            bridge.project_id = saved
        return {
            "id": created["id"],
            "title": created.get("title", title),
            "project_id": project_id,
        }
    raise OptionalBusinessError("forbidden", "unsupported tenant session operation")
