"""Tests for MCP server prompts and logs router endpoints."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers.mcp.servers import (
    MCP_PROJECT_WRITE_ROLES_V2,
    list_mcp_server_logs,
    list_mcp_server_prompts,
    set_mcp_server_log_level,
)
from src.infrastructure.plugins.v2.mcp_services import MCPLifecycleEventRecordV2


@pytest.mark.unit
class TestMCPServerPromptsAndLogs:
    async def test_list_prompts_returns_frontend_response_shape(self) -> None:
        runtime = SimpleNamespace(
            list_server_prompts=AsyncMock(return_value=[{"name": "review"}]),
        )
        authority = SimpleNamespace(services=SimpleNamespace(runtime_service=runtime))

        with patch(
            "src.infrastructure.adapters.primary.web.routers.mcp.servers._get_mcp_server_for_tenant",
            new=AsyncMock(return_value=SimpleNamespace(id="srv-1", tenant_id="tenant-1")),
        ) as access:
            response = await list_mcp_server_prompts(
                server_id="srv-1",
                authority=authority,
            )

        access.assert_awaited_once_with(authority, "srv-1")
        assert response == {"prompts": [{"name": "review"}]}
        runtime.list_server_prompts.assert_awaited_once_with("srv-1", "tenant-1")

    async def test_set_log_level_forwards_to_runtime_and_commits(self) -> None:
        runtime = SimpleNamespace(set_server_log_level=AsyncMock(return_value=True))
        request = SimpleNamespace(json=AsyncMock(return_value={"level": "DEBUG"}))
        db = AsyncMock()
        authority = SimpleNamespace(db=db, services=SimpleNamespace(runtime_service=runtime))

        with patch(
            "src.infrastructure.adapters.primary.web.routers.mcp.servers._get_mcp_server_for_tenant",
            new=AsyncMock(return_value=SimpleNamespace(id="srv-1", tenant_id="tenant-1")),
        ) as access:
            response = await set_mcp_server_log_level(
                server_id="srv-1",
                request=request,
                authority=authority,
            )

        assert response == {"status": "ok", "level": "debug"}
        access.assert_awaited_once_with(authority, "srv-1", MCP_PROJECT_WRITE_ROLES_V2)
        runtime.set_server_log_level.assert_awaited_once_with("srv-1", "tenant-1", "debug")
        db.commit.assert_awaited_once()

    async def test_set_log_level_rejects_invalid_level(self) -> None:
        request = SimpleNamespace(json=AsyncMock(return_value={"level": "verbose"}))
        runtime = SimpleNamespace(set_server_log_level=AsyncMock())
        db = AsyncMock()
        authority = SimpleNamespace(db=db, services=SimpleNamespace(runtime_service=runtime))

        with pytest.raises(HTTPException) as exc_info:
            await set_mcp_server_log_level(
                server_id="srv-1",
                request=request,
                authority=authority,
            )

        assert exc_info.value.status_code == 400
        runtime.set_server_log_level.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_list_logs_returns_persisted_lifecycle_events(self) -> None:
        event = MCPLifecycleEventRecordV2(
            id="event-1",
            status="failed",
            event_type="server.sync",
            error_message="sync failed",
            metadata={"tool_count": 0},
            created_at=datetime(2026, 5, 14, tzinfo=UTC),
        )
        queries = SimpleNamespace(list_server_events=AsyncMock(return_value=[event]))
        authority = SimpleNamespace(services=SimpleNamespace(lifecycle_queries=queries))
        with patch(
            "src.infrastructure.adapters.primary.web.routers.mcp.servers._get_mcp_server_for_tenant",
            new=AsyncMock(return_value=SimpleNamespace(id="srv-1", tenant_id="tenant-1")),
        ) as access:
            response = await list_mcp_server_logs(
                server_id="srv-1",
                limit=100,
                authority=authority,
            )

        access.assert_awaited_once_with(authority, "srv-1")
        queries.list_server_events.assert_awaited_once_with(
            server_id="srv-1", tenant_id="tenant-1", limit=100
        )
        assert response == {
            "logs": [
                {
                    "level": "error",
                    "logger": "server.sync",
                    "data": {
                        "status": "failed",
                        "message": "sync failed",
                        "metadata": {"tool_count": 0},
                    },
                    "timestamp": "2026-05-14T00:00:00+00:00",
                }
            ]
        }
