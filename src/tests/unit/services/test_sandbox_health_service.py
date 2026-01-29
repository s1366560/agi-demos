"""Tests for SandboxHealthService."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.services.sandbox_health_service import (
    ComponentHealth,
    HealthCheckLevel,
    HealthCheckResult,
    HealthStatus,
    SandboxHealthService,
)


class TestSandboxHealthService:
    """测试 SandboxHealthService."""

    @pytest.fixture
    def mock_adapter(self):
        """创建 mock sandbox adapter."""
        adapter = MagicMock()
        adapter.get_sandbox = AsyncMock()
        adapter.health_check = AsyncMock()
        adapter.call_tool = AsyncMock()
        return adapter

    @pytest.fixture
    def service(self, mock_adapter):
        """创建健康检查服务实例."""
        return SandboxHealthService(sandbox_adapter=mock_adapter, default_timeout=5.0)

    @pytest.fixture
    def running_sandbox(self):
        """创建运行中的 mock sandbox."""
        sandbox = MagicMock()
        sandbox.id = "test-sandbox-123"
        sandbox.status = "running"
        sandbox.mcp_port = 18765
        sandbox.desktop_port = 16080
        sandbox.terminal_port = 17681
        sandbox.mcp_client = MagicMock()
        sandbox.mcp_client.is_connected = True
        return sandbox

    @pytest.fixture
    def stopped_sandbox(self):
        """创建已停止的 mock sandbox."""
        sandbox = MagicMock()
        sandbox.id = "test-sandbox-stopped"
        sandbox.status = "stopped"
        sandbox.mcp_port = None
        sandbox.desktop_port = None
        sandbox.terminal_port = None
        sandbox.mcp_client = None
        return sandbox

    @pytest.mark.asyncio
    async def test_check_basic_health_running(self, service: SandboxHealthService, mock_adapter, running_sandbox):
        """运行中的 sandbox 基础健康检查应该返回健康."""
        mock_adapter.get_sandbox.return_value = running_sandbox

        result = await service.check_health("test-sandbox-123", HealthCheckLevel.BASIC)

        assert result.healthy is True
        assert result.status == HealthStatus.HEALTHY
        assert result.level == HealthCheckLevel.BASIC
        assert result.sandbox_id == "test-sandbox-123"

    @pytest.mark.asyncio
    async def test_check_basic_health_stopped(self, service: SandboxHealthService, mock_adapter, stopped_sandbox):
        """已停止的 sandbox 基础健康检查应该返回不健康."""
        mock_adapter.get_sandbox.return_value = stopped_sandbox

        result = await service.check_health("test-sandbox-stopped", HealthCheckLevel.BASIC)

        assert result.healthy is False
        assert result.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_check_basic_health_not_found(self, service: SandboxHealthService, mock_adapter):
        """不存在的 sandbox 应该返回不健康."""
        mock_adapter.get_sandbox.return_value = None

        result = await service.check_health("non-existent", HealthCheckLevel.BASIC)

        assert result.healthy is False
        assert result.status == HealthStatus.UNHEALTHY
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_check_mcp_health(self, service: SandboxHealthService, mock_adapter, running_sandbox):
        """MCP 健康检查应该验证连接状态."""
        mock_adapter.get_sandbox.return_value = running_sandbox

        result = await service.check_health("test-sandbox-123", HealthCheckLevel.MCP)

        assert result.level == HealthCheckLevel.MCP
        # MCP 连接正常应该健康
        if running_sandbox.mcp_client.is_connected:
            assert result.details.get("mcp_connected") is True

    @pytest.mark.asyncio
    async def test_check_services_health(self, service: SandboxHealthService, mock_adapter, running_sandbox):
        """Services 健康检查应该检查 desktop 和 terminal."""
        mock_adapter.get_sandbox.return_value = running_sandbox
        # Mock tool call 返回
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"running": true}'}],
            "is_error": False,
        }

        result = await service.check_health("test-sandbox-123", HealthCheckLevel.SERVICES)

        assert result.level == HealthCheckLevel.SERVICES
        assert "desktop_running" in result.details
        assert "terminal_running" in result.details

    @pytest.mark.asyncio
    async def test_check_full_health(self, service: SandboxHealthService, mock_adapter, running_sandbox):
        """Full 健康检查应该执行所有检查."""
        mock_adapter.get_sandbox.return_value = running_sandbox
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"running": true}'}],
            "is_error": False,
        }

        result = await service.check_health("test-sandbox-123", HealthCheckLevel.FULL)

        assert result.level == HealthCheckLevel.FULL
        assert "container_running" in result.details
        assert "mcp_connected" in result.details

    @pytest.mark.asyncio
    async def test_check_all_sandboxes(self, service: SandboxHealthService, mock_adapter):
        """批量检查多个 sandbox."""
        # 创建多个 mock sandbox
        sandboxes = []
        for i in range(3):
            sb = MagicMock()
            sb.id = f"sandbox-{i}"
            sb.status = "running"
            sb.mcp_port = 18765 + i
            sb.mcp_client = MagicMock()
            sb.mcp_client.is_connected = True
            sandboxes.append(sb)

        mock_adapter.get_sandbox.side_effect = sandboxes

        results = await service.check_all_sandboxes(
            ["sandbox-0", "sandbox-1", "sandbox-2"],
            HealthCheckLevel.BASIC,
        )

        assert len(results) == 3
        assert all(r.healthy for r in results)

    @pytest.mark.asyncio
    async def test_check_all_sandboxes_with_exception(self, service: SandboxHealthService, mock_adapter):
        """批量检查时某个 sandbox 抛出异常应该继续检查其他."""
        # 创建 mock sandbox，中间会抛出异常
        def get_side_effect(sid):
            if sid == "sandbox-1":
                raise Exception("Network error")
            sb = MagicMock()
            sb.id = sid
            sb.status = "running"
            sb.mcp_port = 18765
            return sb

        mock_adapter.get_sandbox.side_effect = get_side_effect

        results = await service.check_all_sandboxes(
            ["sandbox-0", "sandbox-1", "sandbox-2"],
            HealthCheckLevel.BASIC,
        )

        assert len(results) == 3
        # sandbox-0 和 sandbox-2 应该成功
        assert results[0].healthy is True
        assert results[2].healthy is True
        # sandbox-1 返回 HealthCheckResult (异常被处理)
        assert results[1].healthy is False
        assert "Failed to get sandbox" in results[1].errors[0]

    @pytest.mark.asyncio
    async def test_check_basic_health_exception(self, service: SandboxHealthService, mock_adapter):
        """获取 sandbox 抛出异常时应该返回错误状态."""
        mock_adapter.get_sandbox.side_effect = Exception("Docker error")

        result = await service.check_basic_health("test-sandbox-123")

        assert result.container is False
        assert result.container_status == "error"

    @pytest.mark.asyncio
    async def test_check_mcp_health_no_client(self, service: SandboxHealthService, mock_adapter, running_sandbox):
        """没有 MCP 客户端时应该返回 False."""
        running_sandbox.mcp_client = None
        mock_adapter.get_sandbox.return_value = running_sandbox

        result = await service.check_mcp_health("test-sandbox-123")

        assert result is False

    @pytest.mark.asyncio
    async def test_check_services_health_no_adapter(self):
        """没有 adapter 时应该返回默认值."""
        service = SandboxHealthService(sandbox_adapter=None)

        result = await service.check_services_health("test-sandbox-123")

        assert result["desktop"] is False
        assert result["terminal"] is False

    def test_health_check_result_to_dict(self):
        """应该转换为字典."""
        result = HealthCheckResult(
            level=HealthCheckLevel.BASIC,
            status=HealthStatus.HEALTHY,
            healthy=True,
            details={"container": "running"},
            timestamp=None,
            sandbox_id="test-123",
        )
        result.timestamp = result.timestamp or datetime.now()

        data = result.to_dict()

        assert data["level"] == "basic"
        assert data["status"] == "healthy"
        assert data["healthy"] is True
        assert data["sandbox_id"] == "test-123"
