"""Tests for MCP app route hardening."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.mcp import apps as apps_router
from src.infrastructure.adapters.secondary.persistence.models import Project, User


class EmptyAppService:
    async def list_apps(self, _project_id: str, *, include_disabled: bool = False) -> list[Any]:
        return []

    async def get_app(self, _app_id: str) -> None:
        return None


class ExistingAppService:
    async def get_app(self, _app_id: str) -> SimpleNamespace:
        return SimpleNamespace(id="app-1", project_id="project-1", tenant_id="tenant-1")


class FailingMCPManager:
    async def call_tool(self, **_kwargs: Any) -> Any:
        raise RuntimeError("internal mcp resource secret")

    async def list_resources(self, **_kwargs: Any) -> Any:
        raise RuntimeError("internal mcp resource list secret")


class FakeContainer:
    def mcp_app_service(self) -> EmptyAppService:
        return EmptyAppService()

    def sandbox_mcp_server_manager(self) -> FailingMCPManager:
        return FailingMCPManager()


class FailingRuntime:
    async def delete_app(self, _app_id: str, _tenant_id: str) -> None:
        raise ValueError("MCP App not found: app-secret")

    async def refresh_app_resource(self, _app_id: str, _tenant_id: str) -> None:
        raise PermissionError("Access denied for app-secret")


class MissingMCPServerRepository:
    def __init__(self, _db: object) -> None:
        pass

    async def get_by_name(self, _project_id: str, _server_name: str) -> None:
        return None


async def _allow_project_access(*_args: Any, **_kwargs: Any) -> None:
    return None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_proxy_resource_read_sanitizes_mcp_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(apps_router, "ensure_project_access", _allow_project_access)
    monkeypatch.setattr(
        apps_router,
        "resolve_project_tenant_id_for_access",
        AsyncMock(return_value="tenant-1"),
    )
    monkeypatch.setattr(apps_router, "get_container_with_db", lambda _request, _db: FakeContainer())

    with pytest.raises(HTTPException) as exc_info:
        await apps_router.proxy_resource_read(
            request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
            body=apps_router.MCPResourceReadRequest(
                uri="ui://server-1/index.html",
                project_id="project-1",
                server_name="server-1",
            ),
            db=SimpleNamespace(),
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert exc_info.value.detail == "Failed to read resource from MCP server"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_proxy_resource_read_sanitizes_missing_resource_after_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository as repo_module

    class TimeoutMCPManager:
        async def call_tool(self, **_kwargs: Any) -> Any:
            raise TimeoutError("secret timeout")

    class Container(FakeContainer):
        def sandbox_mcp_server_manager(self) -> TimeoutMCPManager:
            return TimeoutMCPManager()

    monkeypatch.setattr(apps_router, "ensure_project_access", _allow_project_access)
    monkeypatch.setattr(
        apps_router,
        "resolve_project_tenant_id_for_access",
        AsyncMock(return_value="tenant-1"),
    )
    monkeypatch.setattr(apps_router, "get_container_with_db", lambda _request, _db: Container())
    monkeypatch.setattr(repo_module, "SqlMCPServerRepository", MissingMCPServerRepository)

    with pytest.raises(HTTPException) as exc_info:
        await apps_router.proxy_resource_read(
            request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
            body=apps_router.MCPResourceReadRequest(
                uri="ui://secret-server/index.html",
                project_id="project-1",
                server_name="secret-server",
            ),
            db=SimpleNamespace(),
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Resource not found"
    assert "secret-server" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_proxy_resource_read_sanitizes_missing_server_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(apps_router, "ensure_project_access", _allow_project_access)
    monkeypatch.setattr(
        apps_router,
        "resolve_project_tenant_id_for_access",
        AsyncMock(return_value="tenant-1"),
    )
    monkeypatch.setattr(apps_router, "get_container_with_db", lambda _request, _db: FakeContainer())

    with pytest.raises(HTTPException) as exc_info:
        await apps_router.proxy_resource_read(
            request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
            body=apps_router.MCPResourceReadRequest(
                uri="secret-resource-without-server",
                project_id="project-1",
            ),
            db=SimpleNamespace(),
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Cannot determine server name from URI"
    assert "secret-resource" not in exc_info.value.detail


@pytest.mark.unit
def test_extract_html_from_result_sanitizes_error_and_empty_content() -> None:
    error_result = SimpleNamespace(
        is_error=True,
        content=[{"type": "text", "text": "secret upstream resource error"}],
    )
    with pytest.raises(HTTPException) as error_exc:
        apps_router._extract_html_from_result(error_result, "ui://secret/index.html")

    assert error_exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert error_exc.value.detail == "Resource not found"
    assert "secret" not in error_exc.value.detail

    empty_result = SimpleNamespace(is_error=False, content=[])
    with pytest.raises(HTTPException) as empty_exc:
        apps_router._extract_html_from_result(empty_result, "ui://secret/index.html")

    assert empty_exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert empty_exc.value.detail == "Resource content not found"
    assert "secret" not in empty_exc.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_proxy_resource_list_sanitizes_mcp_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(apps_router, "ensure_project_access", _allow_project_access)
    monkeypatch.setattr(
        apps_router,
        "resolve_project_tenant_id_for_access",
        AsyncMock(return_value="tenant-1"),
    )
    monkeypatch.setattr(apps_router, "get_container_with_db", lambda _request, _db: FakeContainer())

    with pytest.raises(HTTPException) as exc_info:
        await apps_router.proxy_resource_list(
            request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
            body=apps_router.MCPResourceListRequest(project_id="project-1"),
            db=SimpleNamespace(),
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert exc_info.value.detail == "Failed to list resources from MCP server"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_proxy_resource_list_uses_authorized_project_tenant(
    monkeypatch: pytest.MonkeyPatch,
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    calls: list[dict[str, str]] = []

    class CapturingMCPManager:
        async def list_resources(self, *, project_id: str, tenant_id: str) -> list[dict[str, str]]:
            calls.append({"project_id": project_id, "tenant_id": tenant_id})
            return [{"uri": "ui://server/index.html"}]

    class Container(FakeContainer):
        def sandbox_mcp_server_manager(self) -> CapturingMCPManager:
            return CapturingMCPManager()

    monkeypatch.setattr(apps_router, "get_container_with_db", lambda _request, _db: Container())

    response = await apps_router.proxy_resource_list(
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
        body=apps_router.MCPResourceListRequest(project_id=test_project_db.id),
        db=test_db,
        tenant_id="fallback-tenant",
        current_user=test_user,
    )

    assert response.resources == [{"uri": "ui://server/index.html"}]
    assert calls == [{"project_id": test_project_db.id, "tenant_id": test_project_db.tenant_id}]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_mcp_app_sanitizes_missing_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        apps_router, "_get_mcp_app_service", lambda _request, _db: EmptyAppService()
    )
    monkeypatch.setattr(
        apps_router, "_get_mcp_runtime_service", AsyncMock(return_value=FailingRuntime())
    )
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await apps_router.delete_mcp_app(
            request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
            app_id="app-secret",
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "MCP App not found"
    assert "secret" not in exc_info.value.detail
    db.rollback.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_mcp_app_resource_sanitizes_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        apps_router, "_get_mcp_app_service", lambda _request, _db: ExistingAppService()
    )
    monkeypatch.setattr(apps_router, "ensure_project_access", _allow_project_access)
    monkeypatch.setattr(
        apps_router, "_get_mcp_runtime_service", AsyncMock(return_value=FailingRuntime())
    )
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await apps_router.refresh_mcp_app_resource(
            request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
            app_id="app-secret",
            db=db,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Access denied"
    assert "secret" not in exc_info.value.detail
    db.rollback.assert_awaited_once()
