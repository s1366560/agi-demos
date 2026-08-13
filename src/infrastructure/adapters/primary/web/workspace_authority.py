"""FastAPI access to the process-scoped Workspace authority."""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from src.domain.ports.services.workspace_authority_port import (
    WorkspaceAuthorityAccessDeniedError,
    WorkspaceAuthorityNotFoundError,
    WorkspaceAuthorityPort,
    WorkspaceAuthorityScope,
    WorkspaceAuthorityUnavailableError,
)
from src.infrastructure.i18n import gettext as _


def workspace_core_unavailable_detail() -> dict[str, str]:
    """Return the stable machine- and human-readable Core outage contract."""
    return {
        "code": "WORKSPACE_CORE_UNAVAILABLE",
        "reason": "workspace_core_unavailable",
        "detail": _("Workspace Core is unavailable"),
    }


def workspace_core_unavailable_error() -> HTTPException:
    """Return the common fail-closed Workspace Core outage response."""
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=workspace_core_unavailable_detail(),
    )


def get_workspace_authority(request: Request) -> WorkspaceAuthorityPort:
    authority = getattr(request.app.state, "workspace_authority", None)
    if authority is None:
        raise workspace_core_unavailable_error()
    return authority


async def require_workspace_scope(
    request: Request,
    *,
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    user_id: str,
    is_superuser: bool = False,
    allowed_roles: frozenset[str] | None = None,
) -> str:
    authority = get_workspace_authority(request)
    scope = WorkspaceAuthorityScope(
        tenant_id=tenant_id,
        project_id=project_id,
        workspace_id=workspace_id,
        user_id=user_id,
        is_superuser=is_superuser,
    )
    try:
        role = await authority.get_membership_role(scope)
    except WorkspaceAuthorityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_("Workspace not found")) from exc
    except WorkspaceAuthorityAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=_("Workspace access required")) from exc
    except WorkspaceAuthorityUnavailableError as exc:
        raise workspace_core_unavailable_error() from exc
    if allowed_roles is not None and role not in allowed_roles:
        raise HTTPException(status_code=403, detail=_("Workspace manager permission is required"))
    return role
