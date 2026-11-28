"""HTTP API for signed tenant pages, independent of project creation or selection."""

import base64
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from src.configuration.config import get_settings
from src.host.operations.tenant_commands import TenantPackageContext, tenant_command
from src.host.packages.npm_source import fetch_npm_archive, npm_plugin_id
from src.host.packages.project_installation_view import market_installation
from src.host.packages.project_market import View, market_catalog, market_detail
from src.host.packages.rich_pages import rich_page_resource
from src.host.packages.tenant_installation import TenantPackageService
from src.host.transport.project_marketplace import Actor, Db, ScopeId
from src.infrastructure.adapters.primary.web.routers.optional_business_http_v2 import (
    _http,
    _inspection,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import Tenant, UserTenant
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

router = APIRouter(prefix="/api/v1/tenant-packages", tags=["Tenant Packages"])
errors = (ValueError, OptionalBusinessError, SchemaError, KeyError, TypeError)
Digest = Annotated[str, Field(pattern="^sha256:[a-f0-9]{64}$")]
Revision = Annotated[int, Field(ge=0, strict=True)]


class TenantBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str = Field(min_length=1, max_length=64)


class Archive(TenantBody):
    archive_base64: str = Field(min_length=1, max_length=16 * 1024 * 1024)


class Approval(TenantBody):
    approved_permissions: list[str] = Field(max_length=100)
    expected_revision: Revision
    expected_digest: Digest


class Apply(Approval):
    package_name: str = Field(min_length=1, max_length=214)
    version: str = Field(min_length=1, max_length=128)


class Install(Archive, Approval):
    pass


class Change(TenantBody):
    expected_revision: Revision


class Command(TenantBody):
    expected_digest: Digest
    command_id: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] | None = None


def flags(role: str) -> dict[str, bool]:
    return {
        "can_manage": role in ("owner", "admin"),
        "can_execute": role in ("owner", "admin", "member"),
    }


async def access(db: Db, actor: Actor, tenant: str, require: str = "read") -> dict[str, bool]:
    role = await db.scalar(
        select(UserTenant.role).where(
            UserTenant.tenant_id == tenant, UserTenant.user_id == actor.id
        )
    )
    if not role or not actor.is_active:
        raise HTTPException(403, _("Tenant membership is required"))
    allowed = flags(role)
    if require != "read" and not allowed[require]:
        raise HTTPException(403, _("Tenant permission is required"))
    return allowed


def service(req: Request, db: Db, tenant: str, actor: Actor) -> TenantPackageService:
    return TenantPackageService(
        db,
        tenant,
        tuple(getattr(req.app.state, "plugin_marketplace_trusted_public_keys_v2", ())),
        actor.id,
    )


async def management(req: Request, db: Db, tenant: str, actor: Actor) -> TenantPackageService:
    await access(db, actor, tenant, "can_manage")
    packages = service(req, db, tenant, actor)
    await packages.lock()
    await access(db, actor, tenant, "can_manage")
    return packages


@router.get("/tenants")
async def tenants(db: Db, current_user: Actor) -> dict[str, Any]:
    rows = (
        await db.execute(
            refresh_select_statement(
                select(Tenant.id, Tenant.name, UserTenant.role)
                .join(UserTenant, UserTenant.tenant_id == Tenant.id)
                .where(UserTenant.user_id == current_user.id)
                .order_by(Tenant.name, Tenant.id)
            )
        )
    ).all()
    return {
        "items": [
            {"tenant_id": tenant, "name": name, **flags(role)}
            for tenant, name, role in rows
            if current_user.is_active
        ]
    }


@router.get("/")
async def installed(
    request: Request, tenant_id: ScopeId, current_user: Actor, db: Db
) -> dict[str, Any]:
    await access(db, current_user, tenant_id)
    packages = service(request, db, tenant_id, current_user)
    return {
        "items": [
            market_installation(plugin, await packages.projection(plugin), "tenant")
            for plugin in await packages.installed_ids()
        ]
    }


@router.get("/npm/catalog")
async def catalog(
    request: Request,
    tenant_id: ScopeId,
    current_user: Actor,
    db: Db,
    q: Annotated[str, Query(max_length=160)] = "",
    view: View = "all",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
) -> dict[str, Any]:
    allowed = await access(db, current_user, tenant_id)
    result = await market_catalog(
        service(request, db, tenant_id, current_user),
        get_settings().package_npm_registry_url,
        query=q,
        view=view,
        offset=offset,
        limit=limit,
        scope="tenant",
    )
    return {**result, **allowed}


