"""Instance Template Marketplace API endpoints.

Provides REST API for managing instance templates — reusable configurations
for creating instances with predefined settings and gene compositions.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.instance_template_schemas import (
    InstanceTemplateCreate,
    InstanceTemplateListResponse,
    InstanceTemplateResponse,
    InstanceTemplateUpdate,
    TemplateItemCreate,
    TemplateItemResponse,
)
from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """Get DI container with database session for the current request."""
    app_container: DIContainer = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container.redis_client,
    )


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/instance-templates",
    tags=["Instance Templates"],
)


class CloneTemplateRequest(BaseModel):
    """Request to clone a template."""

    new_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Name for the cloned template",
    )


# ------------------------------------------------------------------
# Template CRUD
# ------------------------------------------------------------------


@router.post(
    "/",
    response_model=InstanceTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    request: Request,
    data: InstanceTemplateCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceTemplateResponse:
    """Create a new instance template."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_template_service()

        template = await service.create_template(
            name=data.name,
            slug=data.slug,
            created_by=tenant_id,
            tenant_id=data.tenant_id or tenant_id,
            description=data.description,
            icon=data.icon,
            image_version=data.image_version,
            default_config=data.default_config,
        )
        await db.commit()

        logger.info("Template created: %s", template.id)
        return InstanceTemplateResponse.model_validate(template, from_attributes=True)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get(
    "/",
    response_model=InstanceTemplateListResponse,
)
async def list_templates(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    is_published: bool | None = Query(None, description="Filter by published status"),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceTemplateListResponse:
    """List instance templates with pagination."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_template_service()

        offset = (page - 1) * page_size
        templates = await service.list_templates(
            tenant_id=tenant_id,
            is_published=is_published,
            limit=page_size,
            offset=offset,
        )

        return InstanceTemplateListResponse(
            templates=[
                InstanceTemplateResponse.model_validate(t, from_attributes=True) for t in templates
            ],
            total=len(templates),
            page=page,
            page_size=page_size,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get(
    "/{template_id}",
    response_model=InstanceTemplateResponse,
)
async def get_template(
    request: Request,
    template_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceTemplateResponse:
    """Get a specific instance template by ID."""
    container = get_container_with_db(request, db)
    service = container.instance_template_service()

    template = await service.get_template(template_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found",
        )

    return InstanceTemplateResponse.model_validate(template, from_attributes=True)


@router.put(
    "/{template_id}",
    response_model=InstanceTemplateResponse,
)
async def update_template(
    request: Request,
    template_id: str,
    data: InstanceTemplateUpdate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceTemplateResponse:
    """Update an existing instance template."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_template_service()

        template = await service.update_template(
            template_id=template_id,
            name=data.name,
            description=data.description,
            icon=data.icon,
            image_version=data.image_version,
            default_config=data.default_config,
            is_published=data.is_published,
        )
        await db.commit()

        logger.info("Template updated: %s", template_id)
        return InstanceTemplateResponse.model_validate(template, from_attributes=True)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.delete(
    "/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_template(
    request: Request,
    template_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an instance template."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_template_service()

        await service.delete_template(template_id)
        await db.commit()

        logger.info("Template deleted: %s", template_id)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


# ------------------------------------------------------------------
# Publish / Unpublish
# ------------------------------------------------------------------


@router.post(
    "/{template_id}/publish",
    response_model=InstanceTemplateResponse,
)
async def publish_template(
    request: Request,
    template_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceTemplateResponse:
    """Publish a template to the marketplace."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_template_service()

        template = await service.publish_template(template_id)
        await db.commit()

        logger.info("Template published: %s", template_id)
        return InstanceTemplateResponse.model_validate(template, from_attributes=True)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.post(
    "/{template_id}/unpublish",
    response_model=InstanceTemplateResponse,
)
async def unpublish_template(
    request: Request,
    template_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceTemplateResponse:
    """Unpublish a template from the marketplace."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_template_service()

        template = await service.unpublish_template(template_id)
        await db.commit()

        logger.info("Template unpublished: %s", template_id)
        return InstanceTemplateResponse.model_validate(template, from_attributes=True)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


# ------------------------------------------------------------------
# Clone
# ------------------------------------------------------------------


@router.post(
    "/{template_id}/clone",
    response_model=InstanceTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def clone_template(
    request: Request,
    template_id: str,
    data: CloneTemplateRequest,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceTemplateResponse:
    """Clone an existing template with a new name."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_template_service()

        source = await service.get_template(template_id)
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source template not found",
            )

        slug = data.new_name.lower().replace(" ", "-")
        cloned = await service.create_template(
            name=data.new_name,
            slug=slug,
            created_by=tenant_id,
            tenant_id=tenant_id,
            description=source.description,
            icon=source.icon,
            image_version=source.image_version,
            default_config=source.default_config,
        )

        source_items = await service.list_template_items(template_id)
        for item in source_items:
            _ = await service.add_template_item(
                template_id=cloned.id,
                item_type=item.item_type,
                item_slug=item.item_slug,
                display_order=item.display_order,
            )

        await db.commit()

        logger.info("Template cloned: %s -> %s", template_id, cloned.id)
        return InstanceTemplateResponse.model_validate(cloned, from_attributes=True)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


# ------------------------------------------------------------------
# Template Items
# ------------------------------------------------------------------


@router.post(
    "/{template_id}/items",
    response_model=TemplateItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_template_item(
    request: Request,
    template_id: str,
    data: TemplateItemCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> TemplateItemResponse:
    """Add an item to a template."""
    try:
        from src.domain.model.instance_template.enums import (
            TemplateItemType,
        )

        container = get_container_with_db(request, db)
        service = container.instance_template_service()

        item = await service.add_template_item(
            template_id=template_id,
            item_type=TemplateItemType(data.item_type),
            item_slug=data.item_slug,
            display_order=data.display_order,
        )
        await db.commit()

        logger.info(
            "Item added to template %s: %s",
            template_id,
            item.id,
        )
        return TemplateItemResponse.model_validate(item, from_attributes=True)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.delete(
    "/{template_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def remove_template_item(
    request: Request,
    template_id: str,
    item_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove an item from a template."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_template_service()

        await service.remove_template_item(item_id)
        await db.commit()

        logger.info(
            "Item removed from template %s: %s",
            template_id,
            item_id,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get(
    "/{template_id}/items",
    response_model=list[TemplateItemResponse],
)
async def list_template_items(
    request: Request,
    template_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[TemplateItemResponse]:
    """List all items belonging to a template."""
    container = get_container_with_db(request, db)
    service = container.instance_template_service()

    items = await service.list_template_items(template_id)

    return [TemplateItemResponse.model_validate(item, from_attributes=True) for item in items]
