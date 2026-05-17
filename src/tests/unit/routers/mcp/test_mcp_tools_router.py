"""Tests for MCP tool route hardening."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.domain.model.mcp.server import MCPServer, MCPServerConfig
from src.domain.model.mcp.transport import TransportType
from src.infrastructure.adapters.primary.web.routers.mcp import tools as tools_router
from src.infrastructure.adapters.primary.web.routers.mcp.schemas import MCPToolCallRequest


class EnabledServerRepository:
    async def get_by_id(self, _server_id: str) -> MCPServer:
        return MCPServer(
            id="server-1",
            tenant_id="tenant-1",
            name="Server 1",
            enabled=True,
            config=MCPServerConfig(
                server_name="Server 1",
                tenant_id="tenant-1",
                transport_type=TransportType.HTTP,
                url="http://mcp.example.test",
            ),
        )


class MissingServerRepository:
    async def get_by_id(self, _server_id: str) -> None:
        return None


class DisabledServerRepository:
    async def get_by_id(self, _server_id: str) -> MCPServer:
        server = await EnabledServerRepository().get_by_id(_server_id)
        server.enabled = False
        server.name = "secret-server"
        return server


class UnconfiguredServerRepository:
    async def get_by_id(self, _server_id: str) -> MCPServer:
        server = await EnabledServerRepository().get_by_id(_server_id)
        server.config = None
        server.name = "secret-server"
        return server


class FailingMCPClient:
    def __init__(self, **_kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "FailingMCPClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    async def call_tool(self, **_kwargs: object) -> object:
        raise RuntimeError("internal mcp token secret")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_mcp_tool_sanitizes_client_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository as repo_module
    import src.infrastructure.agent.mcp.client as client_module

    monkeypatch.setattr(
        repo_module,
        "SqlMCPServerRepository",
        lambda _db: EnabledServerRepository(),
    )
    monkeypatch.setattr(client_module, "MCPClient", FailingMCPClient)

    with pytest.raises(HTTPException) as exc_info:
        await tools_router.call_mcp_tool(
            request_data=MCPToolCallRequest(
                server_id="server-1",
                tool_name="tool-1",
                arguments={},
            ),
            db=SimpleNamespace(),
            tenant_id="tenant-1",
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Failed to call MCP tool"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("repo", "expected_status", "expected_detail"),
    [
        (MissingServerRepository(), 404, "MCP server not found"),
        (DisabledServerRepository(), 400, "MCP server is disabled"),
        (UnconfiguredServerRepository(), 400, "MCP server has no transport configuration"),
    ],
)
async def test_call_mcp_tool_sanitizes_server_lookup_errors(
    monkeypatch: pytest.MonkeyPatch,
    repo: object,
    expected_status: int,
    expected_detail: str,
) -> None:
    import src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository as repo_module

    monkeypatch.setattr(repo_module, "SqlMCPServerRepository", lambda _db: repo)

    with pytest.raises(HTTPException) as exc_info:
        await tools_router.call_mcp_tool(
            request_data=MCPToolCallRequest(
                server_id="server-secret",
                tool_name="tool-1",
                arguments={},
            ),
            db=SimpleNamespace(),
            tenant_id="tenant-1",
        )

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == expected_detail
    assert "secret" not in exc_info.value.detail
