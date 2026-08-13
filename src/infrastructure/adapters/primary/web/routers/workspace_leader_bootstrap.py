"""Retired platform Workspace autonomy scheduler compatibility surface.

Avernet Workspace Core owns task progression, recovery and its transactional
outbox. These call points remain importable while callers migrate, but no
platform SQL Workspace state is read or written.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.workspace_authority import (
    workspace_core_unavailable_error,
)
from src.infrastructure.adapters.secondary.persistence.models import User


async def maybe_auto_trigger_existing_root_execution(
    *,
    db: AsyncSession,
    workspace_id: str,
    current_user: User,
    request: Request | None = None,
    force: bool = False,
    system_tick: bool = False,
) -> dict[str, Any]:
    """Fail closed because Core is the only autonomy command authority."""
    del db, workspace_id, current_user, request, force, system_tick
    raise workspace_core_unavailable_error()


def schedule_autonomy_tick(workspace_id: str, actor_user_id: str) -> None:
    """Ignore obsolete post-commit ticks; Core outbox schedules progression."""
    del workspace_id, actor_user_id


__all__ = ["maybe_auto_trigger_existing_root_execution", "schedule_autonomy_tick"]
