"""Authenticated project administration and online device package admission."""

import hashlib
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.device_plugin_grants import (
    DeviceAdmissionView,
    DeviceGrantView,
    DevicePackageApproval,
    DevicePackageBinding,
    DevicePackageCheck,
    Operation,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.host.operations.project_package_audit import project_operation
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_current_user,
    verify_api_key_dependency,
)
from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    project_package_actor_can_execute,
    resolve_plugin_publication_scope_v2,
    resolve_plugin_read_scope_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.device_plugin_grant_model import (
    DevicePluginGrant,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    APIKey,
    Project,
    User,
    UserSession,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/device-plugin-grants", tags=["Device plugins"]
)


def _denied() -> HTTPException:
    return HTTPException(403, detail=_("Device package operation is not authorized"))


async def _cloud_user(
    user: User = Depends(get_current_user),
    key: APIKey = Depends(verify_api_key_dependency),
    db: AsyncSession = Depends(get_db),
) -> User:
    active = await db.scalar(
        select(UserSession.id).where(
            UserSession.user_id == user.id,
            UserSession.access_api_key_id == key.id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.now(UTC),
        )
    )
    if not active or not user.is_active:
        raise HTTPException(401, detail=_("An active cloud login session is required"))
    return user


async def _scope(
    db: AsyncSession, project_id: str, user: User, *, access: Literal["manage", "read", "execute"]
) -> ScopeV2:
    query = select(Project.tenant_id).where(Project.id == project_id)
    if access == "manage":
        # Serialize overlapping approvals/revocations; each stale handle keeps its old grant ID.
        query = query.with_for_update()
    tenant_id = await db.scalar(query)
    if tenant_id is None:
        raise _denied()
    scope = ScopeV2(kind=ScopeKindV2.PROJECT, project_id=project_id, tenant_id=tenant_id)
    try:
        if access == "execute":
            if not await project_package_actor_can_execute(
                db, current_user=user, requested_scope=scope
            ):
                raise _denied()
            return scope
        resolver = (
            resolve_plugin_publication_scope_v2
            if access == "manage"
            else resolve_plugin_read_scope_v2
        )
        return await resolver(db, current_user=user, requested_scope=scope)
    except RuntimeV2Error as error:
        raise _denied() from error


async def _current_grant(
    db: AsyncSession, scope: ScopeV2, user_id: str, binding: DevicePackageBinding, fingerprint: str
) -> DevicePluginGrant | None:
    matches = await db.scalars(
        select(DevicePluginGrant)
        .where(
            DevicePluginGrant.project_id == scope.project_id,
            DevicePluginGrant.tenant_id == scope.tenant_id,
            DevicePluginGrant.user_id == user_id,
            DevicePluginGrant.machine_id == binding.machine_id,
            DevicePluginGrant.device_fingerprint == fingerprint,
            DevicePluginGrant.bundle_digest == binding.bundle_digest,
            DevicePluginGrant.generation_id == binding.generation_id,
            DevicePluginGrant.revoked_at.is_(None),
            DevicePluginGrant.expires_at > datetime.now(UTC),
        )
        .execution_options(populate_existing=True)
    )
    return matches.first()


def _view(grant: DevicePluginGrant) -> DeviceGrantView:
    return DeviceGrantView(
        grant_id=grant.id,
        project_id=grant.project_id,
        tenant_id=grant.tenant_id,
        user_id=grant.user_id,
        machine_id=grant.machine_id,
        bundle_digest=grant.bundle_digest,
        generation_id=grant.generation_id,
        device_fingerprint=grant.device_fingerprint,
        permissions=cast(list[Operation], grant.permissions),
        approved_permissions=grant.approved_permissions,
        expires_at=grant.expires_at.replace(tzinfo=UTC)
        if grant.expires_at.tzinfo is None
        else grant.expires_at,
    )


@router.get("/authority")
async def device_package_authority(
    project_id: str, user: User = Depends(_cloud_user), db: AsyncSession = Depends(get_db)
) -> dict[str, bool]:
    scope = await _scope(db, project_id, user, access="read")
    try:
        await resolve_plugin_publication_scope_v2(db, current_user=user, requested_scope=scope)
    except RuntimeV2Error as error:
        if error.code == "scope_write_forbidden":
            return {"can_manage": False}
        raise _denied() from error
    return {"can_manage": True}


