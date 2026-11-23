"""Production endpoints for the signed optional-business runtime."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any, override

from anyio import CancelScope
from jsonschema.exceptions import SchemaError

from fastapi import Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.host.packages.project_plugin_installation import ProjectPluginInstallationService
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    project_package_actor_can_execute,
    resolve_plugin_publication_scope_v2,
    resolve_plugin_read_scope_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.host.operations.project_package_audit import project_operation
from src.infrastructure.plugins.v2.project_package_execution import (
    dispatch_project_command,
    invoke_project_tool,
    project_page,
)
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
)
from src.infrastructure.plugins.v2.plugin_namespace_store_v2 import PluginStorageError

if TYPE_CHECKING:
    from starlette.types import Send


class OptionalBusinessArchiveV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str = Field(min_length=1, max_length=64)
    project_id: str = Field(min_length=1, max_length=64)
    archive_base64: str = Field(min_length=1, max_length=16 * 1024 * 1024)


class OptionalBusinessInstallV2(OptionalBusinessArchiveV2):
    approved_permissions: list[str] = Field(max_length=32)


class OptionalBusinessScopeV2(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    project_id: str = Field(min_length=1, max_length=64)


class OptionalBusinessMutationV2(OptionalBusinessScopeV2):
    expected_revision: int | None = Field(default=None, ge=0, strict=True)


class OptionalBusinessInvokeV2(OptionalBusinessScopeV2):
    expected_digest: str | None = Field(None, pattern="^sha256:[0-9a-f]{64}$")
    tool_name: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any]


class OptionalBusinessCommandV2(OptionalBusinessScopeV2):
    payload: dict[str, Any] | None = None
    command_id: str = Field(min_length=1, max_length=128)
    expected_digest: str | None = Field(None, pattern="^sha256:[0-9a-f]{64}$")


class OptionalBusinessStorageV2(OptionalBusinessScopeV2):
    document: dict[str, Any]


def _service(
    request: Request,
    db: AsyncSession,
    tenant_id: str,
    project_id: str,
    *,
    actor_id: str | None = None,
) -> ProjectPluginInstallationService:
    keys = getattr(request.app.state, "plugin_marketplace_trusted_public_keys_v2", ())
    return ProjectPluginInstallationService(
        db, _binding(tenant_id, project_id), tuple(keys), actor_id=actor_id
    )


def _scope(tenant_id: str, project_id: str) -> ScopeV2:
    return ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id=tenant_id, project_id=project_id)


def _binding(tenant_id: str, project_id: str) -> ScopeBindingV2:
    return ScopeBindingV2(tenant_id=tenant_id, project_id=project_id)


def _http(error: Exception) -> HTTPException:
    if isinstance(error, RuntimeV2Error):
        status = 404 if error.code == "scope_resource_unavailable" else 403
        return HTTPException(status, _(str(error)))
    if isinstance(error, OptionalBusinessError):
        if error.code == "invalid_package":
            return HTTPException(400, _(str(error)))
        if error.code == "quota_exceeded":
            return HTTPException(413, _(str(error)))
        if error.code == "busy":
            return HTTPException(429, _("Package concurrency limit reached"))
        status = 409 if error.code in {"apply_failed", "rollback_unavailable", "conflict"} else 403
        return HTTPException(status, _(str(error)))
    return HTTPException(400, _(str(error)))


async def _authorize_write(db: AsyncSession, user: User, tenant_id: str, project_id: str) -> None:
    with project_operation("authorize.manage", actor_id=user.id, failures_only=True):
        try:
            await resolve_plugin_publication_scope_v2(
                db, current_user=user, requested_scope=_scope(tenant_id, project_id)
            )
        except RuntimeV2Error as exc:
            raise _http(exc) from exc


async def _authorize_execution(
    db: AsyncSession, user: User, tenant_id: str, project_id: str
) -> None:
    with project_operation("authorize.execute", actor_id=user.id, failures_only=True):
        try:
            fresh_user = await db.get(User, user.id, populate_existing=True)
            if fresh_user is None:
                raise HTTPException(403, _("Project execution permission is required"))
            allowed = await project_package_actor_can_execute(
                db, current_user=fresh_user, requested_scope=_scope(tenant_id, project_id)
            )
        except RuntimeV2Error as error:
            raise _http(error) from error
        if not allowed:
            raise HTTPException(403, _("Project execution permission is required"))


async def list_project_packages(
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
    except RuntimeV2Error as error:
        raise _http(error) from error
    items = await _service(request, db, tenant_id, project_id).marketplace_items()
    return {"items": items}


async def inspect_optional_business_v2(
    body: OptionalBusinessArchiveV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _authorize_write(db, current_user, body.tenant_id, body.project_id)
    try:
        service = _service(request, db, body.tenant_id, body.project_id, actor_id=current_user.id)
        package = await service.inspect(base64.b64decode(body.archive_base64, validate=True))
    except (ValueError, KeyError, TypeError, SchemaError, OptionalBusinessError) as exc:
        raise _http(exc) from exc
    return {
        "plugin_id": package.plugin_id,
        "version": package.version,
        "digest": package.digest,
        "permissions": sorted(package.approved_permissions),
        "kind": package.kind,
        "targets": list(package.targets),
        **(
            {
                "requires": [
                    {"alias": r.alias, "service": r.service, "version": r.version}
                    for r in package.services.requires
                ]
            }
            if package.services.requires
            else {}
        ),
        **(
            {
                "provides": [
                    {"service": r.service, "version": r.version} for r in package.services.provides
                ]
            }
            if package.services.provides
            else {}
        ),
    }


async def install_optional_business_v2(
    body: OptionalBusinessInstallV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await _authorize_write(db, current_user, body.tenant_id, body.project_id)
    try:
        raw = base64.b64decode(body.archive_base64, validate=True)
        package = await _service(
            request, db, body.tenant_id, body.project_id, actor_id=current_user.id
        ).record(raw, frozenset(body.approved_permissions), current_user.id)
    except (ValueError, KeyError, TypeError, SchemaError, OptionalBusinessError) as exc:
        raise _http(exc) from exc
    return {
        "status": "recorded",
        "plugin_id": package.plugin_id,
        "version": package.version,
        "digest": package.digest,
    }


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
    return await _service(request, db, tenant_id, project_id).projection(plugin_id)


async def _mutate(
    plugin_id: str,
    body: OptionalBusinessMutationV2,
    request: Request,
    current_user: User,
    db: AsyncSession,
    action: str,
) -> dict[str, Any]:
    await _authorize_write(db, current_user, body.tenant_id, body.project_id)
    try:
        view = await _service(
            request, db, body.tenant_id, body.project_id, actor_id=current_user.id
        ).mutate(plugin_id, action, expected_revision=body.expected_revision)
    except (ValueError, OptionalBusinessError, PluginStorageError) as exc:
        raise _http(exc) from exc
    return {
        "status": action,
        "runtime_phase": view["runtime_phase"],
        "retention": view["retention"],
    }


async def enable_optional_business_v2(
    plugin_id: str,
    body: OptionalBusinessMutationV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _mutate(plugin_id, body, request, current_user, db, "enable")


async def disable_optional_business_v2(
    plugin_id: str,
    body: OptionalBusinessMutationV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _mutate(plugin_id, body, request, current_user, db, "disable")


async def uninstall_optional_business_v2(
    plugin_id: str,
    body: OptionalBusinessMutationV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _mutate(plugin_id, body, request, current_user, db, "uninstall")


async def purge_optional_business_v2(
    plugin_id: str,
    body: OptionalBusinessMutationV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _mutate(plugin_id, body, request, current_user, db, "purge")


async def rollback_optional_business_v2(
    plugin_id: str,
    body: OptionalBusinessMutationV2,
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
    await _authorize_execution(db, current_user, body.tenant_id, body.project_id)
    try:
        scope = _binding(body.tenant_id, body.project_id)
        return await _service(
            request, db, body.tenant_id, body.project_id, actor_id=current_user.id
        ).call_active(
            plugin_id,
            lambda package: invoke_project_tool(package, scope, body.tool_name, body.payload),
            operation_kind="tool",
            expected_digest=body.expected_digest,
            check_access=lambda: _authorize_execution(
                db, current_user, body.tenant_id, body.project_id
            ),
        )
    except (ValueError, OptionalBusinessError, PluginStorageError) as exc:
        raise _http(exc) from exc


async def _stream_digest(
    service: ProjectPluginInstallationService, plugin: str, expected_digest: str | None
) -> str:
    view = await service.projection(plugin)
    active = view["actual_digest"]
    if not isinstance(active, str):
        raise HTTPException(409, _("Package has no active release"))
    if expected_digest is not None and expected_digest != active:
        raise HTTPException(409, _("The package release changed"))
    return active


class _InvocationStream(StreamingResponse):
    def __init__(self, events: AsyncGenerator[bytes, None]) -> None:
        self._events = events
        super().__init__(
            events,
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @override
    async def stream_response(self, send: Send) -> None:
        try:
            await super().stream_response(send)
        finally:
            # A disconnected socket can interrupt send() after the generator yielded a chunk.
            with CancelScope(shield=True):
                await self._events.aclose()


async def stream_optional_business_v2(
    plugin_id: str,
    body: OptionalBusinessInvokeV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    await _authorize_execution(db, current_user, body.tenant_id, body.project_id)
    service = _service(request, db, body.tenant_id, body.project_id, actor_id=current_user.id)
    scope = _binding(body.tenant_id, body.project_id)
    digest = await _stream_digest(service, plugin_id, body.expected_digest)

    async def events() -> AsyncGenerator[bytes, None]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=16)

        async def progress(data: dict[str, Any]) -> None:
            await queue.put({"type": "progress", "data": data})

        async def execute() -> None:
            try:
                result = await service.call_active(
                    plugin_id,
                    lambda package: invoke_project_tool(
                        package, scope, body.tool_name, body.payload, progress
                    ),
                    operation_kind="tool",
                    expected_digest=digest,
                    check_access=lambda: _authorize_execution(
                        db, current_user, body.tenant_id, body.project_id
                    ),
                )
            except (ValueError, OptionalBusinessError) as error:
                await queue.put({"type": "error", "detail": str(error)[:512]})
            except Exception:
                await queue.put({"type": "error", "detail": _("Package execution failed")})
            else:
                await queue.put({"type": "result", "data": result})

        task = asyncio.create_task(execute())
        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=2.0)
                except TimeoutError:
                    if await request.is_disconnected():
                        break
                    # ASGI 2.4 also reports a lost socket on the next write.
                    yield b'{"type":"keepalive"}\n'
                    continue
                yield (json.dumps(message, ensure_ascii=False, allow_nan=False) + "\n").encode()
                if message["type"] != "progress":
                    break
        finally:
            # The ASGI disconnect scope is already cancelled. Let the worker drain its
            # call and relinquish its container and database lease before the response returns.
            with CancelScope(shield=True):
                _cancel_requested = task.cancel()
                _outcome = await asyncio.gather(task, return_exceptions=True)

    return _InvocationStream(events())


async def command_optional_business_v2(
    plugin_id: str,
    body: OptionalBusinessCommandV2,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _authorize_execution(db, current_user, body.tenant_id, body.project_id)
    try:
        scope = _binding(body.tenant_id, body.project_id)
        return await _service(
            request, db, body.tenant_id, body.project_id, actor_id=current_user.id
        ).call_active(
            plugin_id,
            lambda package: dispatch_project_command(package, scope, body.command_id, body.payload),
            operation_kind="command",
            expected_digest=body.expected_digest,
            check_access=lambda: _authorize_execution(
                db, current_user, body.tenant_id, body.project_id
            ),
        )
    except (ValueError, OptionalBusinessError, PluginStorageError) as exc:
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
        await _service(
            request, db, body.tenant_id, body.project_id, actor_id=current_user.id
        ).storage(plugin_id, item_key, body.document)
    except (ValueError, OptionalBusinessError, PluginStorageError) as exc:
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
        return await _service(request, db, tenant_id, project_id).storage(plugin_id, item_key, None)
    except (ValueError, OptionalBusinessError, PluginStorageError) as exc:
        raise _http(exc) from exc


async def ui_optional_business_v2(
    plugin_id: str,
    tenant_id: str,
    project_id: str,
    target: str,
    request: Request,
    expected_digest: str | None = None,
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
        package = await _service(request, db, tenant_id, project_id).active_release(
            plugin_id, expected_digest=expected_digest
        )
        return project_page(package, target)
    except (ValueError, OptionalBusinessError, PluginStorageError) as exc:
        raise _http(exc) from exc
