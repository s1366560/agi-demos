"""Tests for MCP app route hardening."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.mcp_application_authority_v2 import (
    MCPApplicationAuthorityV2,
)
from src.infrastructure.adapters.primary.web.routers.mcp import apps as apps_router
from src.infrastructure.adapters.secondary.persistence.models import Project, User
from src.infrastructure.plugins.v2.mcp_services import SqlMCPProjectAccessV2


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


class FailingRuntime:
    async def delete_app(self, _app_id: str, _tenant_id: str) -> None:
        raise ValueError("MCP App not found: app-secret")

    async def refresh_app_resource(self, _app_id: str, _tenant_id: str) -> None:
        raise PermissionError("Access denied for app-secret")


class MissingMCPServerRepository:
    async def get_by_name(self, _project_id: str, _server_name: str) -> None:
        return None


async def _allow_project_access(*_args: Any, **_kwargs: Any) -> None:
    return None


def _authority(
    *,
    db: object | None = None,
    tenant_id: str = "tenant-1",
    user_id: str = "user-1",
    app_service: object | None = None,
    manager: object | None = None,
    runtime: object | None = None,
    repository: object | None = None,
    access: object | None = None,
) -> MCPApplicationAuthorityV2:
    return cast(
        MCPApplicationAuthorityV2,
        SimpleNamespace(
            db=db or SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock()),
            tenant_id=tenant_id,
            user_id=user_id,
            services=SimpleNamespace(
                app_service=app_service or EmptyAppService(),
                sandbox_manager=manager or FailingMCPManager(),
                runtime_service=runtime or FailingRuntime(),
                server_repository=repository or MissingMCPServerRepository(),
                access=access,
            ),
        ),
    )


@pytest.mark.unit
async def test_direct_cloud_tool_call_fails_closed_for_idempotency_key() -> None:
    body = apps_router.MCPDirectToolCallRequest(
        project_id="project-1",
        server_name="server-1",
        tool_name="visible-tool",
        arguments={},
        idempotency_key="desktop-mcp-tool-call:cloud-1",
    )

    response = await apps_router.proxy_tool_call_direct(
        body=body,
        authority=_authority(),
    )

    assert response.is_error is True
    assert response.error_code == -32000
    assert response.error_message == "cloud_mcp_tool_idempotency_unavailable"


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
    with pytest.raises(HTTPException) as exc_info:
        await apps_router.proxy_resource_read(
            body=apps_router.MCPResourceReadRequest(
                uri="ui://server-1/index.html",
                project_id="project-1",
                server_name="server-1",
            ),
            authority=_authority(),
        )

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert exc_info.value.detail == "Failed to read resource from MCP server"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_proxy_resource_read_sanitizes_missing_resource_after_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TimeoutMCPManager:
        async def call_tool(self, **_kwargs: Any) -> Any:
            raise TimeoutError("secret timeout")

    monkeypatch.setattr(apps_router, "ensure_project_access", _allow_project_access)
    monkeypatch.setattr(
        apps_router,
        "resolve_project_tenant_id_for_access",
        AsyncMock(return_value="tenant-1"),
    )
    with pytest.raises(HTTPException) as exc_info:
        await apps_router.proxy_resource_read(
            body=apps_router.MCPResourceReadRequest(
                uri="ui://secret-server/index.html",
                project_id="project-1",
                server_name="secret-server",
            ),
            authority=_authority(manager=TimeoutMCPManager()),
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
    with pytest.raises(HTTPException) as exc_info:
        await apps_router.proxy_resource_read(
            body=apps_router.MCPResourceReadRequest(
                uri="secret-resource-without-server",
                project_id="project-1",
            ),
            authority=_authority(),
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
    with pytest.raises(HTTPException) as exc_info:
        await apps_router.proxy_resource_list(
            body=apps_router.MCPResourceListRequest(project_id="project-1"),
            authority=_authority(),
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

    response = await apps_router.proxy_resource_list(
        body=apps_router.MCPResourceListRequest(project_id=test_project_db.id),
        authority=_authority(
            db=test_db,
            tenant_id=test_project_db.tenant_id,
            user_id=test_user.id,
            manager=CapturingMCPManager(),
            access=SqlMCPProjectAccessV2(_session=test_db),
        ),
    )

    assert response.resources == [{"uri": "ui://server/index.html"}]
    assert calls == [{"project_id": test_project_db.id, "tenant_id": test_project_db.tenant_id}]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_mcp_app_sanitizes_missing_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await apps_router.delete_mcp_app(
            app_id="app-secret",
            authority=_authority(db=db),
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
    monkeypatch.setattr(apps_router, "ensure_project_access", _allow_project_access)
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await apps_router.refresh_mcp_app_resource(
            app_id="app-secret",
            authority=_authority(
                db=db,
                app_service=ExistingAppService(),
            ),
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Access denied"
    assert "secret" not in exc_info.value.detail
    db.rollback.assert_awaited_once()
