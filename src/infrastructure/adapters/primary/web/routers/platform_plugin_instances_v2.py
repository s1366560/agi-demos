"""Authorized ordinary instance configuration; credentials retain their own API."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    resolve_plugin_publication_scope_v2,
    resolve_plugin_read_scope_v2,
)
from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
    ScopedProfileRuntimeV2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error
from src.infrastructure.plugins.v2.scope import parse_scope_v2

router = APIRouter(prefix="/v2", tags=["Platform Plugins V2"])


class InstanceApplyRequestV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str = Field(min_length=1)
    project_id: str | None = Field(default=None, min_length=1)
    expected_revision: int = Field(ge=1, strict=True)
    changes: list[dict[str, Any]] = Field(min_length=1, max_length=500)


def instance_runtime_v2(request: Request) -> ScopedProfileRuntimeV2:
    runtime = getattr(request.app.state, "scoped_profile_runtime_v2", None)
    if not isinstance(runtime, ScopedProfileRuntimeV2):
        raise HTTPException(
            503,
            detail={
                "code": "scoped_runtime_missing",
                "message": _("Plugin configuration is unavailable"),
            },
        )
    return runtime


def instance_error_v2(error: ValueError | RuntimeV2Error) -> HTTPException:
    code = getattr(error, "code", "instance_configuration_invalid")
    return HTTPException(
        403
        if code in {"scope_read_forbidden", "scope_write_forbidden"}
        else 404
        if code == "scope_resource_unavailable"
        else 409,
        detail={"code": code, "message": _("Plugin configuration could not be applied")},
    )


def instance_scope_v2(tenant_id: str, project_id: str | None) -> ScopeV2:
    return parse_scope_v2(
        {
            "kind": "tenant" if project_id is None else "project",
            "tenant_id": tenant_id,
            **({} if project_id is None else {"project_id": project_id}),
        }
    )


@router.get("/instances")
async def get_plugin_instances_v2(
    request: Request,
    response: Response,
    tenant_id: str = Query(min_length=1),
    project_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        scope = await resolve_plugin_read_scope_v2(
            db, current_user=current_user, requested_scope=instance_scope_v2(tenant_id, project_id)
        )
        service = instance_runtime_v2(request).instances(scope)
        await service.initialize(current_user.id)
        view = await service.view()
        try:
            await resolve_plugin_publication_scope_v2(
                db, current_user=current_user, requested_scope=scope
            )
        except RuntimeV2Error:
            for row in view["instances"]:
                row.update(
                    editable=False, config_editable=False, reason_code="scope_write_forbidden"
                )
        await resolve_plugin_read_scope_v2(db, current_user=current_user, requested_scope=scope)
        return view
    except (ValueError, RuntimeV2Error) as error:
        raise instance_error_v2(error) from error


@router.post("/instances/apply")
async def apply_plugin_instances_v2(
    payload: InstanceApplyRequestV2,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        scope = await resolve_plugin_publication_scope_v2(
            db,
            current_user=current_user,
            requested_scope=instance_scope_v2(payload.tenant_id, payload.project_id),
        )
        service = instance_runtime_v2(request).instances(scope)
        await service.initialize(current_user.id)

        async def authorize(session: AsyncSession) -> None:
            await resolve_plugin_publication_scope_v2(
                session, current_user=current_user, requested_scope=scope
            )

        return await service.apply(
            actor_id=current_user.id,
            expected_revision=payload.expected_revision,
            changes=payload.changes,
            authorize=authorize,
        )
    except (ValueError, RuntimeV2Error) as error:
        raise instance_error_v2(error) from error
