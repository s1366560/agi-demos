"""Tests for MCP server prompts and logs router endpoints."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers.mcp.servers import (
    list_mcp_server_logs,
    list_mcp_server_prompts,
    set_mcp_server_log_level,
)


@pytest.mark.unit
class TestMCPServerPromptsAndLogs:
    async def test_list_prompts_returns_frontend_response_shape(self) -> None:
        runtime = SimpleNamespace(
            list_server_prompts=AsyncMock(return_value=[{"name": "review"}]),
        )

        with patch(
            "src.infrastructure.adapters.primary.web.routers.mcp.servers._get_runtime_service",
            new=AsyncMock(return_value=runtime),
        ):
            response = await list_mcp_server_prompts(
                server_id="srv-1",
                request=SimpleNamespace(),
                db=AsyncMock(),
                tenant_id="tenant-1",
            )

        assert response == {"prompts": [{"name": "review"}]}
        runtime.list_server_prompts.assert_awaited_once_with("srv-1", "tenant-1")

    async def test_set_log_level_forwards_to_runtime_and_commits(self) -> None:
        runtime = SimpleNamespace(set_server_log_level=AsyncMock(return_value=True))
        request = SimpleNamespace(json=AsyncMock(return_value={"level": "DEBUG"}))
        db = AsyncMock()

        with patch(
            "src.infrastructure.adapters.primary.web.routers.mcp.servers._get_runtime_service",
            new=AsyncMock(return_value=runtime),
        ):
            response = await set_mcp_server_log_level(
                server_id="srv-1",
                request=request,
                db=db,
                tenant_id="tenant-1",
            )

        assert response == {"status": "ok", "level": "debug"}
        runtime.set_server_log_level.assert_awaited_once_with("srv-1", "tenant-1", "debug")
        db.commit.assert_awaited_once()

    async def test_set_log_level_rejects_invalid_level(self) -> None:
        request = SimpleNamespace(json=AsyncMock(return_value={"level": "verbose"}))

        with pytest.raises(HTTPException) as exc_info:
            await set_mcp_server_log_level(
                server_id="srv-1",
                request=request,
                db=AsyncMock(),
                tenant_id="tenant-1",
            )

        assert exc_info.value.status_code == 400

    async def test_list_logs_returns_persisted_lifecycle_events(self) -> None:
        event = SimpleNamespace(
            status="failed",
            event_type="server.sync",
            error_message="sync failed",
            metadata_json={"tool_count": 0},
            created_at=datetime(2026, 5, 14, tzinfo=UTC),
        )
        scalar_result = MagicMock()
        scalar_result.all.return_value = [event]
        query_result = MagicMock()
        query_result.scalars.return_value = scalar_result
        db = AsyncMock()
        db.execute = AsyncMock(return_value=query_result)
        repo = MagicMock()
        repo.get_by_id = AsyncMock(
            return_value=SimpleNamespace(id="srv-1", tenant_id="tenant-1")
        )

        with patch(
            "src.infrastructure.adapters.primary.web.routers.mcp.servers.SqlMCPServerRepository",
            return_value=repo,
        ):
            response = await list_mcp_server_logs(
                server_id="srv-1",
                limit=100,
                db=db,
                tenant_id="tenant-1",
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
