"""Cloud package authority used by the authenticated project Sandbox MCP gateway."""

import asyncio
import hashlib
import json
import re
from dataclasses import astuple, dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.host.packages.project_plugin_installation import (
    AgentPackagePin,
    ProjectPluginInstallationService,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_api_key_from_header,
    verify_api_key_dependency,
)
from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    project_package_actor_can_execute,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import Project, User
from src.infrastructure.adapters.secondary.persistence.project_plugin_installation import (
    ProjectPluginInstallation,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
)


@dataclass(frozen=True, slots=True)
class _ExportedTool:
    alias: str
    pin: AgentPackagePin
    tool: str
    descriptor: dict[str, Any]


class SandboxPackageCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^pkg_[0-9a-f]{12}_[A-Za-z0-9._-]{1,20}_[0-9a-f]{24}$")
    arguments: dict[str, Any]


async def _host(
    project_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ProjectPluginInstallationService:
    tenant = await db.scalar(select(Project.tenant_id).where(Project.id == project_id))
    if not tenant:
        raise HTTPException(404, _("Project unavailable"))
    try:
        authorized = await project_package_actor_can_execute(
            db,
            current_user=user,
            requested_scope=ScopeV2(
                kind=ScopeKindV2.PROJECT, tenant_id=tenant, project_id=project_id
            ),
        )
    except RuntimeV2Error:
        authorized = False
    if not authorized:
        raise HTTPException(403, _("Project package execution is unavailable"))
    return ProjectPluginInstallationService(
        db,
        ScopeBindingV2(tenant_id=tenant, project_id=project_id),
        tuple(getattr(request.app.state, "plugin_marketplace_trusted_public_keys_v2", ())),
        actor_id=user.id,
    )


async def _tools(
    service: ProjectPluginInstallationService,
    requested: str | None = None,
) -> list[_ExportedTool]:
    install = ProjectPluginInstallation
    rows = await service.db.execute(
        select(install.plugin_id, install.active, install.authorization_epoch, install.generation)
        .where(
            install.project_id == service.scope.project_id,
            install.active.is_not(None),
            install.enabled.is_(True),
        )
        .order_by(install.plugin_id)
        .execution_options(populate_existing=True)
    )
    tools: list[_ExportedTool] = []
    for plugin, version, epoch, active_generation in rows.tuples():
        prefix = "pkg_" + hashlib.sha256(plugin.encode()).hexdigest()[:12] + "_"
        if requested and not requested.startswith(prefix):
            continue
        try:
            release = await service.active_release(plugin)
        except (OptionalBusinessError, ValueError):
            continue
        if release.version != version:
            continue
        pin = AgentPackagePin(
            tenant_id=service.scope.tenant_id,
            project_id=service.scope.project_id,
            plugin_id=plugin,
            version=release.version,
            digest=release.digest,
            authorization_epoch=epoch,
        )
        for tool in release.contribution.tools:
            if (
                "tools.execute" not in tool.permissions
                or not tool.permissions <= release.approved_permissions
            ):
                continue
            generation = hashlib.sha256(
                json.dumps([service.actor_id, *astuple(pin), active_generation, tool.name]).encode()
            ).hexdigest()[:24]
            label = re.sub(r"[^A-Za-z0-9._-]", "-", tool.name[:20])
            alias = f"{prefix}{label}_{generation}"
            tools.append(
                _ExportedTool(
                    alias,
                    pin,
                    tool.name,
                    {
                        "name": alias,
                        "title": f"{plugin} / {tool.name}",
                        "description": tool.description or tool.name,
                        "inputSchema": tool.input_schema,
                    },
                )
            )
    return tools


async def list_sandbox_package_tools(
    service: Annotated[ProjectPluginInstallationService, Depends(_host)],
) -> dict[str, Any]:
    return {"tools": [tool.descriptor for tool in await _tools(service)]}


async def _disconnected(request: Request) -> None:
    while (await request.receive())["type"] != "http.disconnect":
        pass


async def call_sandbox_package_tool(
    body: SandboxPackageCall,
    request: Request,
    service: Annotated[ProjectPluginInstallationService, Depends(_host)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    tool = next(
        (item for item in await _tools(service, body.name) if item.alias == body.name), None
    )
    if tool is None:
        raise HTTPException(409, _("Project package tool changed or is unavailable"))
    project = ScopeV2(
        kind=ScopeKindV2.PROJECT, tenant_id=tool.pin.tenant_id, project_id=tool.pin.project_id
    )

    async def check_access() -> None:
        credential = await get_api_key_from_header(request.headers.get("authorization"))
        current_key = await verify_api_key_dependency(credential, service.db)
        if not current_key or current_key.user_id != user.id:
            raise HTTPException(403, _("Project package execution is unavailable"))
        await service.db.refresh(user)
        if not await project_package_actor_can_execute(
            service.db, current_user=user, requested_scope=project
        ):
            raise HTTPException(403, _("Project package execution is unavailable"))

    await check_access()
    invocation = asyncio.create_task(
        service.invoke_pinned_tool(
            tool.pin, tool.tool, body.arguments, run_pins=None, check_access=check_access
        )
    )
    disconnected = asyncio.create_task(_disconnected(request))
    try:
        done, _pending = await asyncio.wait(
            (invocation, disconnected), return_when=asyncio.FIRST_COMPLETED
        )
        if invocation not in done:
            raise HTTPException(409, _("Project package call was cancelled"))
        result = await invocation
        # A normal upgrade retains a running version. Withdrawal ends its lease.
        _release = await service.pinned_package(tool.pin)
        await check_access()
    except (OptionalBusinessError, ValueError, RuntimeV2Error) as exc:
        raise HTTPException(409, _("Project package tool is unavailable")) from exc
    finally:
        _cancelled = disconnected.cancel()
        if not invocation.done():
            _cancelled = invocation.cancel()
        _outcomes = await asyncio.gather(invocation, disconnected, return_exceptions=True)
    return {
        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
        "structuredContent": result,
    }
