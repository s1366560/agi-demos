"""HTTP adapters for generation-owned MCP authorization services."""

from collections.abc import Collection

from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.mcp_application_authority_v2 import (
    MCPApplicationAuthorityV2,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.mcp_services import MCPProjectAccessDeniedV2


def _access_denied() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=_("Access denied"),
    )


async def list_accessible_project_ids(
    authority: MCPApplicationAuthorityV2,
) -> set[str]:
    """Return direct project memberships through the operation-owned Provider."""
    return await authority.services.access.list_accessible_project_ids(
        tenant_id=authority.tenant_id,
        user_id=authority.user_id,
    )


async def resolve_project_tenant_id_for_access(
    authority: MCPApplicationAuthorityV2,
    project_id: str,
    required_roles: Collection[str] | None = None,
) -> str:
    """Resolve a project tenant through the operation-owned authorization seam."""
    try:
        return await authority.services.access.resolve_project_tenant_id(
            project_id=project_id,
            tenant_id=authority.tenant_id,
            user_id=authority.user_id,
            required_roles=required_roles,
        )
    except MCPProjectAccessDeniedV2 as exc:
        raise _access_denied() from exc


async def ensure_project_access(
    authority: MCPApplicationAuthorityV2,
    project_id: str,
    tenant_id: str,
    required_roles: Collection[str] | None = None,
) -> None:
    """Enforce tenant membership through the operation-owned authorization seam."""
    if tenant_id != authority.tenant_id:
        raise _access_denied()
    try:
        await authority.services.access.ensure_project_access(
            project_id=project_id,
            tenant_id=authority.tenant_id,
            user_id=authority.user_id,
            required_roles=required_roles,
        )
    except MCPProjectAccessDeniedV2 as exc:
        raise _access_denied() from exc


__all__ = [
    "ensure_project_access",
    "list_accessible_project_ids",
    "resolve_project_tenant_id_for_access",
]