@router.get("/npm/detail")
async def detail(
    request: Request,
    tenant_id: ScopeId,
    current_user: Actor,
    db: Db,
    plugin_id: str,
    package_name: str | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    allowed = await access(db, current_user, tenant_id)
    try:
        result = await market_detail(
            service(request, db, tenant_id, current_user),
            get_settings().package_npm_registry_url,
            plugin=plugin_id,
            name=package_name,
            version=version,
            scope="tenant",
        )
    except errors as exc:
        raise _http(exc) from exc
    return {**result, **allowed}


@router.post("/npm/apply")
async def apply(body: Apply, request: Request, current_user: Actor, db: Db) -> dict[str, Any]:
    await access(db, current_user, body.tenant_id, "can_manage")
    try:
        plugin = npm_plugin_id(body.package_name, body.version)
        raw = await fetch_npm_archive(
            get_settings().package_npm_registry_url, body.package_name, body.version
        )
        packages = await management(request, db, body.tenant_id, current_user)
        await packages.record(
            raw,
            frozenset(body.approved_permissions),
            body.expected_revision,
            body.expected_digest,
            identity=(plugin, body.version),
            activate=True,
        )
        return await packages.projection(plugin)
    except errors as exc:
        raise _http(exc) from exc


@router.post("/inspect")
async def inspect(body: Archive, request: Request, current_user: Actor, db: Db) -> dict[str, Any]:
    await access(db, current_user, body.tenant_id)
    try:
        return _inspection(
            await service(request, db, body.tenant_id, current_user).inspect(
                base64.b64decode(body.archive_base64, validate=True)
            )
        )
    except errors as exc:
        raise _http(exc) from exc


@router.post("/install")
async def install(body: Install, request: Request, current_user: Actor, db: Db) -> dict[str, Any]:
    packages = await management(request, db, body.tenant_id, current_user)
    try:
        pkg = await packages.record(
            base64.b64decode(body.archive_base64, validate=True),
            frozenset(body.approved_permissions),
            body.expected_revision,
            body.expected_digest,
            identity=None,
            activate=False,
        )
        state = await packages.projection(pkg.plugin_id)
        return {
            **_inspection(pkg),
            "status": "recorded",
            "desired_revision": state["desired_revision"],
        }
    except errors as exc:
        raise _http(exc) from exc


@router.get("/{plugin_id}")
async def projection(
    plugin_id: str, request: Request, tenant_id: ScopeId, current_user: Actor, db: Db
) -> dict[str, Any]:
    await access(db, current_user, tenant_id)
    return await service(request, db, tenant_id, current_user).projection(plugin_id)


@router.get("/{plugin_id}/ui")
async def page(
    plugin_id: str,
    request: Request,
    tenant_id: ScopeId,
    current_user: Actor,
    db: Db,
    page_id: str,
    target: str,
    expected_digest: Digest,
) -> dict[str, Any]:
    await access(db, current_user, tenant_id)
    try:
        pkg = await service(request, db, tenant_id, current_user).active(plugin_id, expected_digest)
        return rich_page_resource(pkg, page_id, target, scope="tenant")
    except errors as exc:
        raise _http(exc) from exc


@router.post("/{plugin_id}/commands")
async def commands(
    plugin_id: str, body: Command, request: Request, current_user: Actor, db: Db
) -> dict[str, Any]:
    await access(db, current_user, body.tenant_id, "can_execute")
    try:
        packages = service(request, db, body.tenant_id, current_user)
        pkg = await packages.active(plugin_id, body.expected_digest)
        return await tenant_command(
            TenantPackageContext(request, db, current_user, packages.scope),
            pkg,
            body.command_id,
            body.payload,
        )
    except errors as exc:
        raise _http(exc) from exc


@router.post("/{plugin_id}/{action}")
async def mutate(
    plugin_id: str,
    action: Literal["enable", "disable", "uninstall", "rollback"],
    body: Change,
    request: Request,
    current_user: Actor,
    db: Db,
) -> dict[str, Any]:
    packages = await management(request, db, body.tenant_id, current_user)
    try:
        return await packages.mutate(plugin_id, action, body.expected_revision)
    except errors as exc:
        raise _http(exc) from exc
