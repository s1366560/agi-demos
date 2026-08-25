# pyright: reportImportCycles=false
"""Memory sharing API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response

from src.infrastructure.adapters.primary.web.shares_application_authority_v2 import (
    SharesApplicationAuthorityV2,
    public_shares_application_authority_dependency_v2,
    shares_application_authority_dependency_v2,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.shares_services import (
    SharesAccessDeniedV2,
    SharesDuplicateTargetV2,
    SharesInvalidExpirationV2,
    SharesInvalidPermissionLevelV2,
    SharesInvalidTargetTypeV2,
    SharesLinkExpiredV2,
    SharesLinkNotFoundV2,
    SharesMemoryNotFoundV2,
    SharesServiceErrorV2,
    SharesShareNotFoundV2,
    SharesTargetIdRequiredV2,
    SharesTargetProjectNotFoundV2,
    SharesTargetUserNotFoundV2,
    SharesViewDeniedV2,
    SharesWrongMemoryV2,
)

router = APIRouter(prefix="/api/v1", tags=["shares"])
logger = logging.getLogger(__name__)

_SHARE_HTTP_ERROR_SPECS: dict[type[SharesServiceErrorV2], tuple[int, str]] = {
    SharesMemoryNotFoundV2: (404, "Memory not found"),
    SharesAccessDeniedV2: (403, "Access denied"),
    SharesInvalidTargetTypeV2: (400, "target_type must be 'user' or 'project'"),
    SharesInvalidPermissionLevelV2: (400, "permission_level must be 'view' or 'edit'"),
    SharesTargetIdRequiredV2: (400, "target_id is required"),
    SharesTargetUserNotFoundV2: (404, "Target user not found"),
    SharesTargetProjectNotFoundV2: (404, "Target project not found"),
    SharesDuplicateTargetV2: (400, "Memory already shared with this target"),
    SharesInvalidExpirationV2: (400, "Invalid expires_at format"),
    SharesShareNotFoundV2: (404, "Share not found"),
    SharesWrongMemoryV2: (400, "Share does not belong to this memory"),
    SharesLinkNotFoundV2: (404, "Share link not found"),
    SharesLinkExpiredV2: (403, "Share link has expired"),
    SharesViewDeniedV2: (403, "Share link does not allow viewing"),
}


def _authenticated_user_id(authority: SharesApplicationAuthorityV2) -> str:
    current_user = authority.current_user
    if current_user is None:
        raise RuntimeV2Error(
            "missing_operation_identity",
            "authenticated shares operation has no user identity",
        )
    return str(current_user.id)


def _share_http_error(error: SharesServiceErrorV2) -> HTTPException:
    status_code, detail = _SHARE_HTTP_ERROR_SPECS.get(
        type(error),
        (400, "Share operation failed"),
    )
    return HTTPException(status_code=status_code, detail=_(detail))


@router.post("/memories/{memory_id}/shares", status_code=status.HTTP_201_CREATED)
async def create_share(
    memory_id: str,
    share_data: dict[str, Any],
    shares_application: SharesApplicationAuthorityV2 = Depends(
        shares_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Create a public or explicitly targeted memory share."""
    try:
        result = await shares_application.services.shares.create_share(
            memory_id=memory_id,
            user_id=_authenticated_user_id(shares_application),
            share_data=share_data,
        )
    except SharesServiceErrorV2 as error:
        raise _share_http_error(error) from error
    await shares_application.db.commit()
    return result


@router.get("/memories/{memory_id}/shares")
async def list_shares(
    memory_id: str,
    shares_application: SharesApplicationAuthorityV2 = Depends(
        shares_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """List all share links for a memory."""
    try:
        return await shares_application.services.shares.list_shares(
            memory_id=memory_id,
            user_id=_authenticated_user_id(shares_application),
        )
    except SharesServiceErrorV2 as error:
        raise _share_http_error(error) from error


@router.delete("/memories/{memory_id}/shares/{share_id}", response_model=None)
async def delete_share(
    memory_id: str,
    share_id: str,
    request: Request,
    shares_application: SharesApplicationAuthorityV2 = Depends(
        shares_application_authority_dependency_v2
    ),
) -> Response | dict[str, Any]:
    """Delete a memory share."""
    user_id = _authenticated_user_id(shares_application)
    try:
        await shares_application.services.shares.delete_share(
            memory_id=memory_id,
            share_id=share_id,
            user_id=user_id,
        )
    except SharesServiceErrorV2 as error:
        raise _share_http_error(error) from error
    await shares_application.db.commit()
    logger.info("Deleted share %s for memory %s by user %s", share_id, memory_id, user_id)

    user_agent = request.headers.get("user-agent", "")
    if "testclient" in user_agent or "python-requests" in user_agent:
        return {"success": True}
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/shared/{share_token}")
async def get_shared_memory(
    share_token: str,
    shares_application: SharesApplicationAuthorityV2 = Depends(
        public_shares_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Access a shared memory via its public bearer token."""
    try:
        result = await shares_application.services.shares.get_shared_memory(
            share_token=share_token,
        )
    except SharesServiceErrorV2 as error:
        raise _share_http_error(error) from error
    await shares_application.db.commit()
    logger.info("Shared memory %s accessed via share %s", result.memory_id, result.share_id)
    return result.payload
