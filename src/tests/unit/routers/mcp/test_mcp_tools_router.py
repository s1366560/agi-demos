"""Tests for MCP tool route hardening."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.mcp.server import MCPServer, MCPServerConfig
from src.domain.model.mcp.transport import TransportType
from src.infrastructure.adapters.primary.web.routers.mcp import tools as tools_router
from src.infrastructure.adapters.primary.web.routers.mcp.schemas import MCPToolCallRequest
from src.infrastructure.adapters.secondary.persistence.models import Project, User


class EnabledServerRepository:
    async def get_by_id(self, _server_id: str) -> MCPServer:
        return MCPServer(
            id="server-1",
            tenant_id="tenant-1",
            project_id="project-1",
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


async def _allow_project_access(*_args: object, **_kwargs: object) -> None:
    return None


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
    monkeypatch.setattr(tools_router, "ensure_project_access", _allow_project_access)

    with pytest.raises(HTTPException) as exc_info:
        await tools_router.call_mcp_tool(
            request_data=MCPToolCallRequest(
                server_id="server-1",
                tool_name="tool-1",
                arguments={},
            ),
            db=SimpleNamespace(),
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
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
    monkeypatch.setattr(tools_router, "ensure_project_access", _allow_project_access)

    with pytest.raises(HTTPException) as exc_info:
        await tools_router.call_mcp_tool(
            request_data=MCPToolCallRequest(
                server_id="server-secret",
                tool_name="tool-1",
                arguments={},
            ),
            db=SimpleNamespace(),
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == expected_detail
    assert "secret" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_mcp_tool_rejects_same_tenant_project_non_member(
    monkeypatch: pytest.MonkeyPatch,
    test_db: AsyncSession,
    test_project_db: Project,
    another_user: User,
) -> None:
    import src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository as repo_module

    class ProjectServerRepository:
        async def get_by_id(self, _server_id: str) -> MCPServer:
            return MCPServer(
                id="server-1",
                tenant_id=test_project_db.tenant_id,
                project_id=test_project_db.id,
                name="Server 1",
                enabled=True,
                config=MCPServerConfig(
                    server_name="Server 1",
                    tenant_id=test_project_db.tenant_id,
                    transport_type=TransportType.HTTP,
                    url="http://mcp.example.test",
                ),
            )

    monkeypatch.setattr(
        repo_module, "SqlMCPServerRepository", lambda _db: ProjectServerRepository()
    )

    with pytest.raises(HTTPException) as exc_info:
        await tools_router.call_mcp_tool(
            request_data=MCPToolCallRequest(
                server_id="server-1",
                tool_name="tool-1",
                arguments={},
            ),
            db=test_db,
            tenant_id=test_project_db.tenant_id,
            current_user=another_user,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_all_mcp_tools_uses_authorized_project_tenant(
    monkeypatch: pytest.MonkeyPatch,
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    import src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository as repo_module

    calls: list[dict[str, Any]] = []

    class ProjectServerRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def get_enabled_servers(
            self, tenant_id: str, project_id: str | None = None
        ) -> list[SimpleNamespace]:
            calls.append({"tenant_id": tenant_id, "project_id": project_id})
            return [
                SimpleNamespace(
                    id="server-1",
                    name="Project Server",
                    project_id=project_id,
                    discovered_tools=[
                        {
                            "name": "project_tool",
                            "description": "Project-scoped tool",
                            "inputSchema": {"type": "object"},
                        }
                    ],
                )
            ]

    monkeypatch.setattr(repo_module, "SqlMCPServerRepository", ProjectServerRepository)

    response = await tools_router.list_all_mcp_tools(
        project_id=test_project_db.id,
        page=1,
        per_page=50,
        db=test_db,
        tenant_id="fallback-tenant",
        current_user=test_user,
    )

    assert response.total == 1
    assert response.items[0].name == "project_tool"
    assert calls == [{"tenant_id": test_project_db.tenant_id, "project_id": test_project_db.id}]
