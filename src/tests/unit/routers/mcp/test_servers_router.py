from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.mcp.server import MCPServer, MCPServerConfig
from src.domain.model.mcp.transport import TransportType
from src.infrastructure.adapters.primary.web.routers.mcp import servers as servers_router
from src.infrastructure.adapters.primary.web.routers.mcp.schemas import (
    MCPServerCreate,
    MCPServerUpdate,
)
from src.infrastructure.adapters.secondary.persistence.models import Project, User


class _FailingMCPRuntime:
    async def create_server(self, **_kwargs: object) -> object:
        raise RuntimeError("internal create secret")

    async def update_server(self, **_kwargs: object) -> object:
        raise RuntimeError("internal update secret")

    async def delete_server(self, *_args: object) -> None:
        raise RuntimeError("internal delete secret")

    async def sync_server(self, *_args: object) -> object:
        raise RuntimeError("internal sync secret")

    async def test_server(self, *_args: object) -> object:
        raise RuntimeError("internal test secret")


class _PermissionMCPRuntime:
    async def create_server(self, **_kwargs: object) -> object:
        raise PermissionError("tenant secret denied")

    async def update_server(self, **_kwargs: object) -> object:
        raise PermissionError("tenant secret denied")

    async def delete_server(self, *_args: object) -> None:
        raise PermissionError("tenant secret denied")

    async def sync_server(self, *_args: object) -> object:
        raise PermissionError("tenant secret denied")

    async def test_server(self, *_args: object) -> object:
        raise PermissionError("tenant secret denied")

    async def reconcile_project(self, *_args: object) -> object:
        raise PermissionError("tenant secret denied")

    async def list_server_prompts(self, *_args: object) -> object:
        raise PermissionError("tenant secret denied")

    async def set_server_log_level(self, *_args: object) -> object:
        raise PermissionError("tenant secret denied")


class _ValueErrorMCPRuntime:
    def __init__(self, message: str) -> None:
        self.message = message

    async def update_server(self, **_kwargs: object) -> object:
        raise ValueError(self.message)

    async def delete_server(self, *_args: object) -> None:
        raise ValueError(self.message)

    async def sync_server(self, *_args: object) -> object:
        raise ValueError(self.message)

    async def test_server(self, *_args: object) -> object:
        raise ValueError(self.message)

    async def list_server_prompts(self, *_args: object) -> object:
        raise ValueError(self.message)

    async def set_server_log_level(self, *_args: object) -> object:
        raise ValueError(self.message)


class _SuccessfulMCPRuntime:
    def __init__(self) -> None:
        self.create_server = AsyncMock(side_effect=self._create_server)

    async def _create_server(self, **kwargs: object) -> MCPServer:
        tenant_id = str(kwargs["tenant_id"])
        project_id = str(kwargs["project_id"])
        return MCPServer(
            id="srv-1",
            tenant_id=tenant_id,
            project_id=project_id,
            name=str(kwargs["name"]),
            description=kwargs.get("description")
            if isinstance(kwargs.get("description"), str)
            else None,
            enabled=bool(kwargs["enabled"]),
            discovered_tools=[],
            config=MCPServerConfig(
                server_name=str(kwargs["name"]),
                tenant_id=tenant_id,
                transport_type=TransportType.HTTP,
                url="http://mcp.example.test",
            ),
            created_at=datetime(2026, 6, 19, tzinfo=UTC),
        )


class _MCPServerRepository:
    def __init__(self, _db: object) -> None:
        pass

    async def get_by_id(self, _server_id: str) -> object:
        return SimpleNamespace(id="srv-1", tenant_id="tenant-1", project_id="project-1")


class _MissingMCPServerRepository:
    def __init__(self, _db: object) -> None:
        pass

    async def get_by_id(self, _server_id: str) -> object | None:
        return None


class _ForeignMCPServerRepository:
    def __init__(self, _db: object) -> None:
        pass

    async def get_by_id(self, _server_id: str) -> object:
        return SimpleNamespace(id="srv-1", tenant_id="other-tenant", project_id="project-1")


class _JsonRequest:
    async def json(self) -> dict[str, str]:
        return {"level": "debug"}


async def _allow_project_access(*_args: object, **_kwargs: object) -> None:
    return None


async def _deny_project_access(*_args: object, **_kwargs: object) -> None:
    raise HTTPException(status_code=403, detail="Access denied")


@pytest.fixture
def db() -> SimpleNamespace:
    return SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())


@pytest.fixture(autouse=True)
def failing_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        servers_router,
        "_get_runtime_service",
        AsyncMock(return_value=_FailingMCPRuntime()),
    )
    monkeypatch.setattr(servers_router, "SqlMCPServerRepository", _MCPServerRepository)
    monkeypatch.setattr(servers_router, "ensure_project_access", _allow_project_access)


