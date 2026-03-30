"""Deploy Management API endpoints."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.deploy_schemas import (
    DeployCreate,
    DeployListResponse,
    DeployResponse,
)
from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user_from_header_or_query,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    User as DBUser,
    UserTenant,
)


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """Get DI container with database session for the current request."""
    app_container: Any = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container.redis_client,
    )


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/deploys", tags=["Deploys"])


class DeploySuccessRequest(BaseModel):
    """Request body for marking a deploy as successful."""

    message: str = Field("", description="Success message")


class DeployFailedRequest(BaseModel):
    """Request body for marking a deploy as failed."""

    message: str = Field(..., description="Failure message")


@router.post(
    "/",
    response_model=DeployResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_deploy(
    request: Request,
    data: DeployCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> DeployResponse:
    """Create a new deploy record."""
    try:
        container = get_container_with_db(request, db)
        service = container.deploy_service()
        result = await service.create_deploy(
            instance_id=data.instance_id,
            action=cast(Any, data.action),
            triggered_by=data.triggered_by or tenant_id,
            image_version=data.image_version,
            replicas=data.replicas,
            config_snapshot=data.config_snapshot,
        )
        await db.commit()
        return DeployResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.exception("Error creating deploy")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/", response_model=DeployListResponse)
async def list_deploys(
    request: Request,
    instance_id: str = Query(..., description="Instance ID to filter by"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> DeployListResponse:
    """List deploy records for an instance."""
    try:
        container = get_container_with_db(request, db)
        service = container.deploy_service()
        offset = (page - 1) * page_size
        items = await service.list_deploys(
            instance_id=instance_id,
            limit=page_size,
            offset=offset,
        )
        return DeployListResponse(
            deploys=[DeployResponse.model_validate(r, from_attributes=True) for r in items],
            total=len(items),
            page=page,
            page_size=page_size,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error listing deploys")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get(
    "/instances/{instance_id}/latest",
    response_model=DeployResponse,
)
async def get_latest_deploy(
    request: Request,
    instance_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> DeployResponse:
    """Get the most recent deploy record for an instance."""
    try:
        container = get_container_with_db(request, db)
        service = container.deploy_service()
        result = await service.get_latest_deploy(instance_id=instance_id)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No deploys found for instance {instance_id}",
            )
        return DeployResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting latest deploy")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/{deploy_id}", response_model=DeployResponse)
async def get_deploy(
    request: Request,
    deploy_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> DeployResponse:
    """Get a specific deploy record by ID."""
    try:
        container = get_container_with_db(request, db)
        service = container.deploy_service()
        result = await service.get_deploy(deploy_id=deploy_id)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Deploy {deploy_id} not found",
            )
        return DeployResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting deploy")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post(
    "/{deploy_id}/success",
    response_model=DeployResponse,
)
async def mark_deploy_success(
    request: Request,
    deploy_id: str,
    data: DeploySuccessRequest,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> DeployResponse:
    """Mark a deploy as successful."""
    try:
        container = get_container_with_db(request, db)
        service = container.deploy_service()
        result = await service.mark_deploy_success(
            deploy_id=deploy_id,
            message=data.message or None,
        )
        await db.commit()
        return DeployResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.exception("Error marking deploy success")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post(
    "/{deploy_id}/failed",
    response_model=DeployResponse,
)
async def mark_deploy_failed(
    request: Request,
    deploy_id: str,
    data: DeployFailedRequest,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> DeployResponse:
    """Mark a deploy as failed."""
    try:
        container = get_container_with_db(request, db)
        service = container.deploy_service()
        result = await service.mark_deploy_failed(
            deploy_id=deploy_id,
            message=data.message,
        )
        await db.commit()
        return DeployResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.exception("Error marking deploy failed")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post(
    "/{deploy_id}/cancel",
    response_model=DeployResponse,
)
async def cancel_deploy(
    request: Request,
    deploy_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> DeployResponse:
    """Cancel a deploy that has not yet reached a terminal state."""
    try:
        container = get_container_with_db(request, db)
        service = container.deploy_service()
        result = await service.cancel_deploy(deploy_id=deploy_id)
        await db.commit()
        return DeployResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.exception("Error cancelling deploy")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/{deploy_id}/progress")
async def stream_deploy_progress(
    request: Request,
    deploy_id: str,
    current_user: DBUser = Depends(get_current_user_from_header_or_query),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """SSE endpoint for real-time deploy progress via Redis pub/sub."""
    # Derive tenant_id from user (supports both header and query-param auth for EventSource)
    result = await db.execute(
        select(UserTenant.tenant_id).where(UserTenant.user_id == current_user.id).limit(1)
    )
    tenant_id = result.scalar_one_or_none()
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User does not belong to any tenant",
        )

    container = get_container_with_db(request, db)
    service = container.deploy_service()

    record = await service.get_deploy(deploy_id=deploy_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deploy {deploy_id} not found",
        )

    rc: Any = container.redis_client

    async def event_stream() -> AsyncGenerator[str, None]:
        channel_name = f"deploy:progress:{deploy_id}"

        yield f"data: {json.dumps({'type': 'status', 'status': record.status.value, 'deploy_id': deploy_id})}\n\n"

        if record.is_terminal():
            yield f"data: {json.dumps({'type': 'done', 'status': record.status.value})}\n\n"
            return

        pubsub = rc.pubsub()
        await pubsub.subscribe(channel_name)
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    yield f"data: {data}\n\n"
                    try:
                        parsed = json.loads(data)
                        if parsed.get("type") == "done":
                            break
                    except (json.JSONDecodeError, TypeError):
                        pass
                else:
                    yield ": keepalive\n\n"
                    await asyncio.sleep(0.5)
        finally:
            await pubsub.unsubscribe(channel_name)
            await pubsub.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
