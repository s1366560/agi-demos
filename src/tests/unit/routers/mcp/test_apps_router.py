"""Tests for MCP app route hardening."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers.mcp import apps as apps_router


class EmptyAppService:
    async def list_apps(self, _project_id: str, *, include_disabled: bool = False) -> list[Any]:
        return []


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


async def _allow_project_access(*_args: Any, **_kwargs: Any) -> None:
    return None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_proxy_resource_read_sanitizes_mcp_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(apps_router, "ensure_project_access", _allow_project_access)
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
        )

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert exc_info.value.detail == "Failed to read resource from MCP server"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_proxy_resource_list_sanitizes_mcp_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(apps_router, "ensure_project_access", _allow_project_access)
    monkeypatch.setattr(apps_router, "get_container_with_db", lambda _request, _db: FakeContainer())

    with pytest.raises(HTTPException) as exc_info:
        await apps_router.proxy_resource_list(
            request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
            body=apps_router.MCPResourceListRequest(project_id="project-1"),
            db=SimpleNamespace(),
            tenant_id="tenant-1",
        )

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert exc_info.value.detail == "Failed to list resources from MCP server"
    assert "internal" not in exc_info.value.detail
