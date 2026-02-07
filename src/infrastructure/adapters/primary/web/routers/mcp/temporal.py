"""Temporal MCP management endpoints.

Endpoints for managing MCP servers via Temporal Workflows for horizontal scaling.
"""

import logging
import time
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.infrastructure.adapters.primary.web.dependencies import get_current_user_tenant

from .schemas import (
    TemporalMCPConnectRequest,
    TemporalMCPStatusResponse,
    TemporalMCPToolCallRequest,
    TemporalMCPToolCallResponse,
    TemporalMCPToolInfo,
)
from .utils import get_mcp_adapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/temporal")


@router.post("/servers", response_model=TemporalMCPStatusResponse)
async def start_temporal_mcp_server(
    connect_request: TemporalMCPConnectRequest,
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Start an MCP server via Temporal Workflow.

    Creates a long-running workflow that manages the MCP server lifecycle.
    The server runs in a separate MCP Worker process for horizontal scaling.

    Benefits over runtime/connect:
    - Survives API service restarts
    - Runs in separate worker process
    - Supports horizontal scaling
    - Tenant isolation via workflow ID
    """
    try:
        adapter = await get_mcp_adapter(request)

        server_status = await adapter.start_mcp_server(
            tenant_id=tenant_id,
            server_name=connect_request.server_name,
            transport_type=connect_request.transport_type,
            command=connect_request.command,
            environment=connect_request.environment,
            url=connect_request.url,
            headers=connect_request.headers,
            timeout=connect_request.timeout,
        )

        return TemporalMCPStatusResponse(
            server_name=server_status.server_name,
            tenant_id=server_status.tenant_id,
            connected=server_status.connected,
            tool_count=server_status.tool_count,
            error=server_status.error,
            workflow_id=server_status.workflow_id,
        )

    except Exception as e:
        logger.error(f"Failed to start Temporal MCP server: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start MCP server: {str(e)}",
        )


@router.delete("/servers/{server_name}", status_code=status.HTTP_204_NO_CONTENT)
async def stop_temporal_mcp_server(
    server_name: str,
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Stop a Temporal MCP server workflow.
    """
    try:
        adapter = await get_mcp_adapter(request)
        await adapter.stop_mcp_server(tenant_id, server_name)

    except Exception as e:
        logger.error(f"Failed to stop Temporal MCP server: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop MCP server: {str(e)}",
        )


@router.get("/servers", response_model=List[TemporalMCPStatusResponse])
async def list_temporal_mcp_servers(
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    List all Temporal MCP servers for the current tenant.
    """
    try:
        adapter = await get_mcp_adapter(request)
        servers = await adapter.list_servers(tenant_id)

        return [
            TemporalMCPStatusResponse(
                server_name=s.server_name,
                tenant_id=s.tenant_id,
                connected=s.connected,
                tool_count=s.tool_count,
                error=s.error,
                workflow_id=s.workflow_id,
            )
            for s in servers
        ]

    except Exception as e:
        logger.error(f"Failed to list Temporal MCP servers: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list MCP servers: {str(e)}",
        )


@router.get("/servers/{server_name}/status", response_model=TemporalMCPStatusResponse)
async def get_temporal_mcp_server_status(
    server_name: str,
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Get status of a specific Temporal MCP server.
    """
    try:
        adapter = await get_mcp_adapter(request)
        server_status = await adapter.get_server_status(tenant_id, server_name)

        return TemporalMCPStatusResponse(
            server_name=server_status.server_name,
            tenant_id=server_status.tenant_id,
            connected=server_status.connected,
            tool_count=server_status.tool_count,
            error=server_status.error,
            workflow_id=server_status.workflow_id,
        )

    except Exception as e:
        logger.error(f"Failed to get Temporal MCP server status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get MCP server status: {str(e)}",
        )


@router.get("/servers/{server_name}/tools", response_model=List[TemporalMCPToolInfo])
async def list_temporal_mcp_tools(
    server_name: str,
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    List tools available from a Temporal MCP server.
    """
    try:
        adapter = await get_mcp_adapter(request)
        tools = await adapter.list_tools(tenant_id, server_name)

        return [
            TemporalMCPToolInfo(
                name=t.name,
                server_name=t.server_name,
                description=t.description,
                input_schema=t.input_schema,
            )
            for t in tools
        ]

    except Exception as e:
        logger.error(f"Failed to list Temporal MCP tools: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list MCP tools: {str(e)}",
        )


@router.get("/tools", response_model=List[TemporalMCPToolInfo])
async def list_all_temporal_mcp_tools(
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    List all tools from all Temporal MCP servers for the current tenant.
    """
    try:
        adapter = await get_mcp_adapter(request)
        tools = await adapter.list_all_tools(tenant_id)

        return [
            TemporalMCPToolInfo(
                name=t.name,
                server_name=t.server_name,
                description=t.description,
                input_schema=t.input_schema,
            )
            for t in tools
        ]

    except Exception as e:
        logger.error(f"Failed to list all Temporal MCP tools: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list MCP tools: {str(e)}",
        )


@router.post(
    "/servers/{server_name}/tools/call",
    response_model=TemporalMCPToolCallResponse,
)
async def call_temporal_mcp_tool(
    server_name: str,
    call_request: TemporalMCPToolCallRequest,
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
):
    """
    Call a tool on a Temporal MCP server.

    The tool call is executed via Temporal Workflow update,
    ensuring reliable execution with automatic retries.
    """
    try:
        adapter = await get_mcp_adapter(request)

        start_time = time.time()

        result = await adapter.call_mcp_tool(
            tenant_id=tenant_id,
            server_name=server_name,
            tool_name=call_request.tool_name,
            arguments=call_request.arguments,
            timeout=call_request.timeout,
        )

        execution_time_ms = (time.time() - start_time) * 1000

        return TemporalMCPToolCallResponse(
            content=result.content,
            is_error=result.is_error,
            error_message=result.error_message,
            execution_time_ms=execution_time_ms,
        )

    except Exception as e:
        logger.error(f"Failed to call Temporal MCP tool: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to call MCP tool: {str(e)}",
        )
