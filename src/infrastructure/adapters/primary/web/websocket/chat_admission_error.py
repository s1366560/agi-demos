"""Durable host-owned admission failures before a private runtime is available."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import exists, select

from src.domain.model.agent import AgentExecutionEvent
from src.infrastructure.adapters.secondary.persistence.agent_run_settlement import settle_agent_run
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
    Project,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    SqlAgentExecutionEventRepository,
)


async def persist_chat_admission_error(
    *,
    user_id: str,
    tenant_id: str,
    project_id: str,
    conversation_id: str,
    message_id: str,
    data: dict[str, str],
) -> dict[str, str | int]:
    """Record an authorized failure without committing the caller's turn claim."""
    now = datetime.now(UTC)
    event_time_us = int(now.timestamp() * 1_000_000)
    enriched: dict[str, str | int] = {
        **data,
        "message_id": message_id,
        "event_time_us": event_time_us,
        "event_counter": 0,
    }
    async with async_session_factory() as session:
        # Admission may have failed before authorization or during remote archive
        # loading. Recheck durable ownership and membership before writing history.
        allowed = await session.scalar(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.tenant_id == tenant_id,
                Conversation.project_id == project_id,
                exists(
                    select(Project.id).where(
                        Project.id == project_id, Project.tenant_id == tenant_id
                    )
                ),
                exists(
                    select(UserProject.id).where(
                        UserProject.user_id == user_id, UserProject.project_id == project_id
                    )
                ),
                exists(
                    select(UserTenant.id).where(
                        UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id
                    )
                ),
            )
        )
        if allowed is None:
            return enriched
        result = await session.execute(
            select(AgentRunAuthorityModel)
            .where(
                AgentRunAuthorityModel.id == message_id,
                AgentRunAuthorityModel.message_id == message_id,
                AgentRunAuthorityModel.tenant_id == tenant_id,
                AgentRunAuthorityModel.project_id == project_id,
                AgentRunAuthorityModel.conversation_id == conversation_id,
                AgentRunAuthorityModel.run_kind == "chat",
            )
            .with_for_update()
        )
        run = result.scalar_one_or_none()
        if run is not None and run.status == "queued":
            run.status = "failed"
            run.revision += 1
            run.updated_at = now
            run.completed_at = now
            run.error = data.get("message")
            enriched.update(run_id=run.id, run_revision=run.revision, status="failed")
            await settle_agent_run(
                session,
                run=run,
                started_at=run.created_at,
                succeeded=False,
                completed_at=now,
            )
        await SqlAgentExecutionEventRepository(session).save(
            AgentExecutionEvent(
                id=str(uuid4()),
                conversation_id=conversation_id,
                message_id=message_id,
                event_type="error",
                event_data=enriched,
                event_time_us=event_time_us,
                event_counter=0,
                created_at=now,
            )
        )
        await session.commit()
    return enriched