@pytest.mark.unit
async def test_create_mcp_server_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    monkeypatch.setattr(
        servers_router,
        "resolve_project_tenant_id_for_access",
        AsyncMock(return_value="tenant-1"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await servers_router.create_mcp_server(
            server_data=MCPServerCreate(
                name="Local",
                server_type="stdio",
                transport_config={"command": "python"},
                project_id="project-1",
            ),
            request=SimpleNamespace(),
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Failed to create MCP server"
    assert "internal" not in exc_info.value.detail
    db.rollback.assert_awaited_once()


@pytest.mark.unit
async def test_create_mcp_server_uses_authorized_project_tenant(
    monkeypatch: pytest.MonkeyPatch,
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    runtime = _SuccessfulMCPRuntime()
    monkeypatch.setattr(
        servers_router,
        "_get_runtime_service",
        AsyncMock(return_value=runtime),
    )

    response = await servers_router.create_mcp_server(
        server_data=MCPServerCreate(
            name="Local",
            server_type="http",
            transport_config={"url": "http://mcp.example.test"},
            project_id=test_project_db.id,
        ),
        request=SimpleNamespace(),
        db=test_db,
        tenant_id="fallback-tenant",
        current_user=test_user,
    )

    assert response.tenant_id == test_project_db.tenant_id
    runtime.create_server.assert_awaited_once()
    assert runtime.create_server.await_args.kwargs["tenant_id"] == test_project_db.tenant_id


@pytest.mark.unit
async def test_update_mcp_server_sanitizes_internal_errors(db: SimpleNamespace) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await servers_router.update_mcp_server(
            server_id="srv-1",
            server_data=MCPServerUpdate(name="Updated"),
            request=SimpleNamespace(),
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Failed to update MCP server"
    assert "internal" not in exc_info.value.detail
    db.rollback.assert_awaited_once()


@pytest.mark.unit
async def test_delete_mcp_server_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    monkeypatch.setattr(servers_router, "SqlMCPServerRepository", _MCPServerRepository)

    with pytest.raises(HTTPException) as exc_info:
        await servers_router.delete_mcp_server(
            server_id="srv-1",
            request=SimpleNamespace(),
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Failed to delete MCP server"
    assert "internal" not in exc_info.value.detail
    db.rollback.assert_awaited_once()


@pytest.mark.unit
async def test_sync_mcp_server_tools_sanitizes_internal_errors(db: SimpleNamespace) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await servers_router.sync_mcp_server_tools(
            server_id="srv-1",
            request=SimpleNamespace(),
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Failed to sync MCP server tools"
    assert "internal" not in exc_info.value.detail
    db.rollback.assert_awaited_once()


@pytest.mark.unit
async def test_test_mcp_server_connection_sanitizes_internal_errors(
    db: SimpleNamespace,
) -> None:
    result = await servers_router.test_mcp_server_connection(
        server_id="srv-1",
        request=SimpleNamespace(),
        db=db,
        tenant_id="tenant-1",
        current_user=SimpleNamespace(id="user-1"),
    )

    assert result.success is False
    assert result.message == "Connection failed"
    assert result.errors == ["Connection failed"]
    assert "internal" not in result.model_dump_json()
    db.rollback.assert_awaited_once()


@pytest.mark.unit
async def test_create_mcp_server_sanitizes_permission_errors(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    monkeypatch.setattr(
        servers_router,
        "resolve_project_tenant_id_for_access",
        AsyncMock(return_value="tenant-1"),
    )
    monkeypatch.setattr(
        servers_router,
        "_get_runtime_service",
        AsyncMock(return_value=_PermissionMCPRuntime()),
    )

    with pytest.raises(HTTPException) as exc_info:
        await servers_router.create_mcp_server(
            server_data=MCPServerCreate(
                name="Local",
                server_type="stdio",
                transport_config={"command": "python"},
                project_id="project-1",
            ),
            request=SimpleNamespace(),
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied"
    assert "secret" not in exc_info.value.detail
    db.rollback.assert_awaited_once()


@pytest.mark.unit
async def test_get_mcp_server_missing_id_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    monkeypatch.setattr(servers_router, "SqlMCPServerRepository", _MissingMCPServerRepository)

    with pytest.raises(HTTPException) as exc_info:
        await servers_router.get_mcp_server(
            server_id="srv-secret",
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "MCP server not found"
    assert "srv-secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_get_mcp_server_foreign_project_access_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    monkeypatch.setattr(servers_router, "SqlMCPServerRepository", _ForeignMCPServerRepository)
    monkeypatch.setattr(servers_router, "ensure_project_access", _deny_project_access)

    with pytest.raises(HTTPException) as exc_info:
        await servers_router.get_mcp_server(
            server_id="srv-1",
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied"


@pytest.mark.unit
async def test_get_mcp_server_for_tenant_checks_access_with_server_tenant(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    calls: list[dict[str, object]] = []

    async def capture_project_access(*args: object, **kwargs: object) -> None:
        calls.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(servers_router, "SqlMCPServerRepository", _MCPServerRepository)
    monkeypatch.setattr(servers_router, "ensure_project_access", capture_project_access)

    server = await servers_router._get_mcp_server_for_tenant(
        db=db,
        server_id="srv-1",
        tenant_id="fallback-tenant",
        user_id="user-1",
    )

    assert server.tenant_id == "tenant-1"
    assert calls[0]["args"][2] == "tenant-1"


@pytest.mark.unit
async def test_update_mcp_server_sanitizes_value_errors(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    monkeypatch.setattr(
        servers_router,
        "_get_runtime_service",
        AsyncMock(return_value=_ValueErrorMCPRuntime("server srv-secret not found")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await servers_router.update_mcp_server(
            server_id="srv-secret",
            server_data=MCPServerUpdate(name="Updated"),
            request=SimpleNamespace(),
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "MCP server not found"
    assert "srv-secret" not in exc_info.value.detail
    db.rollback.assert_awaited_once()


@pytest.mark.unit
async def test_sync_mcp_server_tools_sanitizes_non_not_found_value_errors(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    monkeypatch.setattr(
        servers_router,
        "_get_runtime_service",
        AsyncMock(return_value=_ValueErrorMCPRuntime("sandbox secret failed")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await servers_router.sync_mcp_server_tools(
            server_id="srv-1",
            request=SimpleNamespace(),
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "MCP server operation failed"
    assert "secret" not in exc_info.value.detail
    db.rollback.assert_awaited_once()


@pytest.mark.unit
async def test_test_mcp_server_connection_sanitizes_value_errors(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    monkeypatch.setattr(
        servers_router,
        "_get_runtime_service",
        AsyncMock(return_value=_ValueErrorMCPRuntime("server srv-secret not found")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await servers_router.test_mcp_server_connection(
            server_id="srv-secret",
            request=SimpleNamespace(),
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "MCP server not found"
    assert "srv-secret" not in exc_info.value.detail
    db.rollback.assert_awaited_once()


@pytest.mark.unit
async def test_reconcile_mcp_project_sanitizes_permission_errors(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    monkeypatch.setattr(
        servers_router,
        "resolve_project_tenant_id_for_access",
        AsyncMock(return_value="tenant-1"),
    )
    monkeypatch.setattr(
        servers_router,
        "_get_runtime_service",
        AsyncMock(return_value=_PermissionMCPRuntime()),
    )

    with pytest.raises(HTTPException) as exc_info:
        await servers_router.reconcile_mcp_project(
            project_id="project-secret",
            request=SimpleNamespace(),
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied"
    assert "secret" not in exc_info.value.detail
    db.rollback.assert_awaited_once()


@pytest.mark.unit
async def test_get_mcp_server_health_missing_id_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    monkeypatch.setattr(
        servers_router,
        "SqlMCPServerRepository",
        _MissingMCPServerRepository,
    )

    with pytest.raises(HTTPException) as exc_info:
        await servers_router.get_mcp_server_health(
            server_id="srv-secret",
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "MCP server not found"
    assert "srv-secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_list_mcp_server_prompts_sanitizes_value_errors(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    monkeypatch.setattr(
        servers_router,
        "_get_runtime_service",
        AsyncMock(return_value=_ValueErrorMCPRuntime("server srv-secret not found")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await servers_router.list_mcp_server_prompts(
            server_id="srv-secret",
            request=SimpleNamespace(),
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "MCP server not found"
    assert "srv-secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_set_mcp_server_log_level_sanitizes_value_errors(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    monkeypatch.setattr(
        servers_router,
        "_get_runtime_service",
        AsyncMock(return_value=_ValueErrorMCPRuntime("server srv-secret not found")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await servers_router.set_mcp_server_log_level(
            server_id="srv-secret",
            request=_JsonRequest(),
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "MCP server not found"
    assert "srv-secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_get_mcp_server_for_tenant_sanitizes_missing_id(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    monkeypatch.setattr(servers_router, "SqlMCPServerRepository", _MissingMCPServerRepository)

    with pytest.raises(HTTPException) as exc_info:
        await servers_router._get_mcp_server_for_tenant(
            db=db,
            server_id="srv-secret",
            tenant_id="tenant-1",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "MCP server not found"
    assert "srv-secret" not in exc_info.value.detail
