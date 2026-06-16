"""Prompt template CRUD API endpoints."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.prompt_template import (
    PromptTemplate,
    TemplateVariable,
)
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import (
    get_db,
)
from src.infrastructure.adapters.secondary.persistence.models import Project
from src.infrastructure.adapters.secondary.persistence.sql_prompt_template_repository import (
    SqlPromptTemplateRepository,
)
from src.infrastructure.i18n import gettext as _

from .access import require_tenant_access

logger = logging.getLogger(__name__)
router = APIRouter()


class TemplateVariableSchema(BaseModel):
    name: str
    description: str = ""
    default_value: str = ""
    required: bool = False


class TemplateCreateRequest(BaseModel):
    title: str = Field(..., max_length=200)
    content: str = Field(..., min_length=1)
    category: str = Field(default="general", max_length=50)
    project_id: str | None = None
    variables: list[TemplateVariableSchema] = Field(default_factory=list)
    is_system: bool = False


class TemplateUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content: str | None = None
    category: str | None = Field(default=None, max_length=50)
    variables: list[TemplateVariableSchema] | None = None


class TemplateResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str | None = None
    created_by: str
    title: str
    content: str
    category: str
    variables: list[TemplateVariableSchema]
    is_system: bool
    usage_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


def _to_response(t: PromptTemplate) -> TemplateResponse:
    return TemplateResponse(
        id=t.id,
        tenant_id=t.tenant_id,
        project_id=t.project_id,
        created_by=t.created_by,
        title=t.title,
        content=t.content,
        category=t.category,
        variables=[
            TemplateVariableSchema(
                name=v.name,
                description=v.description,
                default_value=v.default_value,
                required=v.required,
            )
            for v in t.variables
        ],
        is_system=t.is_system,
        usage_count=t.usage_count,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


async def _require_project_scope(
    db: AsyncSession,
    tenant_id: str,
    project_id: str,
) -> None:
    result = await db.execute(
        refresh_select_statement(
            select(Project.id).where(
                Project.id == project_id,
                Project.tenant_id == tenant_id,
            )
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=_("Project not found"))


async def _get_template_or_404(
    repo: SqlPromptTemplateRepository,
    template_id: str,
) -> PromptTemplate:
    template = await repo.find_by_id(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=_("Template not found"))
    return template


async def _require_template_read_access(
    db: AsyncSession,
    current_user: User,
    template: PromptTemplate,
) -> None:
    await require_tenant_access(db, current_user, template.tenant_id)


async def _require_template_write_access(
    db: AsyncSession,
    current_user: User,
    template: PromptTemplate,
) -> None:
    await require_tenant_access(
        db,
        current_user,
        template.tenant_id,
        require_admin=template.is_system,
    )
    if not template.is_system and template.created_by != current_user.id:
        raise HTTPException(status_code=403, detail=_("Not authorized to modify this template"))


@router.post(
    "/templates",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    data: TemplateCreateRequest,
    tenant_id: str = Query(..., description="Tenant ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    """Create a new prompt template."""
    try:
        await require_tenant_access(
            db,
            current_user,
            tenant_id,
            require_admin=data.is_system,
        )
        if data.project_id is not None:
            await _require_project_scope(db, tenant_id, data.project_id)

        repo = SqlPromptTemplateRepository(db)
        template = PromptTemplate(
            tenant_id=tenant_id,
            project_id=data.project_id,
            created_by=current_user.id,
            title=data.title,
            content=data.content,
            category=data.category,
            variables=[
                TemplateVariable(
                    name=v.name,
                    description=v.description,
                    default_value=v.default_value,
                    required=v.required,
                )
                for v in data.variables
            ],
            is_system=data.is_system,
        )
        saved = await repo.save(template)
        await db.commit()
        return _to_response(saved)
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        logger.exception("Error creating template")
        raise HTTPException(status_code=500, detail=_("Failed to create template")) from None


@router.get("/templates", response_model=list[TemplateResponse])
async def list_templates(
    tenant_id: str = Query(..., description="Tenant ID"),
    category: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TemplateResponse]:
    """List prompt templates."""
    try:
        await require_tenant_access(db, current_user, tenant_id)
        repo = SqlPromptTemplateRepository(db)
        if project_id:
            await _require_project_scope(db, tenant_id, project_id)
            templates = await repo.list_by_project(project_id, limit=limit, offset=offset)
        else:
            templates = await repo.list_by_tenant(
                tenant_id,
                category=category,
                limit=limit,
                offset=offset,
            )
        return [_to_response(t) for t in templates]
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error listing templates")
        raise HTTPException(status_code=500, detail=_("Failed to list templates")) from None


@router.get("/templates/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    """Get a specific prompt template."""
    repo = SqlPromptTemplateRepository(db)
    template = await _get_template_or_404(repo, template_id)
    await _require_template_read_access(db, current_user, template)
    return _to_response(template)


@router.put("/templates/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: str,
    data: TemplateUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    """Update a prompt template."""
    try:
        repo = SqlPromptTemplateRepository(db)
        template = await _get_template_or_404(repo, template_id)
        await _require_template_write_access(db, current_user, template)
        if data.title is not None:
            template.title = data.title
        if data.content is not None:
            template.content = data.content
        if data.category is not None:
            template.category = data.category
        if data.variables is not None:
            template.variables = [
                TemplateVariable(
                    name=v.name,
                    description=v.description,
                    default_value=v.default_value,
                    required=v.required,
                )
                for v in data.variables
            ]
        template.updated_at = datetime.now(UTC)
        saved = await repo.save(template)
        await db.commit()
        return _to_response(saved)
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        logger.exception("Error updating template")
        raise HTTPException(status_code=500, detail=_("Failed to update template")) from None


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a prompt template."""
    try:
        repo = SqlPromptTemplateRepository(db)
        template = await _get_template_or_404(repo, template_id)
        await _require_template_write_access(db, current_user, template)
        deleted = await repo.delete(template_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=_("Template not found"))
        await db.commit()
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        logger.exception("Error deleting template")
        raise HTTPException(status_code=500, detail=_("Failed to delete template")) from None
