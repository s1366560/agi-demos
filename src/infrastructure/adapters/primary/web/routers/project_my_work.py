"""Project-scoped My Work read endpoint."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.project_my_work import ProjectMyWorkResponse
from src.application.services.project_my_work_service import (
    ProjectMyWorkAccessDeniedError,
    ProjectMyWorkService,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.sql_project_my_work_reader import (
    SqlProjectMyWorkReader,
)
from src.infrastructure.i18n import gettext as _

router = APIRouter(prefix="/api/v1/projects", tags=["project-my-work"])


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
