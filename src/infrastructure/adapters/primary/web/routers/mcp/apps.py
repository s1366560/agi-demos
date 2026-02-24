"""MCP App API endpoints.

CRUD operations and resource serving for MCP Apps -
interactive HTML interfaces declared by MCP tools.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.mcp_app_service import MCPAppService
from src.application.services.mcp_runtime_service import MCPRuntimeService
from src.infrastructure.adapters.primary.web.dependencies import get_current_user_tenant
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.sql_mcp_app_repository import (
    SqlMCPAppRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
    SqlMCPServerRepository,
)

from .utils import ensure_project_access, get_container_with_db

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from src.domain.model.mcp.app import MCPApp

router = APIRouter(prefix="/apps", tags=["MCP Apps"])


# === Schemas ===


class MCPAppResponse(BaseModel):
    """Response schema for MCP App."""

    id: str
    project_id: str
    tenant_id: str
    server_id: str | None = None
    server_name: str
    tool_name: str
    ui_metadata: dict
    source: str
    status: str
    lifecycle_metadata: dict = Field(default_factory=dict)
    error_message: str | None = None
    has_resource: bool = False
    resource_size_bytes: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MCPAppResourceResponse(BaseModel):
    """Response schema for MCP App HTML resource."""

    app_id: str
    resource_uri: str
    html_content: str
    mime_type: str = "text/html;profile=mcp-app"
    size_bytes: int = 0
    ui_metadata: dict = Field(default_factory=dict)


class MCPAppToolCallRequest(BaseModel):
    """Request schema for proxying a tool call from an MCP App iframe."""

    tool_name: str = Field(..., description="Name of the MCP tool to call")
    arguments: dict = Field(default_factory=dict, description="Tool call arguments")


class MCPAppToolCallResponse(BaseModel):
    """Response schema for proxied tool call.

    Error responses follow JSON-RPC -32000 convention per SEP-1865.
    """

    content: list = Field(default_factory=list)
    is_error: bool = False
    error_message: str | None = None
    error_code: int | None = Field(None, description="JSON-RPC error code (-32000 for proxy)")


# === Dependency ===


def _get_mcp_app_service(request: Request, db: AsyncSession) -> MCPAppService:
    """Get MCPAppService from DI container."""
    container = get_container_with_db(request, db)
    return container.mcp_app_service()


async def _get_mcp_runtime_service(request: Request, db: AsyncSession) -> MCPRuntimeService:
    """Get MCP runtime service from request-scoped dependencies."""
    container = request.app.state.container.with_db(db)
    return MCPRuntimeService(
        db=db,
        server_repo=SqlMCPServerRepository(db),
        app_repo=SqlMCPAppRepository(db),
        app_service=container.mcp_app_service(),
        sandbox_manager=container.sandbox_mcp_server_manager(),
        redis_client=container.redis(),
    )


def _validate_tenant(app: MCPApp, tenant_id: str) -> None:
    """Ensure app belongs to the requesting tenant."""
    if app.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="MCP App not found")


# === Endpoints ===


@router.get("", response_model=list[MCPAppResponse])
async def list_mcp_apps(
    request: Request,
    project_id: str | None = Query(None, description="Filter by project ID"),
    include_disabled: bool = Query(False, description="Include disabled apps"),
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> list[Any]:
    """List MCP Apps. If project_id is provided, scopes to that project; otherwise lists all tenant apps."""
    service = _get_mcp_app_service(request, db)
    if project_id:
        await ensure_project_access(db, project_id, tenant_id)
        apps = await service.list_apps(project_id, include_disabled=include_disabled)
    else:
        apps = await service.list_apps_by_tenant(tenant_id, include_disabled=include_disabled)

    return [
        MCPAppResponse(
            id=app.id,
            project_id=app.project_id,
            tenant_id=app.tenant_id,
            server_id=app.server_id,
            server_name=app.server_name,
            tool_name=app.tool_name,
            ui_metadata=app.ui_metadata.to_dict(),
            source=app.source.value,
            status=app.status.value,
            lifecycle_metadata=app.lifecycle_metadata,
            error_message=app.error_message,
            has_resource=app.resource is not None,
            resource_size_bytes=app.resource.size_bytes if app.resource else None,
            created_at=app.created_at.isoformat() if app.created_at else None,
            updated_at=app.updated_at.isoformat() if app.updated_at else None,
        )
        for app in apps
    ]


# === Direct Proxy Endpoints (must be before /{app_id} routes) ===
# These endpoints don't require a DB app record.  They are used for
# auto-discovered MCP Apps with synthetic app_ids (e.g. ``_synthetic_hello``).


class MCPDirectToolCallRequest(BaseModel):
    """Request for direct tool-call proxy without requiring a DB app record."""

    project_id: str = Field(..., description="Project owning the sandbox")
    server_name: str = Field(..., description="MCP server name in the sandbox")
    tool_name: str = Field(..., description="Name of the MCP tool to call")
    arguments: dict = Field(default_factory=dict, description="Tool call arguments")


@router.post("/proxy/tool-call", response_model=MCPAppToolCallResponse)
async def proxy_tool_call_direct(
    request: Request,
    body: MCPDirectToolCallRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> MCPAppToolCallResponse:
    """Proxy a tool call directly to a sandbox MCP server (no DB lookup).

    Used when the MCP App was auto-discovered during an agent session
    and has no persistent DB record (synthetic app_id like ``_synthetic_<tool>``).
    """
    try:
        await ensure_project_access(db, body.project_id, tenant_id)
        container = get_container_with_db(request, db)
        mcp_manager = container.sandbox_mcp_server_manager()
        result = await mcp_manager.call_tool(
            project_id=body.project_id,
            server_name=body.server_name,
            tool_name=body.tool_name,
            arguments=body.arguments,
        )
        return MCPAppToolCallResponse(
            content=result.content,
            is_error=result.is_error,
            error_message=result.error_message,
        )
    except Exception as e:
        logger.error(
            "Direct tool call proxy failed: project=%s, server=%s, tool=%s, err=%s",
            body.project_id,
            body.server_name,
            body.tool_name,
            e,
        )
        return MCPAppToolCallResponse(
            content=[{"type": "text", "text": f"Error: {e!s}"}],
            is_error=True,
            error_message=str(e),
            error_code=-32000,
        )


@router.get("/{app_id}", response_model=MCPAppResponse)
async def get_mcp_app(
    request: Request,
    app_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> MCPAppResponse:
    """Get MCP App details."""
    service = _get_mcp_app_service(request, db)
    app = await service.get_app(app_id)
    if not app:
        raise HTTPException(status_code=404, detail="MCP App not found")
    _validate_tenant(app, tenant_id)

    return MCPAppResponse(
        id=app.id,
        project_id=app.project_id,
        tenant_id=app.tenant_id,
        server_id=app.server_id,
        server_name=app.server_name,
        tool_name=app.tool_name,
        ui_metadata=app.ui_metadata.to_dict(),
        source=app.source.value,
        status=app.status.value,
        lifecycle_metadata=app.lifecycle_metadata,
        error_message=app.error_message,
        has_resource=app.resource is not None,
        resource_size_bytes=app.resource.size_bytes if app.resource else None,
        created_at=app.created_at.isoformat() if app.created_at else None,
        updated_at=app.updated_at.isoformat() if app.updated_at else None,
    )


@router.get("/{app_id}/resource", response_model=MCPAppResourceResponse)
async def get_mcp_app_resource(
    request: Request,
    app_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> MCPAppResourceResponse:
    """Get the resolved HTML resource for an MCP App.

    Returns the cached HTML content if available, or returns 404
    if the resource hasn't been resolved yet.
    """
    service = _get_mcp_app_service(request, db)
    app = await service.get_app(app_id)
    if not app:
        raise HTTPException(status_code=404, detail="MCP App not found")
    _validate_tenant(app, tenant_id)

    if not app.resource:
        raise HTTPException(
            status_code=404,
            detail="Resource not yet resolved. Call POST /refresh first.",
        )

    return MCPAppResourceResponse(
        app_id=app.id,
        resource_uri=app.resource.uri,
        html_content=app.resource.html_content,
        mime_type=app.resource.mime_type,
        size_bytes=app.resource.size_bytes,
        ui_metadata=app.ui_metadata.to_dict(),
    )


@router.post("/{app_id}/tool-call", response_model=MCPAppToolCallResponse)
async def proxy_tool_call(
    request: Request,
    app_id: str,
    body: MCPAppToolCallRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> MCPAppToolCallResponse:
    """Proxy a tool call from an MCP App iframe to its MCP server.

    This endpoint is called by the AppBridge when the app needs to
    invoke tools on its server (bidirectional communication).

    TODO(SEP-1865): Enforce tool visibility - reject calls to tools
    where _meta.ui.visibility does not include "app". Requires caching
    the server's tools/list result to avoid per-call latency.
    """
    service = _get_mcp_app_service(request, db)
    app = await service.get_app(app_id)
    if not app:
        raise HTTPException(status_code=404, detail="MCP App not found")
    _validate_tenant(app, tenant_id)

    try:
        container = get_container_with_db(request, db)
        mcp_manager = container.sandbox_mcp_server_manager()
        result = await mcp_manager.call_tool(
            project_id=app.project_id,
            server_name=app.server_name,
            tool_name=body.tool_name,
            arguments=body.arguments,
        )
        return MCPAppToolCallResponse(
            content=result.content,
            is_error=result.is_error,
            error_message=result.error_message,
        )
    except Exception as e:
        logger.error("Tool call proxy failed: app=%s, tool=%s, err=%s", app_id, body.tool_name, e)
        # SEP-1865: Use JSON-RPC -32000 error code for tool call proxy failures
        return MCPAppToolCallResponse(
            content=[
                {
                    "type": "text",
                    "text": f"Error: {e!s}",
                }
            ],
            is_error=True,
            error_message=str(e),
            error_code=-32000,
        )


@router.delete("/{app_id}")
async def delete_mcp_app(
    request: Request,
    app_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> dict[str, Any]:
    """Delete an MCP App."""
    try:
        runtime = await _get_mcp_runtime_service(request, db)
        await runtime.delete_app(app_id, tenant_id)
        await db.commit()
        return {"message": "MCP App deleted", "id": app_id}
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        await db.rollback()
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        await db.rollback()
        logger.exception("Delete app failed: app=%s", app_id)
        raise HTTPException(status_code=500, detail="Failed to delete app") from e


@router.post("/{app_id}/refresh", response_model=MCPAppResponse)
async def refresh_mcp_app_resource(
    request: Request,
    app_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> MCPAppResponse:
    """Re-fetch the HTML resource for an MCP App.

    Useful when the app has been rebuilt (e.g., by the agent).
    Note: Requires full DI wiring for sandbox access.
    """
    try:
        runtime = await _get_mcp_runtime_service(request, db)
        app = await runtime.refresh_app_resource(app_id, tenant_id)
        await db.commit()
        return MCPAppResponse(
            id=app.id,
            project_id=app.project_id,
            tenant_id=app.tenant_id,
            server_id=app.server_id,
            server_name=app.server_name,
            tool_name=app.tool_name,
            ui_metadata=app.ui_metadata.to_dict(),
            source=app.source.value,
            status=app.status.value,
            lifecycle_metadata=app.lifecycle_metadata,
            error_message=app.error_message,
            has_resource=app.resource is not None,
            resource_size_bytes=app.resource.size_bytes if app.resource else None,
            created_at=app.created_at.isoformat() if app.created_at else None,
            updated_at=app.updated_at.isoformat() if app.updated_at else None,
        )
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        await db.rollback()
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        await db.rollback()
        logger.exception("Resource refresh failed: app=%s", app_id)
        raise HTTPException(status_code=500, detail="Failed to refresh resource") from e


# === Standard MCP Resource/Tool Proxy ===
# These endpoints implement the host-side proxy needed by the standard
# @mcp-ui/client AppRenderer component.  The frontend cannot call
# MCP servers directly (they run in Docker sandboxes behind WebSocket).


class MCPResourceReadRequest(BaseModel):
    """Request schema for standard MCP resources/read proxy."""

    uri: str = Field(..., description="MCP resource URI (e.g. ui://server/index.html)")
    project_id: str = Field(..., description="Project ID for server resolution")
    server_name: str | None = Field(None, description="Server name hint (optional)")


class MCPResourceReadResponse(BaseModel):
    """Response compatible with AppRenderer's onReadResource callback."""

    contents: list = Field(default_factory=list)


