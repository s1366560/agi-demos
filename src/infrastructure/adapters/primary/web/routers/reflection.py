"""Read-only API surface for the reflection / playbook loop.

Exposes:
- ``GET /api/v1/projects/{project_id}/playbooks`` — distilled playbooks
- ``GET /api/v1/projects/{project_id}/reflection-verdicts`` — audit log

Both endpoints require the calling user to be a member of the project,
matching the access policy used by ``/api/v1/projects/{id}``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    User,
    UserProject,
)
from src.infrastructure.adapters.secondary.persistence.sql_playbook_repository import (
    SqlPlaybookRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_reflection_verdict_repository import (
    SqlReflectionVerdictRepository,
)
from src.infrastructure.i18n import gettext as _

router = APIRouter(prefix="/api/v1/projects", tags=["reflection"])
logger = logging.getLogger(__name__)


class PlaybookView(BaseModel):
    id: str
    project_id: str
    name: str
    status: str
    trigger: dict[str, Any]
    steps: list[dict[str, Any]]
    hit_count: int
    last_used_at: str | None
    created_at: str
    updated_at: str


class PlaybooksResponse(BaseModel):
    items: list[PlaybookView]


class VerdictView(BaseModel):
    id: str
    project_id: str
    action: str
    playbook_id: str | None
    rationale: str
    proposed_payload: dict[str, Any] | None
    created_at: str


class VerdictsResponse(BaseModel):
    items: list[VerdictView]


async def _ensure_member(
    *, db: AsyncSession, user_id: str, project_id: str
) -> None:
    result = await db.execute(
        refresh_select_statement(
            select(UserProject).where(
                and_(
                    UserProject.user_id == user_id,
                    UserProject.project_id == project_id,
                )
            )
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied to project"),
        )


@router.get(
    "/{project_id}/playbooks",
    response_model=PlaybooksResponse,
)
async def list_playbooks(
    project_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlaybooksResponse:
    """Return all playbooks visible to the caller for this project."""
    await _ensure_member(db=db, user_id=current_user.id, project_id=project_id)
    repo = SqlPlaybookRepository(db)
    playbooks = await repo.find_by_project(project_id, limit=limit)
    items = [
        PlaybookView(
            id=p.id,
            project_id=p.project_id,
            name=p.name,
            status=p.status.value,
            trigger={
                "description": p.trigger.description,
                "friction_kinds": list(p.trigger.friction_kinds),
                "lane_transitions": [list(pair) for pair in p.trigger.lane_transitions],
            },
            steps=[
                {
                    "order": s.order,
                    "instruction": s.instruction,
                    "rationale": s.rationale,
                }
                for s in p.steps
            ],
            hit_count=p.hit_count,
            last_used_at=p.last_used_at.isoformat() if p.last_used_at else None,
            created_at=p.created_at.isoformat(),
            updated_at=p.updated_at.isoformat(),
        )
        for p in playbooks
    ]
    return PlaybooksResponse(items=items)


@router.get(
    "/{project_id}/reflection-verdicts",
    response_model=VerdictsResponse,
)
async def list_reflection_verdicts(
    project_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VerdictsResponse:
    """Return the most-recent reflection verdicts for this project."""
    await _ensure_member(db=db, user_id=current_user.id, project_id=project_id)
    repo = SqlReflectionVerdictRepository(db)
    rows = await repo.list_for_project(project_id, limit=limit)
    items = [
        VerdictView(
            id=row.id,
            project_id=row.project_id,
            action=row.verdict.action.value,
            playbook_id=row.verdict.playbook_id,
            rationale=row.verdict.rationale,
            proposed_payload=(
                dict(row.verdict.proposed_playbook)
                if row.verdict.proposed_playbook is not None
                else None
            ),
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
    return VerdictsResponse(items=items)


__all__ = ["router"]
