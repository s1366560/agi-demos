"""Persisted ownership and project membership for cloud and device runs."""

from fastapi import HTTPException
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    PROJECT_EXECUTOR_ROLES,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
    Project,
    UserProject,
    UserTenant,
)
from src.infrastructure.i18n import gettext as _


async def load_owned_conversation(
    db: AsyncSession, *, conversation_id: str, user_id: str, lock: bool = False, write: bool = False
) -> Conversation:
    membership = select(UserProject.id).where(
        UserProject.project_id == Conversation.project_id, UserProject.user_id == user_id
    )
    if write:
        membership = membership.where(UserProject.role.in_(PROJECT_EXECUTOR_ROLES))
    statement = (
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            exists(
                select(Project.id).where(
                    Project.id == Conversation.project_id,
                    Project.tenant_id == Conversation.tenant_id,
                )
            ),
            exists(membership),
            exists(
                select(UserTenant.id).where(
                    UserTenant.tenant_id == Conversation.tenant_id,
                    UserTenant.user_id == user_id,
                )
            ),
        )
        .limit(1)
    )
    if lock:
        statement = statement.with_for_update()
    result = await db.execute(refresh_select_statement(statement))
    conversation: Conversation | None = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=403, detail=_("Agent run access denied"))
    return conversation


async def load_scoped_run(
    db: AsyncSession,
    *,
    run_id: str,
    user_id: str,
    lock: bool = False,
    write: bool = False,
) -> tuple[AgentRunAuthorityModel, Conversation]:
    run_statement = select(AgentRunAuthorityModel).where(AgentRunAuthorityModel.id == run_id)
    if lock:
        run_statement = run_statement.with_for_update()
    run_result = await db.execute(refresh_select_statement(run_statement))
    run = run_result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail=_("Agent run not found"))
    conversation = await load_owned_conversation(
        db, conversation_id=run.conversation_id, user_id=user_id, lock=lock, write=write
    )
    if conversation.project_id != run.project_id or conversation.tenant_id != run.tenant_id:
        raise HTTPException(status_code=403, detail=_("Agent run access denied"))
    return run, conversation
