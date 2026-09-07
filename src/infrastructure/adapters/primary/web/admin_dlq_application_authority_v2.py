# pyright: reportImportCycles=false
"""FastAPI authority for generation-owned admin DLQ services."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, status

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.admin_dlq_services import (
    ADMIN_DLQ_APPLICATION_SERVICE_V2,
    AdminDlqApplicationResolverProtocolV2,
    AdminDlqApplicationServicesV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error

_ADMIN_ROLE_NAMES = frozenset({"admin", "system_admin", "super_admin"})


@dataclass(frozen=True, kw_only=True)
class AdminDlqApplicationAuthorityV2:
    """Administrator request's immutable generation and queue services."""

    operation: OperationContextV2
    current_user: DBUser
    services: AdminDlqApplicationServicesV2


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) else "-"


def _user_has_admin_access(current_user: DBUser) -> bool:
    """Return whether structured persisted roles grant global admin access."""
    if bool(getattr(current_user, "is_superuser", False)):
        return True

    legacy_role = getattr(current_user, "role", None)
    if isinstance(legacy_role, str) and legacy_role in _ADMIN_ROLE_NAMES:
        return True

    user_roles = cast(Iterable[Any], getattr(current_user, "roles", []) or [])
    return any(
        getattr(getattr(user_role, "role", None), "name", None) in _ADMIN_ROLE_NAMES
        for user_role in user_roles
    )


def require_admin(current_user: DBUser = Depends(get_current_user)) -> DBUser:
    """Require an explicit global-admin role before resolving DLQ services."""
    if not _user_has_admin_access(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Admin access required"),
        )
    return current_user


@asynccontextmanager
async def admin_dlq_application_authority_context_v2(
    *,
    request: Request,
    current_user: DBUser,
) -> AsyncIterator[AdminDlqApplicationAuthorityV2]:
    """Pin one generation and resolve root-scoped admin DLQ services."""
    operation = OperationContextV2(
        generation=current_generation_v2(),
        operation_id=f"http-admin-dlq:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    async with operation:
        _ = operation.provide(
            OPERATION_IDENTITY_SERVICE_V2,
            {"user_id": str(current_user.id)},
        )
        _ = operation.provide(
            OPERATION_METADATA_SERVICE_V2,
            {
                "kind": "http-authority",
                "method": request.method,
                "path": _route_template(request),
            },
        )
        resolver = operation.require(ADMIN_DLQ_APPLICATION_SERVICE_V2)
        if not isinstance(resolver, AdminDlqApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_admin_dlq_application_resolver",
                "admin DLQ application service has an invalid implementation",
            )
        yield AdminDlqApplicationAuthorityV2(
            operation=operation,
            current_user=current_user,
            services=resolver.resolve(operation),
        )


async def admin_dlq_application_authority_dependency_v2(
    request: Request,
    current_user: DBUser = Depends(require_admin),
) -> AsyncIterator[AdminDlqApplicationAuthorityV2]:
    """Yield admin DLQ services pinned for the complete HTTP handler."""
    async with admin_dlq_application_authority_context_v2(
        request=request,
        current_user=current_user,
    ) as authority:
        yield authority


__all__ = [
    "AdminDlqApplicationAuthorityV2",
    "admin_dlq_application_authority_context_v2",
    "admin_dlq_application_authority_dependency_v2",
    "require_admin",
]
