"""Project-scoped browsing and reviewed activation of local npm plugin releases."""

from typing import Annotated, Any

from fastapi import Depends, Query, Request
from jsonschema.exceptions import SchemaError
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.config import get_settings
from src.host.packages.npm_source import fetch_npm_archive, npm_plugin_id
from src.host.packages.project_market import View, market_catalog, market_detail
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    project_package_actor_can_execute,
    resolve_plugin_publication_scope_v2,
)
from src.infrastructure.adapters.primary.web.routers.optional_business_http_v2 import (
    NpmReleaseRequest,
    _authorize_write,
    _http,
    _scope,
    _service,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

Actor = Annotated[User, Depends(get_current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]
ScopeId = Annotated[str, Query(min_length=1, max_length=64)]


async def _market_access(
    db: AsyncSession, user: User, tenant: str, project: str
) -> dict[str, bool]:
    scope = _scope(tenant, project)
    try:
        execute = await project_package_actor_can_execute(
            db, current_user=user, requested_scope=scope
        )
    except RuntimeV2Error as exc:
        raise _http(exc) from exc
    try:
        await resolve_plugin_publication_scope_v2(db, current_user=user, requested_scope=scope)
    except RuntimeV2Error as exc:
        if exc.code == "scope_write_forbidden":
            return {"can_manage": False, "can_execute": execute}
        raise _http(exc) from exc
    return {"can_manage": True, "can_execute": execute}


async def browse_npm_market(
    request: Request,
    tenant_id: ScopeId,
    project_id: ScopeId,
    current_user: Actor,
    db: Db,
    q: Annotated[str, Query(max_length=160)] = "",
    view: View = "all",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
) -> dict[str, Any]:
    access = await _market_access(db, current_user, tenant_id, project_id)
    result = await market_catalog(
        _service(request, db, tenant_id, project_id),
        get_settings().package_npm_registry_url,
        query=q,
        view=view,
        offset=offset,
        limit=limit,
    )
    return {**result, **access}


async def read_npm_market_release(
    request: Request,
    tenant_id: ScopeId,
    project_id: ScopeId,
    current_user: Actor,
    db: Db,
    plugin_id: Annotated[str, Query(min_length=1, max_length=128)],
    package_name: Annotated[str | None, Query(min_length=1, max_length=214)] = None,
    version: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
) -> dict[str, Any]:
    access = await _market_access(db, current_user, tenant_id, project_id)
    try:
        result = await market_detail(
            _service(request, db, tenant_id, project_id),
            get_settings().package_npm_registry_url,
            plugin=plugin_id,
            name=package_name,
            version=version,
        )
    except (ValueError, OptionalBusinessError) as exc:
        raise _http(exc) from exc
    return {**result, **access}


class ApplyNpmRelease(NpmReleaseRequest):
    approved_permissions: list[str] = Field(max_length=100)
    expected_revision: int = Field(ge=0, strict=True)
    expected_digest: str = Field(pattern="^sha256:[a-f0-9]{64}$")


async def apply_npm_market_release(
    body: ApplyNpmRelease,
    request: Request,
    current_user: Actor,
    db: Db,
) -> dict[str, Any]:
    await _authorize_write(db, current_user, body.tenant_id, body.project_id)
    service = _service(request, db, body.tenant_id, body.project_id, actor_id=current_user.id)
    try:
        plugin = npm_plugin_id(body.package_name, body.version)
        archive = await fetch_npm_archive(
            get_settings().package_npm_registry_url, body.package_name, body.version
        )
        await _authorize_write(db, current_user, body.tenant_id, body.project_id)
        await service.record_selection(
            archive,
            frozenset(body.approved_permissions),
            current_user.id,
            expected_revision=body.expected_revision,
            expected_digest=body.expected_digest,
            expected_identity=(plugin, body.version),
            activate=True,
        )
    except (ValueError, KeyError, TypeError, SchemaError, OptionalBusinessError) as exc:
        raise _http(exc) from exc
    return await service.projection(plugin)
