"""Protocol V2 control plane and explicit retirement of the V1 HTTP surface."""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, status

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v1_retirement import (
    PLUGIN_MARKETPLACE_V2_PATH,
    PLUGIN_PROTOCOL_V1_RETIRED_CODE,
)

from .platform_plugin_profile_sources_v2 import router as profile_sources_router
from .platform_plugins_v2 import router as protocol_v2_router

router = APIRouter(prefix="/api/v1/platform-plugins", tags=["Platform Plugins"])
router.include_router(protocol_v2_router)
router.include_router(profile_sources_router)


def raise_plugin_protocol_v1_retired() -> NoReturn:
    """Return the stable breaking-protocol response for every V1 operation."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": PLUGIN_PROTOCOL_V1_RETIRED_CODE,
            "message": _("Plugin protocol V1 is retired; use the V2 plugin control plane"),
            "migration_target": PLUGIN_MARKETPLACE_V2_PATH,
        },
    )


@router.api_route(
    "",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    response_model=None,
    include_in_schema=False,
)
async def retired_plugin_protocol_v1_root_route(
    _current_user: User = Depends(get_current_user),
) -> NoReturn:
    """Reject the exact V1 control-plane root without a redirect."""
    raise_plugin_protocol_v1_retired()


@router.api_route(
    "/{legacy_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    response_model=None,
    include_in_schema=False,
)
async def retired_plugin_protocol_v1_route(
    legacy_path: str,
    _current_user: User = Depends(get_current_user),
) -> NoReturn:
    """Reject every authenticated legacy platform-plugin path without conversion."""
    normalized_path = legacy_path.strip("/")
    if normalized_path == "v2" or normalized_path.startswith("v2/"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Not Found"),
        )
    raise_plugin_protocol_v1_retired()


__all__ = [
    "raise_plugin_protocol_v1_retired",
    "retired_plugin_protocol_v1_root_route",
    "retired_plugin_protocol_v1_route",
    "router",
]
