"""Project-scoped My Work and Activity read-state endpoints."""

import uuid
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.activity_read_state import (
    ActivityReadEntry,
    ActivityReadStateResponse,
    UpdateActivityReadStateRequest,
)
from src.application.schemas.project_my_work import ProjectMyWorkResponse
from src.application.services.project_my_work_service import (
    ProjectMyWorkAccessDeniedError,
    ProjectMyWorkService,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    ActivityReadReceiptModel,
    Project,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_my_work_reader import (
    SqlProjectMyWorkReader,
)
from src.infrastructure.i18n import gettext as _

router = APIRouter(prefix="/api/v1/projects", tags=["project-my-work"])


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _require_project_scope(
    db: AsyncSession,
    *,
    project_id: str,
    user_id: str,
) -> Project:
    result = await db.execute(
        refresh_select_statement(
            select(Project)
            .where(
                Project.id == project_id,
                exists(
                    select(UserProject.id).where(
                        UserProject.project_id == Project.id,
                        UserProject.user_id == user_id,
                    )
                ),
                exists(
                    select(UserTenant.id).where(
                        UserTenant.tenant_id == Project.tenant_id,
                        UserTenant.user_id == user_id,
                    )
                ),
            )
            .limit(1)
        )
    )
    project = cast(Project | None, result.scalar_one_or_none())
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Project access denied"),
        )
    return project


@router.get("/{project_id}/my-work", response_model=ProjectMyWorkResponse)
async def list_project_my_work(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectMyWorkResponse:
    """List current persisted execution authorities visible to the caller."""

    service = ProjectMyWorkService(SqlProjectMyWorkReader(db))
    try:
        return await service.list_for_project(project_id=project_id, user_id=current_user.id)
    except ProjectMyWorkAccessDeniedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Project access denied"),
        ) from error


@router.get(
    "/{project_id}/activity/read-state",
    response_model=ActivityReadStateResponse,
)
async def get_activity_read_state(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActivityReadStateResponse:
    """Return the caller's server-authoritative Activity receipts."""

    project = await _require_project_scope(
        db,
        project_id=project_id,
        user_id=current_user.id,
    )
    result = await db.execute(
        refresh_select_statement(
            select(ActivityReadReceiptModel)
            .where(
                ActivityReadReceiptModel.tenant_id == project.tenant_id,
                ActivityReadReceiptModel.project_id == project.id,
                ActivityReadReceiptModel.user_id == current_user.id,
            )
            .order_by(ActivityReadReceiptModel.entry_id.asc())
        )
    )
    rows = result.scalars().all()
    return ActivityReadStateResponse(
        project_id=project.id,
        entries=[
            ActivityReadEntry(
                entry_id=row.entry_id,
                entry_revision=row.entry_revision,
                read_at=row.read_at,
            )
            for row in rows
        ],
        authority_revision=max((row.revision for row in rows), default=0),
    )


@router.put(
    "/{project_id}/activity/read-state",
    response_model=ActivityReadStateResponse,
)
async def put_activity_read_state(
    project_id: str,
    body: UpdateActivityReadStateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActivityReadStateResponse:
    """Merge offline receipts by explicit entry revision and read time."""

    project = await _require_project_scope(
        db,
        project_id=project_id,
        user_id=current_user.id,
    )
    # Receipt rows do not exist for a caller's first write, so locking only the
    # receipt query cannot serialize concurrent devices.  The membership row is
    # stable for the lifetime of this project scope and provides a per-user,
    # per-project revision lock before any authority revision is calculated.
    membership_result = await db.execute(
        select(UserProject.id)
        .where(
            UserProject.project_id == project.id,
            UserProject.user_id == current_user.id,
        )
        .with_for_update()
    )
    if membership_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Project access denied"),
        )
    entry_ids = [item.entry_id for item in body.entries]
    if len(entry_ids) != len(set(entry_ids)):
        raise HTTPException(status_code=422, detail=_("Activity entry IDs must be unique"))
    known_projection = await ProjectMyWorkService(SqlProjectMyWorkReader(db)).list_for_project(
        project_id=project.id,
        user_id=current_user.id,
    )
    known_entry_ids = {item.id for item in known_projection.items}
    if set(entry_ids) - known_entry_ids:
        raise HTTPException(
            status_code=422,
            detail=_("Activity entries must belong to the current project projection"),
        )
    existing_result = await db.execute(
        refresh_select_statement(
            select(ActivityReadReceiptModel)
            .where(
                ActivityReadReceiptModel.tenant_id == project.tenant_id,
                ActivityReadReceiptModel.project_id == project.id,
                ActivityReadReceiptModel.user_id == current_user.id,
            )
            .with_for_update()
        )
    )
    existing_rows = existing_result.scalars().all()
    existing_by_id = {row.entry_id: row for row in existing_rows}
    revision_result = await db.execute(
        refresh_select_statement(
            select(func.max(ActivityReadReceiptModel.revision)).where(
                ActivityReadReceiptModel.tenant_id == project.tenant_id,
                ActivityReadReceiptModel.project_id == project.id,
                ActivityReadReceiptModel.user_id == current_user.id,
            )
        )
    )
    authority_revision = int(revision_result.scalar_one_or_none() or 0)
    if (
        body.expected_authority_revision is not None
        and body.expected_authority_revision != authority_revision
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("Activity read-state revision conflict"),
        )
    now = datetime.now(UTC)
    for entry in body.entries:
        existing = existing_by_id.get(entry.entry_id)
        if existing is None:
            authority_revision += 1
            row = ActivityReadReceiptModel(
                id=str(uuid.uuid4()),
                tenant_id=project.tenant_id,
                project_id=project.id,
                user_id=current_user.id,
                entry_id=entry.entry_id,
                entry_revision=entry.entry_revision,
                revision=authority_revision,
                read_at=entry.read_at,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            existing_by_id[entry.entry_id] = row
            continue
        next_entry_revision = max(existing.entry_revision, entry.entry_revision)
        next_read_at = max(_utc(existing.read_at), _utc(entry.read_at))
        if next_entry_revision == existing.entry_revision and next_read_at == existing.read_at:
            continue
        authority_revision += 1
        existing.entry_revision = next_entry_revision
        existing.read_at = next_read_at
        existing.revision = authority_revision
        existing.updated_at = now
    await db.commit()
    return await get_activity_read_state(
        project_id=project.id,
        current_user=current_user,
        db=db,
    )
