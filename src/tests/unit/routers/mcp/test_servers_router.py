from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers.mcp import servers as servers_router
from src.infrastructure.adapters.primary.web.routers.mcp.schemas import (
    MCPServerCreate,
    MCPServerUpdate,
)


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


class _MCPServerRepository:
    def __init__(self, _db: object) -> None:
        pass

    async def get_by_id(self, _server_id: str) -> object:
        return SimpleNamespace(id="srv-1", tenant_id="tenant-1")


class _MissingMCPServerRepository:
    def __init__(self, _db: object) -> None:
        pass

    async def get_by_id(self, _server_id: str) -> object | None:
        return None


class _ForeignMCPServerRepository:
    def __init__(self, _db: object) -> None:
        pass

    async def get_by_id(self, _server_id: str) -> object:
        return SimpleNamespace(id="srv-1", tenant_id="other-tenant")


class _JsonRequest:
    async def json(self) -> dict[str, str]:
        return {"level": "debug"}


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


@pytest.mark.unit
async def test_create_mcp_server_sanitizes_internal_errors(db: SimpleNamespace) -> None:
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
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Failed to create MCP server"
    assert "internal" not in exc_info.value.detail
    db.rollback.assert_awaited_once()


@pytest.mark.unit
async def test_update_mcp_server_sanitizes_internal_errors(db: SimpleNamespace) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await servers_router.update_mcp_server(
            server_id="srv-1",
            server_data=MCPServerUpdate(name="Updated"),
            request=SimpleNamespace(),
            db=db,
            tenant_id="tenant-1",
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
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "MCP server not found"
    assert "srv-secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_get_mcp_server_foreign_tenant_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    db: SimpleNamespace,
) -> None:
    monkeypatch.setattr(servers_router, "SqlMCPServerRepository", _ForeignMCPServerRepository)

    with pytest.raises(HTTPException) as exc_info:
        await servers_router.get_mcp_server(
            server_id="srv-1",
            db=db,
            tenant_id="tenant-1",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied"


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
        "_get_runtime_service",
        AsyncMock(return_value=_PermissionMCPRuntime()),
    )

    with pytest.raises(HTTPException) as exc_info:
        await servers_router.reconcile_mcp_project(
            project_id="project-secret",
            request=SimpleNamespace(),
            db=db,
            tenant_id="tenant-1",
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
        "src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository.SqlMCPServerRepository",
        _MissingMCPServerRepository,
    )

    with pytest.raises(HTTPException) as exc_info:
        await servers_router.get_mcp_server_health(
            server_id="srv-secret",
            db=db,
            tenant_id="tenant-1",
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
