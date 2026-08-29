"""Fail-closed authentication for protocol-v2 data-plane workloads."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.platform_plugin_data_plane_credential_repository_v2 import (
    PLUGIN_DATA_PLANE_CREDENTIAL_PREFIX_V2,
    PlatformPluginDataPlaneCredentialRepositoryV2,
    PlatformPluginDataPlanePrincipalV2,
)
from src.infrastructure.i18n import gettext as _


async def get_plugin_data_plane_principal_v2(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> PlatformPluginDataPlanePrincipalV2:
    """Authenticate only a dedicated bearer secret and return its plane binding."""
    secret: str | None = None
    if authorization is not None and authorization.startswith("Bearer "):
        candidate = authorization[7:]
        if candidate.startswith(PLUGIN_DATA_PLANE_CREDENTIAL_PREFIX_V2):
            secret = candidate
    principal = (
        None
        if secret is None
        else await PlatformPluginDataPlaneCredentialRepositoryV2(db).authenticate(secret)
    )
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_("Invalid plugin data-plane credential"),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


__all__ = [
    "PlatformPluginDataPlanePrincipalV2",
    "get_plugin_data_plane_principal_v2",
]
