"""Unit tests for sandbox tool route error handling."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers.sandbox import tools as tools_router
from src.infrastructure.adapters.primary.web.routers.sandbox.schemas import ToolCallRequest


class FailingSandboxAdapter:
    async def connect_mcp(self, sandbox_id: str) -> bool:
        raise RuntimeError(f"internal connection secret for {sandbox_id}")

    async def list_tools(self, sandbox_id: str) -> list[dict[str, Any]]:
        raise RuntimeError(f"internal tool list secret for {sandbox_id}")

    async def call_tool(
        self,
        sandbox_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        raise RuntimeError(f"internal tool call secret for {sandbox_id}:{tool_name}")


async def _allow_sandbox_access(**_kwargs: Any) -> tuple[SimpleNamespace, str]:
    return SimpleNamespace(project_id="project-1"), "project-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connect_mcp_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools_router, "assert_caller_owns_sandbox", _allow_sandbox_access)

    with pytest.raises(HTTPException) as exc_info:
        await tools_router.connect_mcp(
            sandbox_id="sandbox-secret",
            current_user=SimpleNamespace(id="user-1", is_superuser=True),
            adapter=FailingSandboxAdapter(),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to connect MCP client"
    assert "internal" not in exc_info.value.detail
    assert "sandbox-secret" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_tools_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools_router, "assert_caller_owns_sandbox", _allow_sandbox_access)

    with pytest.raises(HTTPException) as exc_info:
        await tools_router.list_tools(
            sandbox_id="sandbox-secret",
            current_user=SimpleNamespace(id="user-1", is_superuser=True),
            adapter=FailingSandboxAdapter(),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to list sandbox tools"
    assert "internal" not in exc_info.value.detail
    assert "sandbox-secret" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_tool_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools_router, "assert_caller_owns_sandbox", _allow_sandbox_access)

    with pytest.raises(HTTPException) as exc_info:
        await tools_router.call_tool(
            sandbox_id="sandbox-secret",
            request=ToolCallRequest(tool_name="bash", arguments={"command": "pwd"}),
            current_user=SimpleNamespace(id="user-1", is_superuser=True),
            adapter=FailingSandboxAdapter(),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to call sandbox tool"
    assert "internal" not in exc_info.value.detail
    assert "sandbox-secret" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_agent_tools_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingToolRegistry:
        async def get_sandbox_tools(self, sandbox_id: str) -> list[str] | None:
            raise RuntimeError(f"internal registry secret for {sandbox_id}")

    class FakeDIContainer:
        def sandbox_tool_registry(self) -> FailingToolRegistry:
            return FailingToolRegistry()

    import src.configuration.di_container as di_container

    monkeypatch.setattr(tools_router, "assert_caller_owns_sandbox", _allow_sandbox_access)
    monkeypatch.setattr(di_container, "DIContainer", FakeDIContainer)

    with pytest.raises(HTTPException) as exc_info:
        await tools_router.list_agent_tools(
            sandbox_id="sandbox-secret",
            current_user=SimpleNamespace(id="user-1", is_superuser=True),
            adapter=FailingSandboxAdapter(),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to list agent tools"
    assert "internal" not in exc_info.value.detail
    assert "sandbox-secret" not in exc_info.value.detail