def _extract_server_name_from_uri(uri: str) -> str | None:
    """Extract server name from MCP app resource URI.

    Supported URI schemes:
    - ui://server-name/path -> server-name
    - app://server-name/path -> server-name
    - mcp-app://server-name/path -> server-name

    Examples:
    - ui://pick-color/mcp-app.html -> pick-color
    - app://color-picker -> color-picker
    - mcp-app://my-server/index.html -> my-server
    """
    # List of supported URI scheme prefixes
    prefixes = ["ui://", "app://", "mcp-app://"]

    for prefix in prefixes:
        if uri.startswith(prefix):
            # Remove prefix
            rest = uri[len(prefix) :]
            # Extract first path segment as server name
            if "/" in rest:
                return rest.split("/")[0]
            return rest if rest else None

    return None


async def _retry_resource_after_reinstall(
    body: MCPResourceReadRequest,
    server_name: str,
    tenant_id: str,
    db: AsyncSession,
    mcp_manager: Any,
    read_fn: Any,
) -> Any:
    """Reinstall an MCP server and retry the resource read."""
    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SqlMCPServerRepository,
    )

    try:
        mcp_repo = SqlMCPServerRepository(db)
        mcp_server = await mcp_repo.get_by_name(body.project_id, server_name)
        if mcp_server and mcp_server.transport_config:
            logger.info(
                "resources/read failed -- reinstalling server '%s' and retrying",
                server_name,
            )
            await mcp_manager.install_and_start(
                project_id=body.project_id,
                tenant_id=tenant_id,
                server_name=server_name,
                server_type=mcp_server.server_type,
                transport_config=mcp_server.transport_config,
            )
            return await read_fn()
        raise HTTPException(status_code=404, detail=f"Resource not found: {body.uri}")
    except HTTPException:
        raise
    except TimeoutError:
        logger.warning("resources/read retry timed out after reinstall: uri=%s", body.uri)
        raise HTTPException(status_code=404, detail=f"Resource not found: {body.uri}") from None
    except Exception as reinstall_err:
        logger.warning("resources/read reinstall failed for '%s': %s", server_name, reinstall_err)
        raise HTTPException(
            status_code=404, detail=f"Resource not found: {body.uri}"
        ) from reinstall_err


