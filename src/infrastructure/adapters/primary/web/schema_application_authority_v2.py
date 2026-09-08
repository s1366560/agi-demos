"""FastAPI authority dependency for generation-owned project schema services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.project_schema.commands import ProjectSchemaAction
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    current_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.schema_services import (
    SCHEMA_APPLICATION_SERVICE_V2,
    SchemaAccessDeniedV2,
    SchemaApplicationResolverProtocolV2,
    SchemaApplicationServicesV2,
)


@dataclass(frozen=True, kw_only=True)
class SchemaApplicationAuthorityV2:
    """Request-owned schema services and their disposable operation boundary."""

    operation: OperationContextV2
    db: AsyncSession
    services: SchemaApplicationServicesV2


async def schema_application_authority_dependency_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[SchemaApplicationAuthorityV2]:
    """Yield schema services from the generation pinned to this HTTP request."""
    generation = current_generation_v2()
    project_id = _scope_id_v2(request.path_params.get("project_id"))
    requested_tenant = _scope_id_v2(
        request.path_params.get("tenant_id") or request.query_params.get("tenant_id")
    )
    if project_id is None:
        raise HTTPException(status_code=403, detail=_("Access denied to project"))
    try:
        async with OperationContextV2(
            generation=generation,
            operation_id=f"http-schema-discovery:{uuid4()}",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ) as discovery:
            _provide_operation(discovery, db, current_user.id, request)
            discovered = await _resolver(discovery).discover_scope(discovery, project_id)
        if requested_tenant is not None and requested_tenant != discovered.tenant_id:
            raise SchemaAccessDeniedV2
        operation = OperationContextV2(
            generation=generation,
            operation_id=f"http-schema-application:{uuid4()}",
            scope=ScopeV2(
                kind=ScopeKindV2.PROJECT,
                tenant_id=discovered.tenant_id,
                project_id=discovered.project_id,
            ),
        )
        async with operation:
            _provide_operation(operation, db, current_user.id, request)
            services = _resolver(operation).resolve(operation)
            await services.authorization.authorize(services.scope, ProjectSchemaAction.READ)
            yield SchemaApplicationAuthorityV2(operation=operation, db=db, services=services)
    except (SchemaAccessDeniedV2, ProjectSchemaError) as error:
        if isinstance(error, ProjectSchemaError) and error.code != "project_schema_access_denied":
            raise
        raise HTTPException(status_code=403, detail=_("Access denied to project")) from error


def _provide_operation(
    operation: OperationContextV2, db: AsyncSession, user_id: str, request: Request
) -> None:
    scope = operation.context.scope
    _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
    _ = operation.provide(
        OPERATION_IDENTITY_SERVICE_V2,
        {
            "tenant_id": scope.tenant_id,
            "project_id": scope.project_id,
            "user_id": user_id,
        },
    )
    _ = operation.provide(
        OPERATION_METADATA_SERVICE_V2,
        {
            "kind": "http-authority",
            "method": request.method,
            "path": request.url.path,
        },
    )


def _resolver(operation: OperationContextV2) -> SchemaApplicationResolverProtocolV2:
    resolver = operation.require(SCHEMA_APPLICATION_SERVICE_V2)
    if not isinstance(resolver, SchemaApplicationResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_schema_application_resolver",
            "schema application service has an invalid implementation",
        )
    return resolver


def _scope_id_v2(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


__all__ = [
    "SchemaApplicationAuthorityV2",
    "schema_application_authority_dependency_v2",
]
