"""Production endpoints for the signed optional-business runtime."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    resolve_plugin_publication_scope_v2,
    resolve_plugin_read_scope_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
    SignedOptionalBusinessRuntimeV2,
    SignedPackageBytesV2,
)
from src.infrastructure.plugins.sdk_path import ensure_plugin_sdk_path

ensure_plugin_sdk_path()

from memstack_plugin_sdk.contract import parse_contribution


class OptionalBusinessInstallV2(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    project_id: str = Field(min_length=1, max_length=64)
    plugin_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=32)
    digest: str = Field(min_length=7, max_length=80)
    wasm_base64: str
    contribution: dict[str, Any]
    ui_files: dict[str, str] = Field(default_factory=dict)
    approved_permissions: list[str]


class OptionalBusinessScopeV2(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    project_id: str = Field(min_length=1, max_length=64)


class OptionalBusinessInvokeV2(OptionalBusinessScopeV2):
    tool_name: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any]


class OptionalBusinessCommandV2(OptionalBusinessScopeV2):
    command_id: str = Field(min_length=1, max_length=128)


class OptionalBusinessStorageV2(OptionalBusinessScopeV2):
    document: dict[str, Any]


def runtime_from_request_v2(request: Request) -> SignedOptionalBusinessRuntimeV2:
    runtime = getattr(request.app.state, "optional_business_runtime_v2", None)
    if not isinstance(runtime, SignedOptionalBusinessRuntimeV2):
        raise HTTPException(503, _("Optional business runtime is unavailable"))
    return runtime


def _scope(tenant_id: str, project_id: str) -> ScopeV2:
    return ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id=tenant_id, project_id=project_id)


def _binding(tenant_id: str, project_id: str) -> ScopeBindingV2:
    return ScopeBindingV2(tenant_id=tenant_id, project_id=project_id)


def _http(error: Exception) -> HTTPException:
    if isinstance(error, RuntimeV2Error):
        status = 404 if error.code == "scope_resource_unavailable" else 403
        return HTTPException(status, _(str(error)))
    if isinstance(error, OptionalBusinessError):
        status = 409 if error.code in {"apply_failed", "rollback_unavailable"} else 403
        return HTTPException(status, _(str(error)))
    return HTTPException(400, _(str(error)))


async def _authorize_write(
    db: AsyncSession, user: User, tenant_id: str, project_id: str
) -> None:
    try:
        await resolve_plugin_publication_scope_v2(
            db, current_user=user, requested_scope=_scope(tenant_id, project_id)
        )
    except RuntimeV2Error as exc:
        raise _http(exc) from exc


async def install_optional_business_v2(
    body: OptionalBusinessInstallV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await _authorize_write(db, current_user, body.tenant_id, body.project_id)
    import base64

    try:
        wasm = base64.b64decode(body.wasm_base64, validate=True)
        contribution = parse_contribution(body.contribution)
        ui_files = {
            path: base64.b64decode(content, validate=True) for path, content in body.ui_files.items()
        }
        runtime_from_request_v2(request).record(
            SignedPackageBytesV2(
                plugin_id=body.plugin_id,
                version=body.version,
                digest=body.digest,
                wasm=wasm,
                contribution=contribution,
                ui_files=ui_files,
                approved_permissions=frozenset(body.approved_permissions),
            )
        )
    except Exception as exc:
        raise _http(exc) from exc
    return {"status": "recorded", "plugin_id": body.plugin_id}


async def projection_optional_business_v2(
    plugin_id: str,
    tenant_id: str,
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        await resolve_plugin_read_scope_v2(
            db, current_user=current_user, requested_scope=_scope(tenant_id, project_id)
        )
    except RuntimeV2Error as exc:
        raise _http(exc) from exc
    view = runtime_from_request_v2(request).projection(plugin_id)
    return {
        "plugin_id": view.plugin_id,
        "version": view.version,
        "source": view.source,
        "package_recorded": view.package_recorded,
        "desired_enabled": view.desired_enabled,
        "runtime_phase": view.runtime_phase,
        "ui_mounted": view.ui_mounted,
        "sync": view.sync,
        "desired_revision": view.desired_revision,
        "actual_generation": view.actual_generation,
        "desired_digest": view.desired_digest,
        "actual_digest": view.actual_digest,
        "failure": view.failure,
        "retention": view.retention,
    }


async def _mutate(
    plugin_id: str,
    body: OptionalBusinessScopeV2,
    request: Request,
    current_user: User,
    db: AsyncSession,
    action: str,
) -> dict[str, Any]:
    await _authorize_write(db, current_user, body.tenant_id, body.project_id)
    runtime = runtime_from_request_v2(request)
    try:
        if action == "enable":
            runtime.enable(plugin_id)
        elif action == "disable":
            runtime.disable(plugin_id)
        elif action == "uninstall":
            runtime.uninstall(plugin_id)
        elif action == "purge":
            runtime.purge(plugin_id, _binding(body.tenant_id, body.project_id))
        elif action == "rollback":
            runtime.rollback(plugin_id)
        else:
            raise OptionalBusinessError("action", "unknown lifecycle action")
    except OptionalBusinessError as exc:
        raise _http(exc) from exc
    view = runtime.projection(plugin_id)
    return {"status": action, "runtime_phase": view.runtime_phase, "retention": view.retention}


async def enable_optional_business_v2(
    plugin_id: str,
    body: OptionalBusinessScopeV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _mutate(plugin_id, body, request, current_user, db, "enable")


async def disable_optional_business_v2(
    plugin_id: str,
    body: OptionalBusinessScopeV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _mutate(plugin_id, body, request, current_user, db, "disable")


async def uninstall_optional_business_v2(
    plugin_id: str,
    body: OptionalBusinessScopeV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _mutate(plugin_id, body, request, current_user, db, "uninstall")


async def purge_optional_business_v2(
    plugin_id: str,
    body: OptionalBusinessScopeV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _mutate(plugin_id, body, request, current_user, db, "purge")


async def rollback_optional_business_v2(
    plugin_id: str,
    body: OptionalBusinessScopeV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _mutate(plugin_id, body, request, current_user, db, "rollback")


async def invoke_optional_business_v2(
    plugin_id: str,
    body: OptionalBusinessInvokeV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _authorize_write(db, current_user, body.tenant_id, body.project_id)
    try:
        return runtime_from_request_v2(request).session(
            plugin_id, _binding(body.tenant_id, body.project_id)
        ).invoke(body.tool_name, body.payload)
    except OptionalBusinessError as exc:
        raise _http(exc) from exc


async def command_optional_business_v2(
    plugin_id: str,
    body: OptionalBusinessCommandV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _authorize_write(db, current_user, body.tenant_id, body.project_id)
    try:
        return runtime_from_request_v2(request).dispatch_command(
            plugin_id, _binding(body.tenant_id, body.project_id), body.command_id
        )
    except OptionalBusinessError as exc:
        raise _http(exc) from exc


async def put_optional_business_storage_v2(
    plugin_id: str,
    item_key: str,
    body: OptionalBusinessStorageV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await _authorize_write(db, current_user, body.tenant_id, body.project_id)
    try:
        runtime_from_request_v2(request).storage_put(
            plugin_id, _binding(body.tenant_id, body.project_id), item_key, body.document
        )
    except OptionalBusinessError as exc:
        raise _http(exc) from exc
    return {"status": "stored"}


async def get_optional_business_storage_v2(
    plugin_id: str,
    item_key: str,
    tenant_id: str,
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        await resolve_plugin_read_scope_v2(
            db, current_user=current_user, requested_scope=_scope(tenant_id, project_id)
        )
    except RuntimeV2Error as exc:
        raise _http(exc) from exc
    try:
        document = runtime_from_request_v2(request).storage_get(
            plugin_id, _binding(tenant_id, project_id), item_key
        )
    except OptionalBusinessError as exc:
        raise _http(exc) from exc
    return {"document": document}


async def ui_optional_business_v2(
    plugin_id: str,
    tenant_id: str,
    project_id: str,
    target: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        await resolve_plugin_read_scope_v2(
            db, current_user=current_user, requested_scope=_scope(tenant_id, project_id)
        )
    except RuntimeV2Error as exc:
        raise _http(exc) from exc
    try:
        return runtime_from_request_v2(request).mount_ui(
            plugin_id, "tool_result_renderer", target
        )
    except OptionalBusinessError as exc:
        raise _http(exc) from exc
