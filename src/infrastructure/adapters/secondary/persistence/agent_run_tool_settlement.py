"""Settle interrupted tool projections under their canonical cancelled run."""

from __future__ import annotations

from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
    ToolExecutionRecord,
)
from src.infrastructure.i18n import gettext as _


async def settle_cancelled_run_tools(db: AsyncSession, *, run: AgentRunAuthorityModel) -> int:
    """Close only this run's unfinished records; preserve every settled result.

    Workers call this in their terminal transaction. An authenticated retry of
    the same cancellation receipt can also repair interrupted legacy settlement.
    The caller owns the transaction and must already have validated run authority.
    """
    if run.status != "cancelled" or run.completed_at is None:
        return 0
    result = await db.execute(
        refresh_select_statement(
            select(ToolExecutionRecord)
            .join(Conversation, Conversation.id == ToolExecutionRecord.conversation_id)
            .where(
                Conversation.id == run.conversation_id,
                Conversation.tenant_id == run.tenant_id,
                Conversation.project_id == run.project_id,
                ToolExecutionRecord.message_id == run.message_id,
                ToolExecutionRecord.status == "running",
                ToolExecutionRecord.completed_at.is_(None),
            )
            .with_for_update(of=ToolExecutionRecord)
        )
    )
    records = result.scalars().all()
    completed_at = run.completed_at
    # SQLite unit tests omit timezone information when loading persisted dates.
    terminal_utc = completed_at.replace(tzinfo=UTC) if completed_at.tzinfo is None else completed_at
    for record in records:
        started_at = record.started_at
        started_utc = started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at
        record.status = "cancelled"
        record.completed_at = completed_at
        record.duration_ms = max(0, int((terminal_utc - started_utc).total_seconds() * 1000))
        record.error = _("Run cancelled before tool completion")
    return len(records)