def _extract_html_from_result(result: Any, uri: str) -> str:
    """Extract HTML content from an MCP resource read result."""
    if result.is_error:
        error_text = ""
        for item in result.content:
            if isinstance(item, dict) and item.get("type") == "text":
                error_text = item.get("text", "")
                break
        logger.warning("resources/read proxy error: %s", error_text)
        raise HTTPException(status_code=404, detail=f"Resource not found: {uri}")

    html_content = None
    for item in result.content:
        if isinstance(item, dict):
            if item.get("uri") == uri:
                html_content = item.get("text", "")
                break
            if item.get("type") == "text" and not html_content:
                html_content = item.get("text", "")

    if not html_content:
        raise HTTPException(status_code=404, detail=f"No content found for resource: {uri}")
    return html_content


@router.post("/resources/read", response_model=MCPResourceReadResponse)
async def proxy_resource_read(
    request: Request,
    body: MCPResourceReadRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> MCPResourceReadResponse:
    """Proxy a resources/read request to the appropriate MCP server.

    Resolution order:
    1. If URI matches a registered app record -> serve from DB
    2. Otherwise -> proxy to sandbox MCP server via mcp_server_call_tool

    The resources/read is proxied through the sandbox management server's
    mcp_server_call_tool to reach the correct child MCP server.
    """
    await ensure_project_access(db, body.project_id, tenant_id)
    service = _get_mcp_app_service(request, db)

    # Path 1: Check if any registered app owns this URI
    apps = await service.list_apps(body.project_id, include_disabled=False)
    for app in apps:
        if app.resource and app.resource.uri == body.uri and app.resource.html_content:
            return MCPResourceReadResponse(
                contents=[
                    {
                        "uri": body.uri,
                        "mimeType": "text/html;profile=mcp-app",
                        "text": app.resource.html_content,
                    }
                ]
            )

    # Path 2: Proxy to sandbox MCP server via mcp_server_call_tool
    # This routes to the correct child MCP server based on server_name
    try:
        # Resolve server_name from URI if not provided
        server_name = body.server_name or _extract_server_name_from_uri(body.uri)
        if not server_name:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot determine server name from URI: {body.uri}. Provide server_name parameter.",
            )

        container = get_container_with_db(request, db)
        mcp_manager = container.sandbox_mcp_server_manager()

        async def _read_resource() -> Any:
            """Call __resources_read__ with a 15s timeout."""
            return await asyncio.wait_for(
                mcp_manager.call_tool(
                    project_id=body.project_id,
                    server_name=server_name,
                    tool_name="__resources_read__",
                    arguments={"uri": body.uri},
                ),
                timeout=15.0,
            )

        # Use call_tool with __resources_read__ to proxy to child MCP server.
        # Use a short timeout so callers don't wait the full 60s when the
        # resource doesn't exist (e.g. ephemeral sandbox was restarted).
        # On failure (timeout or server-not-found), attempt a one-shot reinstall
        # and retry — handles the case where the management server was restarted
        # and lost its in-memory server registry.
        need_retry = False
        try:
            result = await _read_resource()
            if result.is_error:
                need_retry = True
        except TimeoutError:
            logger.warning("resources/read timed out after 15s: uri=%s", body.uri)
            need_retry = True

        if need_retry:
            result = await _retry_resource_after_reinstall(
                body, server_name, tenant_id, db, mcp_manager, _read_resource
            )

        html_content = _extract_html_from_result(result, body.uri)
        return MCPResourceReadResponse(
            contents=[
                {
                    "uri": body.uri,
                    "mimeType": "text/html;profile=mcp-app",
                    "text": html_content,
                }
            ]
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("resources/read proxy failed: uri=%s, err=%s", body.uri, e)
        raise HTTPException(
            status_code=502, detail=f"Failed to read resource from MCP server: {e!s}"
        ) from e


class MCPResourceListRequest(BaseModel):
    """Request schema for standard MCP resources/list proxy."""

    project_id: str = Field(..., description="Project ID for server resolution")
    server_name: str | None = Field(None, description="Server name hint (optional)")


class MCPResourceListResponse(BaseModel):
    """Response compatible with AppRenderer's onListResources callback."""

    resources: list = Field(default_factory=list)


@router.post("/resources/list", response_model=MCPResourceListResponse)
async def proxy_resource_list(
    request: Request,
    body: MCPResourceListRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_current_user_tenant),
) -> MCPResourceListResponse:
    """Proxy a resources/list request to sandbox MCP servers.

    Returns the aggregated list of resources from all running MCP
    servers in the project's sandbox.
    """
    try:
        await ensure_project_access(db, body.project_id, tenant_id)
        container = get_container_with_db(request, db)
        mcp_manager = container.sandbox_mcp_server_manager()
        resources = await mcp_manager.list_resources(
            project_id=body.project_id,
            tenant_id=tenant_id,
        )
        return MCPResourceListResponse(resources=resources)
    except Exception as e:
        logger.error("resources/list proxy failed: err=%s", e)
        raise HTTPException(
            status_code=502, detail=f"Failed to list resources from MCP server: {e!s}"
        ) from e
