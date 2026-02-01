"""Tests for SandboxManagerService."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.services.sandbox_manager_service import (
    SandboxCreateResult,
    SandboxManagerService,
)
from src.domain.ports.services.sandbox_port import SandboxStatus


class TestSandboxCreateResult:
    """测试 SandboxCreateResult."""

    def test_to_dict(self) -> None:
        """应该转换为字典."""
        result = SandboxCreateResult(
            sandbox_id="test-sandbox-123",
            status=SandboxStatus.RUNNING,
            project_path="/tmp/test",
            endpoint="test-endpoint",
            websocket_url="ws://localhost:8765",
            mcp_port=18765,
            desktop_port=16080,
            terminal_port=17681,
        )

        data = result.to_dict()

        assert data["id"] == "test-sandbox-123"
        assert data["status"] == "running"
        assert data["project_path"] == "/tmp/test"
        assert data["websocket_url"] == "ws://localhost:8765"


class TestSandboxManagerService:
    """测试 SandboxManagerService."""

    @pytest.fixture
    def mock_adapter(self):
        """创建 mock 适配器."""
        adapter = MagicMock()
        adapter.create_sandbox = AsyncMock()
        adapter.terminate_sandbox = AsyncMock()
        adapter.get_sandbox = AsyncMock()
        adapter.list_sandboxes = AsyncMock()
        adapter.cleanup_expired = AsyncMock()
        adapter.get_sandbox_stats = AsyncMock()
        adapter.health_check = AsyncMock()
        return adapter

    @pytest.fixture
    def service(self, mock_adapter):
        """创建 Sandbox 管理器实例."""
        return SandboxManagerService(
            sandbox_adapter=mock_adapter,
            default_timeout=300.0,
        )

    @pytest.mark.asyncio
    async def test_create_sandbox_default(self, service: SandboxManagerService, mock_adapter) -> None:
        """应该使用默认配置创建 Sandbox."""
        mock_sandbox = MagicMock()
        mock_sandbox.id = "sandbox-123"
        mock_sandbox.status = SandboxStatus.RUNNING
        mock_sandbox.project_path = "/tmp/memstack_test"
        mock_sandbox.endpoint = "endpoint"
        mock_sandbox.websocket_url = "ws://localhost:18765"
        mock_sandbox.mcp_port = 18765
        mock_sandbox.desktop_port = 16080
        mock_sandbox.terminal_port = 17681
        mock_sandbox.created_at = MagicMock()
        mock_sandbox.tools = ["bash", "read"]

        mock_adapter.create_sandbox.return_value = mock_sandbox
        mock_adapter.connect_mcp = AsyncMock(return_value=True)
        mock_adapter.list_tools = AsyncMock(return_value=[
            {"name": "bash"},
            {"name": "read"},
        ])

        result = await service.create_sandbox("test-project")

        assert result.sandbox_id == "sandbox-123"
        assert result.status == SandboxStatus.RUNNING
        assert result.mcp_port == 18765
        assert result.tools == ["bash", "read"]

    @pytest.mark.asyncio
    async def test_create_sandbox_with_profile(self, service: SandboxManagerService, mock_adapter) -> None:
        """应该使用指定 profile 创建 Sandbox."""
        from src.application.services.sandbox_profile import SandboxProfileType

        mock_sandbox = MagicMock()
        mock_sandbox.id = "sandbox-lite-123"
        mock_sandbox.status = SandboxStatus.RUNNING
        mock_sandbox.project_path = "/tmp/memstack_test"
        mock_sandbox.mcp_port = 18765
        mock_sandbox.desktop_port = None  # lite 没有 desktop
        mock_sandbox.terminal_port = 17681

        mock_adapter.create_sandbox.return_value = mock_sandbox
        mock_adapter.connect_mcp = AsyncMock(return_value=True)
        mock_adapter.list_tools = AsyncMock(return_value=[])

        result = await service.create_sandbox(
            "test-project",
            profile=SandboxProfileType.LITE,
        )

        assert result.sandbox_id == "sandbox-lite-123"
        assert result.desktop_port is None
        # 验证配置使用了正确的资源限制
        call_args = mock_adapter.create_sandbox.call_args
        # create_sandbox 使用关键字参数调用，所以从 kwargs 获取
        config = call_args[1].get("config")
        assert config is not None
        assert config.memory_limit == "512m"
        assert config.cpu_limit == "0.5"

    @pytest.mark.asyncio
    async def test_terminate_sandbox(self, service: SandboxManagerService, mock_adapter) -> None:
        """应该终止 Sandbox."""
        mock_adapter.terminate_sandbox.return_value = True

        result = await service.terminate_sandbox("sandbox-123")

        assert result is True
        mock_adapter.terminate_sandbox.assert_called_once_with("sandbox-123")

    @pytest.mark.asyncio
    async def test_get_sandbox(self, service: SandboxManagerService, mock_adapter) -> None:
        """应该获取 Sandbox 信息."""
        mock_sandbox = MagicMock()
        mock_sandbox.id = "sandbox-123"
        mock_sandbox.status = SandboxStatus.RUNNING

        mock_adapter.get_sandbox.return_value = mock_sandbox

        result = await service.get_sandbox("sandbox-123")

        assert result is not None
        assert result.id == "sandbox-123"

    @pytest.mark.asyncio
    async def test_get_sandbox_not_found(self, service: SandboxManagerService, mock_adapter) -> None:
        """不存在的 Sandbox 应该返回 None."""
        mock_adapter.get_sandbox.return_value = None

        result = await service.get_sandbox("non-existent")

        assert result is None

    @pytest.mark.asyncio
    async def test_list_sandboxes(self, service: SandboxManagerService, mock_adapter) -> None:
        """应该列出所有 Sandbox."""
        mock_sandboxes = [
            MagicMock(id="sb-1", status=SandboxStatus.RUNNING),
            MagicMock(id="sb-2", status=SandboxStatus.STOPPED),
        ]
        mock_adapter.list_sandboxes.return_value = mock_sandboxes

        results = await service.list_sandboxes()

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_list_sandboxes_with_filter(self, service: SandboxManagerService, mock_adapter) -> None:
        """应该按状态过滤 Sandbox."""
        all_sandboxes = [
            MagicMock(id="sb-1", status=SandboxStatus.RUNNING),
            MagicMock(id="sb-2", status=SandboxStatus.STOPPED),
            MagicMock(id="sb-3", status=SandboxStatus.RUNNING),
        ]
        mock_adapter.list_sandboxes.return_value = all_sandboxes

        results = await service.list_sandboxes(status=SandboxStatus.RUNNING)

        assert len(results) == 2
        assert all(sb.status == SandboxStatus.RUNNING for sb in results)

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, service: SandboxManagerService, mock_adapter) -> None:
        """应该清理过期的 Sandbox."""
        mock_adapter.cleanup_expired.return_value = 3

        count = await service.cleanup_expired(max_age_seconds=3600)

        assert count == 3
        mock_adapter.cleanup_expired.assert_called_once_with(max_age_seconds=3600)

    @pytest.mark.asyncio
    async def test_get_sandbox_stats(self, service: SandboxManagerService, mock_adapter) -> None:
        """应该获取 Sandbox 统计信息."""
        mock_adapter.get_sandbox_stats.return_value = {
            "cpu_percent": 50.5,
            "memory_usage": 1024 * 1024 * 512,
            "memory_limit": 1024 * 1024 * 1024 * 2,
            "memory_percent": 25.0,
            "pids": 5,
            "status": "running",
        }

        stats = await service.get_sandbox_stats("sandbox-123")

        assert stats["cpu_percent"] == 50.5
        assert stats["memory_percent"] == 25.0

    @pytest.mark.asyncio
    async def test_health_check(self, service: SandboxManagerService, mock_adapter) -> None:
        """应该检查 Sandbox 健康状态."""
        mock_adapter.health_check.return_value = True

        result = await service.health_check("sandbox-123")

        assert result is True

    @pytest.mark.asyncio
    async def test_batch_create(self, service: SandboxManagerService, mock_adapter) -> None:
        """应该批量创建 Sandbox."""
        mock_sandboxes = []
        for i in range(3):
            sb = MagicMock()
            sb.id = f"sandbox-{i}"
            sb.status = SandboxStatus.RUNNING
            sb.project_path = f"/tmp/memstack_project{i}"
            sb.mcp_port = 18765 + i
            sb.created_at = MagicMock()
            sb.tools = []
            mock_sandboxes.append(sb)

        mock_adapter.create_sandbox.side_effect = mock_sandboxes
        mock_adapter.connect_mcp = AsyncMock(return_value=True)
        mock_adapter.list_tools = AsyncMock(return_value=[])

        requests = [
            {"project_id": f"project{i}", "project_path": f"/tmp/path{i}"}
            for i in range(3)
        ]

        results = await service.batch_create(requests)

        assert len(results) == 3
        assert all(r.sandbox_id.startswith("sandbox-") for r in results)

    @pytest.mark.asyncio
    async def test_resolve_project_path(self, service: SandboxManagerService) -> None:
        """应该自动解析项目路径."""
        # 默认路径生成
        path = service._resolve_project_path("my-project", None)

        assert path == "/tmp/memstack_my-project"

        # 自定义路径
        path = service._resolve_project_path("my-project", "/custom/path")

        assert path == "/custom/path"

    def test_resolve_config(self, service: SandboxManagerService) -> None:
        """应该解析 Sandbox 配置."""
        from src.application.services.sandbox_profile import SandboxProfileType

        config = service._resolve_config(
            SandboxProfileType.LITE,
            {"memory_limit": "1g"},
        )

        assert config.memory_limit == "1g"  # 覆盖值
        assert config.cpu_limit == "0.5"  # profile 默认值
