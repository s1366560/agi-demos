"""Conditional derived-state writes; never insert or modify portable content."""

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import Table, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.memory.processing import MemoryProcessingSource
from src.infrastructure.adapters.secondary.persistence.models import Memory


async def update_memory_processing_status(
    session: AsyncSession, source: MemoryProcessingSource, status: str
) -> bool:
    """Apply only to the exact source version and task, leaving commit to the caller."""
    table = cast(Table, Memory.__table__)
    statement = (
        update(table)
        .where(
            table.c.id == source.memory_id,
            table.c.project_id == source.project_id,
            table.c.version == source.revision,
            table.c.task_id == source.task_id,
        )
        .values(processing_status=status, updated_at=datetime.now(UTC))
        .returning(table.c.id)
    )
    with session.no_autoflush:
        result = await session.execute(statement)
    return result.scalar_one_or_none() is not None
