"""Plugin marketplace package API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.plugin_marketplace import (
    MarketplacePackageRequest,
    MarketplacePackageResponse,
)
from src.application.services.plugin_marketplace_install_service import (
    PluginMarketplaceInstallService,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/plugin-marketplace", tags=["Plugin Marketplace"])


def _service(
    db: AsyncSession = Depends(get_db),
) -> PluginMarketplaceInstallService:
    return PluginMarketplaceInstallService(
        PlatformPluginGovernanceRepository(db),
    )


@router.post(
    "/packages/{plugin_id}/install",
    response_model=MarketplacePackageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def install_package(
    plugin_id: str,
    request: MarketplacePackageRequest,
    _current_user: User = Depends(get_current_user),
    service: PluginMarketplaceInstallService = Depends(_service),
    db: AsyncSession = Depends(get_db),
) -> MarketplacePackageResponse:
    """Verify and request one package installation without exposing secrets."""
    if request.plugin_id != plugin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Plugin path and request body must identify the same package"),
        )
    decision = await service.request_install(request=request)
    if decision.status == "approved":
        await db.commit()
    else:
        await db.rollback()
    return MarketplacePackageResponse(
        plugin_id=decision.plugin_id,
        version=decision.version,
        status=decision.status,
        reason=decision.reason,
    )
