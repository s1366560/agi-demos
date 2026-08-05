"""Shared structural authority checks for Cloud run routers."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentRunAuthorityModel,
    Conversation,
    Project,
    UserProject,
    UserTenant,
)
from src.infrastructure.i18n import gettext as _


def _canonical_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _load_scoped_run(
    db: AsyncSession,
    *,
    run_id: str,
    user_id: str,
    lock: bool = False,
) -> tuple[AgentRunAuthorityModel, Conversation]:
    run_statement = select(AgentRunAuthorityModel).where(AgentRunAuthorityModel.id == run_id)
    if lock:
        run_statement = run_statement.with_for_update()
    run_result = await db.execute(refresh_select_statement(run_statement))
    run = run_result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail=_("Agent run not found"))
    statement = (
        select(Conversation)
        .where(
            Conversation.id == run.conversation_id,
            Conversation.project_id == run.project_id,
            Conversation.user_id == user_id,
            exists(
                select(Project.id).where(
                    Project.id == Conversation.project_id,
                    Project.tenant_id == Conversation.tenant_id,
                )
            ),
            exists(
                select(UserProject.id).where(
                    UserProject.project_id == Conversation.project_id,
                    UserProject.user_id == user_id,
                )
            ),
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
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=403, detail=_("Agent run access denied"))
    return run, conversation


def _explicit_change_payloads(event: AgentExecutionEvent) -> list[dict[str, Any]]:
    data = dict(event.event_data)
    changes = data.get("changes")
    if isinstance(changes, list):
        return [dict(item) for item in changes if isinstance(item, dict)]
    tool_input = data.get("tool_input")
    if isinstance(tool_input, dict) and _has_explicit_change_shape(tool_input):
        return [dict(tool_input)]
    if _has_explicit_change_shape(data):
        return [data]
    return []


def _has_explicit_change_shape(payload: dict[str, Any]) -> bool:
    """Reject generic file activity unless a persisted change marker is present."""

    return (
        isinstance(payload.get("hunk_id"), str)
        or isinstance(payload.get("patch_digest"), str)
        or isinstance(payload.get("hunks"), list)
        or (
            isinstance(payload.get("file_path") or payload.get("path"), str)
            and any(
                isinstance(payload.get(key), int) and not isinstance(payload.get(key), bool)
                for key in ("additions", "deletions")
            )
        )
    )


__all__ = ["_canonical_hash", "_explicit_change_payloads", "_load_scoped_run"]
