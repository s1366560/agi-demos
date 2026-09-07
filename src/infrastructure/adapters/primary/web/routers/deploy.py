"""Deploy Management API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.application.schemas.deploy_schemas import (
    DeployCreate,
    DeployListResponse,
    DeployResponse,
)
from src.domain.model.deploy.enums import DeployAction
from src.infrastructure.adapters.primary.web.instance_deploy_application_authority_v2 import (
    InstanceDeployApplicationAuthorityV2,
    deploy_application_authority_dependency_v2,
    deploy_progress_application_authority_dependency_v2,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/deploys", tags=["Deploys"])


class DeploySuccessRequest(BaseModel):
    """Request body for marking a deploy as successful."""

    message: str = Field("", description="Success message")


class DeployFailedRequest(BaseModel):
    """Request body for marking a deploy as failed."""

    message: str = Field(..., description="Failure message")


def _deploy_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_("Deploy not found"),
    )


def _deploy_action_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_("Deploy operation failed"),
    )


async def _ensure_tenant_access(
    authority: InstanceDeployApplicationAuthorityV2,
    tenant_id: str,
) -> None:
    if not await authority.services.access.can_access_tenant(
        authority.current_user,
        tenant_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied to tenant"),
        )


async def _require_instance_tenant_access(
    authority: InstanceDeployApplicationAuthorityV2,
    instance_id: str,
) -> str:
    tenant_id = await authority.services.access.find_instance_tenant_id(instance_id)
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Instance not found"),
        )
    await _ensure_tenant_access(authority, tenant_id)
    return tenant_id


async def _require_deploy_tenant_access(
    authority: InstanceDeployApplicationAuthorityV2,
    deploy_id: str,
) -> None:
    instance_tenant_id = await authority.services.access.find_deploy_tenant_id(deploy_id)
    if instance_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Deploy not found"),
        )
    await _ensure_tenant_access(authority, instance_tenant_id)


@router.post(
    "/",
    response_model=DeployResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_deploy(
    data: DeployCreate,
    authority: InstanceDeployApplicationAuthorityV2 = Depends(
        deploy_application_authority_dependency_v2
    ),
) -> DeployResponse:
    """Create a new deploy record."""
    try:
        await _require_instance_tenant_access(authority, data.instance_id)
        service = authority.services.deploys
        result = await service.create_deploy(
            instance_id=data.instance_id,
            action=DeployAction(data.action),
            triggered_by=authority.current_user.id,
            image_version=data.image_version,
            replicas=data.replicas,
            config_snapshot=data.config_snapshot,
        )
        await authority.db.commit()
        return DeployResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except ValueError as e:
        raise _deploy_action_error() from e
    except Exception as e:
        logger.exception("Error creating deploy")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e


@router.get("/", response_model=DeployListResponse)
async def list_deploys(
    instance_id: str = Query(..., description="Instance ID to filter by"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    authority: InstanceDeployApplicationAuthorityV2 = Depends(
        deploy_application_authority_dependency_v2
    ),
) -> DeployListResponse:
    """List deploy records for an instance."""
    try:
        await _require_instance_tenant_access(authority, instance_id)
        service = authority.services.deploys
        offset = (page - 1) * page_size
        items, total = await service.list_deploys_with_total(
            instance_id=instance_id,
            limit=page_size,
            offset=offset,
        )
        return DeployListResponse(
            deploys=[DeployResponse.model_validate(r, from_attributes=True) for r in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error listing deploys")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e


@router.get(
    "/instances/{instance_id}/latest",
    response_model=DeployResponse,
)
async def get_latest_deploy(
    instance_id: str,
    authority: InstanceDeployApplicationAuthorityV2 = Depends(
        deploy_application_authority_dependency_v2
    ),
) -> DeployResponse:
    """Get the most recent deploy record for an instance."""
    try:
        await _require_instance_tenant_access(authority, instance_id)
        service = authority.services.deploys
        result = await service.get_latest_deploy(instance_id=instance_id)
        if result is None:
            raise _deploy_not_found_error()
        return DeployResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting latest deploy")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e


@router.get("/{deploy_id}", response_model=DeployResponse)
async def get_deploy(
    deploy_id: str,
    authority: InstanceDeployApplicationAuthorityV2 = Depends(
        deploy_application_authority_dependency_v2
    ),
) -> DeployResponse:
    """Get a specific deploy record by ID."""
    try:
        await _require_deploy_tenant_access(authority, deploy_id)
        service = authority.services.deploys
        result = await service.get_deploy(deploy_id=deploy_id)
        if result is None:
            raise _deploy_not_found_error()
        return DeployResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting deploy")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e


@router.post(
    "/{deploy_id}/success",
    response_model=DeployResponse,
)
async def mark_deploy_success(
    deploy_id: str,
    data: DeploySuccessRequest,
    authority: InstanceDeployApplicationAuthorityV2 = Depends(
        deploy_application_authority_dependency_v2
    ),
) -> DeployResponse:
    """Mark a deploy as successful."""
    try:
        await _require_deploy_tenant_access(authority, deploy_id)
        service = authority.services.deploys
        result = await service.mark_deploy_success(
            deploy_id=deploy_id,
            message=data.message or None,
        )
        await authority.db.commit()
        return DeployResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except ValueError as e:
        raise _deploy_action_error() from e
    except Exception as e:
        logger.exception("Error marking deploy success")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e


@router.post(
    "/{deploy_id}/failed",
    response_model=DeployResponse,
)
async def mark_deploy_failed(
    deploy_id: str,
    data: DeployFailedRequest,
    authority: InstanceDeployApplicationAuthorityV2 = Depends(
        deploy_application_authority_dependency_v2
    ),
) -> DeployResponse:
    """Mark a deploy as failed."""
    try:
        await _require_deploy_tenant_access(authority, deploy_id)
        service = authority.services.deploys
        result = await service.mark_deploy_failed(
            deploy_id=deploy_id,
            message=data.message,
        )
        await authority.db.commit()
        return DeployResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except ValueError as e:
        raise _deploy_action_error() from e
    except Exception as e:
        logger.exception("Error marking deploy failed")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e


@router.post(
    "/{deploy_id}/cancel",
    response_model=DeployResponse,
)
async def cancel_deploy(
    deploy_id: str,
    authority: InstanceDeployApplicationAuthorityV2 = Depends(
        deploy_application_authority_dependency_v2
    ),
) -> DeployResponse:
    """Cancel a deploy that has not yet reached a terminal state."""
    try:
        await _require_deploy_tenant_access(authority, deploy_id)
        service = authority.services.deploys
        result = await service.cancel_deploy(deploy_id=deploy_id)
        await authority.db.commit()
        return DeployResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except ValueError as e:
        raise _deploy_action_error() from e
    except Exception as e:
        logger.exception("Error cancelling deploy")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e


@router.get("/{deploy_id}/progress")
async def stream_deploy_progress(
    request: Request,
    deploy_id: str,
    authority: InstanceDeployApplicationAuthorityV2 = Depends(
        deploy_progress_application_authority_dependency_v2
    ),
) -> StreamingResponse:
    """SSE endpoint for real-time deploy progress via Redis pub/sub."""
    service = authority.services.deploys

    record = await service.get_deploy(deploy_id=deploy_id)
    if record is None:
        raise _deploy_not_found_error()
    await _require_deploy_tenant_access(authority, deploy_id)

    return StreamingResponse(
        authority.services.progress.stream(
            record=record,
            is_disconnected=request.is_disconnected,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