@router.post("/", status_code=201)
async def approve_device_package(
    project_id: str,
    body: DevicePackageApproval,
    user: User = Depends(_cloud_user),
    db: AsyncSession = Depends(get_db),
) -> DeviceGrantView:
    with project_operation("device.approve", actor_id=user.id) as audit:
        scope = await _scope(db, project_id, user, access="manage")
        audit.tenant_id, audit.project_id = scope.tenant_id, scope.project_id
        target = await db.get(User, body.user_id)
        if target is None or not target.is_active:
            raise _denied()
        await _scope(db, project_id, target, access="execute")
        audit.subject_id = target.id
        audit.digest, audit.generation_id = body.bundle_digest, body.generation_id
        now = datetime.now(UTC)
        if body.expires_at <= now:
            raise HTTPException(422, detail=_("Device grant expiry must be in the future"))
        previous = await _current_grant(db, scope, target.id, body, body.device_fingerprint)
        if previous:
            view = _view(previous)
            if (
                set(view.permissions) == set(body.permissions)
                and set(view.approved_permissions) == set(body.approved_permissions)
                and view.expires_at == body.expires_at
            ):
                return view
            previous.revoked_at = now
        grant = DevicePluginGrant(
            id=str(uuid4()),
            user_id=target.id,
            approved_by=user.id,
            tenant_id=scope.tenant_id,
            project_id=project_id,
            machine_id=body.machine_id,
            generation_id=body.generation_id,
            bundle_digest=body.bundle_digest,
            permissions=sorted(set(body.permissions)),
            approved_permissions=sorted(set(body.approved_permissions)),
            device_fingerprint=body.device_fingerprint,
            expires_at=body.expires_at.astimezone(UTC),
        )
        db.add(grant)
        view = _view(grant)
        await db.commit()
        return view


@router.post("/check")
async def check_device_package(
    project_id: str,
    body: DevicePackageCheck,
    response: Response,
    user: User = Depends(_cloud_user),
    db: AsyncSession = Depends(get_db),
) -> DeviceAdmissionView:
    with project_operation("device.check", actor_id=user.id) as audit:
        scope = await _scope(db, project_id, user, access="execute")
        audit.tenant_id, audit.project_id = scope.tenant_id, scope.project_id
        fingerprint = (
            "sha256:" + hashlib.sha256(body.device_proof.get_secret_value().encode()).hexdigest()
        )
        grant = await _current_grant(db, scope, user.id, body, fingerprint)
        if (
            grant is None
            or body.permission not in grant.permissions
            or (
                (body.permission == "invoke" or body.grant_id is not None)
                and body.grant_id != grant.id
            )
            or not set(body.approved_permissions).issubset(grant.approved_permissions)
        ):
            raise _denied()
        audit.digest, audit.generation_id = grant.bundle_digest, grant.generation_id
        response.headers["Cache-Control"] = "no-store"
        return DeviceAdmissionView(
            grant_id=grant.id,
            project_id=project_id,
            tenant_id=grant.tenant_id,
            user_id=user.id,
            machine_id=grant.machine_id,
            bundle_digest=grant.bundle_digest,
            generation_id=grant.generation_id,
            approved_permissions=sorted(set(body.approved_permissions)),
            permission=body.permission,
        )


@router.delete("/{grant_id}", status_code=204)
async def revoke_device_package(
    project_id: str,
    grant_id: str,
    user: User = Depends(_cloud_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    with project_operation("device.revoke", actor_id=user.id) as audit:
        scope = await _scope(db, project_id, user, access="manage")
        audit.tenant_id, audit.project_id = scope.tenant_id, scope.project_id
        grant = await db.scalar(
            select(DevicePluginGrant)
            .where(
                DevicePluginGrant.id == grant_id,
                DevicePluginGrant.project_id == project_id,
                DevicePluginGrant.tenant_id == scope.tenant_id,
            )
            .execution_options(populate_existing=True)
        )
        if grant is None:
            raise HTTPException(404, detail=_("Device package grant was not found"))
        audit.subject_id = grant.user_id
        audit.digest, audit.generation_id = grant.bundle_digest, grant.generation_id
        if grant.revoked_at is None:
            grant.revoked_at = datetime.now(UTC)
            await db.commit()
        return Response(status_code=204)
