"""Prompt template CRUD API endpoints."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.prompt_template import (
    PromptTemplate,
    TemplateVariable,
)
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.secondary.persistence.database import (
    get_db,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.sql_prompt_template_repository import (
    SqlPromptTemplateRepository,
)

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
        repo = SqlPromptTemplateRepository(db)
        # Only admins can create system templates
        is_system = data.is_system and getattr(current_user, 'role', '') == 'admin'
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
            is_system=is_system,
        )
        saved = await repo.save(template)
        await db.commit()
        return _to_response(saved)
    except Exception:
        await db.rollback()
        logger.exception("Error creating template")
        raise HTTPException(status_code=500, detail="Failed to create template")


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
        repo = SqlPromptTemplateRepository(db)
        if project_id:
            templates = await repo.list_by_project(project_id, limit=limit, offset=offset)
        else:
            templates = await repo.list_by_tenant(
                tenant_id,
                category=category,
                limit=limit,
                offset=offset,
            )
        return [_to_response(t) for t in templates]
    except Exception:
        logger.exception("Error listing templates")
        raise HTTPException(status_code=500, detail="Failed to list templates")


@router.get("/templates/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    """Get a specific prompt template."""
    repo = SqlPromptTemplateRepository(db)
    template = await repo.find_by_id(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
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
        template = await repo.find_by_id(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        if template.created_by != current_user.id and not template.is_system:
            raise HTTPException(status_code=403, detail="Not authorized to update this template")
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
        raise HTTPException(status_code=500, detail="Failed to update template")


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
        template = await repo.find_by_id(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        if template.created_by != current_user.id and not template.is_system:
            raise HTTPException(status_code=403, detail="Not authorized to delete this template")
        deleted = await repo.delete(template_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Template not found")
        await db.commit()
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        logger.exception("Error deleting template")
        raise HTTPException(status_code=500, detail="Failed to delete template")
