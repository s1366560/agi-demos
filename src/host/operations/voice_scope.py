"""Bind cloud microphone sessions to the caller's live project conversation."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
    UserTenant,
)


async def voice_conversation_tenant(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_id: str | None,
    project_id: str,
    conversation_id: str,
) -> str | None:
    latest_target = (
        select(AgentRunAuthorityModel.execution_target)
        .where(
            AgentRunAuthorityModel.tenant_id == Conversation.tenant_id,
            AgentRunAuthorityModel.project_id == Conversation.project_id,
            AgentRunAuthorityModel.conversation_id == Conversation.id,
        )
        .order_by(AgentRunAuthorityModel.created_at.desc(), AgentRunAuthorityModel.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    query = (
        select(Conversation.tenant_id)
        .join(UserTenant, UserTenant.tenant_id == Conversation.tenant_id)
        .where(
            UserTenant.user_id == user_id,
            Conversation.user_id == user_id,
            Conversation.project_id == project_id,
            Conversation.id == conversation_id,
            func.coalesce(Conversation.meta["execution_target"].as_string(), "cloud") == "cloud",
            func.coalesce(latest_target, "cloud") == "cloud",
        )
    )
    if tenant_id is not None:
        query = query.where(Conversation.tenant_id == tenant_id)
    tenant: str | None = await db.scalar(query)
    return tenant
