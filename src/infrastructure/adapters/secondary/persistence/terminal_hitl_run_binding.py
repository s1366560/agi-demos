"""Exact terminal run association for persisted HITL requests; active retries take precedence."""

from sqlalchemy import SQLColumnExpression, exists, false
from sqlalchemy.sql.elements import ColumnElement

from src.infrastructure.adapters.secondary.persistence.models import AgentRunAuthorityModel


def terminal_hitl_run_binding(
    *,
    tenant_id: str | SQLColumnExpression[str | None] | None,
    project_id: str | SQLColumnExpression[str | None] | None,
    conversation_id: str | SQLColumnExpression[str | None] | None,
    message_id: str | SQLColumnExpression[str | None] | None,
) -> ColumnElement[bool]:
    """Only retire strongly message-bound requests when no matching run remains active."""
    if message_id is None:
        return false()
    scope = (
        AgentRunAuthorityModel.tenant_id == tenant_id,
        AgentRunAuthorityModel.project_id == project_id,
        AgentRunAuthorityModel.conversation_id == conversation_id,
        AgentRunAuthorityModel.message_id == message_id,
    )
    return exists().where(
        *scope, AgentRunAuthorityModel.status.in_(("completed", "failed", "cancelled"))
    ) & ~exists().where(*scope, AgentRunAuthorityModel.status.in_(("queued", "running")))
