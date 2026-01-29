"""Tests for ServiceManagerService."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.services.service_manager_service import (
    DesktopConfig,
    ServiceManagerService,
    ServiceState,
    ServiceStatus,
    ServiceType,
    TerminalConfig,
)


class TestServiceState:
    """测试 ServiceState 数据类."""

    def test_service_state_to_dict_desktop(self) -> None:
        """应该将 Desktop 状态转换为字典."""
        state = ServiceState(
            service_type=ServiceType.DESKTOP,
            status=ServiceStatus.RUNNING,
            running=True,
            url="http://localhost:6080/vnc.html",
            port=6080,
            pid=12345,
            display=":1",
            resolution="1280x720",
        )

        result = state.to_dict()

        assert result["service_type"] == "desktop"
        assert result["status"] == "running"
        assert result["running"] is True
        assert result["url"] == "http://localhost:6080/vnc.html"
        assert result["port"] == 6080

    def test_service_state_to_dict_terminal(self) -> None:
        """应该将 Terminal 状态转换为字典."""
        state = ServiceState(
            service_type=ServiceType.TERMINAL,
            status=ServiceStatus.RUNNING,
            running=True,
            url="ws://localhost:7681",
            port=7681,
            pid=54321,
            session_id="term-abc123",
        )

        result = state.to_dict()

        assert result["service_type"] == "terminal"
        assert result["status"] == "running"
        assert result["session_id"] == "term-abc123"


class TestServiceManagerService:
    """测试 ServiceManagerService."""

    @pytest.fixture
    def mock_adapter(self):
        """创建 mock MCP 适配器."""
        adapter = MagicMock()
        adapter.call_tool = AsyncMock()
        return adapter

    @pytest.fixture
    def service(self, mock_adapter):
        """创建服务管理器实例."""
        return ServiceManagerService(mcp_adapter=mock_adapter, default_timeout=30.0)

    @pytest.mark.asyncio
    async def test_start_desktop(self, service: ServiceManagerService, mock_adapter) -> None:
        """应该启动 Desktop 服务."""
        mock_adapter.call_tool.return_value = {
            "content": [{
                "text": '{"success": true, "running": true, "url": "http://localhost:6080/vnc.html", "port": 6080}'
            }],
            "is_error": False,
        }

        result = await service.start_desktop("sandbox-123")

        assert result.service_type == ServiceType.DESKTOP
        assert result.running is True
        assert result.url == "http://localhost:6080/vnc.html"
        assert result.port == 6080

        mock_adapter.call_tool.assert_called_once_with(
            "sandbox-123",
            "start_desktop",
            {
                "resolution": "1280x720",
                "display": ":1",
                "port": 6080,
                "_workspace_dir": "/workspace",
            },
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_start_desktop_custom_config(self, service: ServiceManagerService, mock_adapter) -> None:
        """应该使用自定义配置启动 Desktop."""
        config = DesktopConfig(resolution="1920x1080", display=":2", port=7000)
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"success": true, "running": true, "resolution": "1920x1080", "display": ":2", "port": 7000}'}],
            "is_error": False,
        }

        result = await service.start_desktop("sandbox-123", config)

        # Mock 返回的 JSON 包含这些字段，需要验证调用参数正确
        call_args = mock_adapter.call_tool.call_args
        assert call_args[0][2]["resolution"] == "1920x1080"
        assert call_args[0][2]["display"] == ":2"
        assert call_args[0][2]["port"] == 7000

    @pytest.mark.asyncio
    async def test_stop_desktop(self, service: ServiceManagerService, mock_adapter) -> None:
        """应该停止 Desktop 服务."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"success": true}'}],
            "is_error": False,
        }

        result = await service.stop_desktop("sandbox-123")

        assert result is True

        mock_adapter.call_tool.assert_called_once_with(
            "sandbox-123",
            "stop_desktop",
            {"_workspace_dir": "/workspace"},
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_get_desktop_status_running(self, service: ServiceManagerService, mock_adapter) -> None:
        """应该获取 Desktop 运行状态."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"running": true, "url": "http://localhost:6080/vnc.html", "port": 6080, "display": ":1", "resolution": "1280x720"}'}],
            "is_error": False,
        }

        result = await service.get_desktop_status("sandbox-123")

        assert result.service_type == ServiceType.DESKTOP
        assert result.running is True
        assert result.status == ServiceStatus.RUNNING
        assert result.url == "http://localhost:6080/vnc.html"

    @pytest.mark.asyncio
    async def test_get_desktop_status_stopped(self, service: ServiceManagerService, mock_adapter) -> None:
        """应该获取 Desktop 停止状态."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"running": false}'}],
            "is_error": False,
        }

        result = await service.get_desktop_status("sandbox-123")

        assert result.running is False
        assert result.status == ServiceStatus.STOPPED

    @pytest.mark.asyncio
    async def test_start_terminal(self, service: ServiceManagerService, mock_adapter) -> None:
        """应该启动 Terminal 服务."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"success": true, "running": true, "url": "ws://localhost:7681", "port": 7681, "pid": 54321}'}],
            "is_error": False,
        }

        result = await service.start_terminal("sandbox-123")

        assert result.service_type == ServiceType.TERMINAL
        assert result.running is True
        assert result.url == "ws://localhost:7681"
        assert result.port == 7681
        assert result.pid == 54321

        mock_adapter.call_tool.assert_called_once_with(
            "sandbox-123",
            "start_terminal",
            {"port": 7681, "_workspace_dir": "/workspace"},
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_start_terminal_custom_config(self, service: ServiceManagerService, mock_adapter) -> None:
        """应该使用自定义配置启动 Terminal."""
        config = TerminalConfig(port=8000, shell="/bin/zsh")
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"success": true, "running": true}'}],
            "is_error": False,
        }

        result = await service.start_terminal("sandbox-123", config)

        # TerminalConfig 的 shell 当前实现中未传递到 MCP 工具
        # 验证传递了正确的端口参数
        call_args = mock_adapter.call_tool.call_args
        assert call_args[0][2]["port"] == 8000

    @pytest.mark.asyncio
    async def test_stop_terminal(self, service: ServiceManagerService, mock_adapter) -> None:
        """应该停止 Terminal 服务."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"success": true}'}],
            "is_error": False,
        }

        result = await service.stop_terminal("sandbox-123")

        assert result is True

        mock_adapter.call_tool.assert_called_once_with(
            "sandbox-123",
            "stop_terminal",
            {"_workspace_dir": "/workspace"},
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_get_terminal_status(self, service: ServiceManagerService, mock_adapter) -> None:
        """应该获取 Terminal 状态."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"running": true, "url": "ws://localhost:7681", "port": 7681, "session_id": "term-xyz"}'}],
            "is_error": False,
        }

        result = await service.get_terminal_status("sandbox-123")

        assert result.service_type == ServiceType.TERMINAL
        assert result.running is True
        assert result.session_id == "term-xyz"

    @pytest.mark.asyncio
    async def test_get_all_status(self, service: ServiceManagerService, mock_adapter) -> None:
        """应该获取所有服务状态."""
        # Mock 不同的响应
        def side_effect(sid, tool, args, **kwargs):
            if tool == "get_desktop_status":
                return {
                    "content": [{"text": '{"running": true, "url": "http://localhost:6080"}'}],
                    "is_error": False,
                }
            else:
                return {
                    "content": [{"text": '{"running": true, "url": "ws://localhost:7681"}'}],
                    "is_error": False,
                }

        mock_adapter.call_tool.side_effect = side_effect

        result = await service.get_all_status("sandbox-123")

        assert "desktop" in result
        assert "terminal" in result
        assert result["desktop"].running is True
        assert result["terminal"].running is True

    @pytest.mark.asyncio
    async def test_restart_desktop(self, service: ServiceManagerService, mock_adapter) -> None:
        """应该重启 Desktop 服务."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"success": true, "running": true, "url": "http://localhost:6080/vnc.html", "port": 6080}'}],
            "is_error": False,
        }

        result = await service.restart_desktop("sandbox-123")

        assert result.running is True
        # 应该调用 stop 然后 start
        assert mock_adapter.call_tool.call_count == 2

    @pytest.mark.asyncio
    async def test_restart_terminal(self, service: ServiceManagerService, mock_adapter) -> None:
        """应该重启 Terminal 服务."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"success": true, "running": true, "url": "ws://localhost:7681", "port": 7681}'}],
            "is_error": False,
        }

        result = await service.restart_terminal("sandbox-123")

        assert result.running is True
        assert mock_adapter.call_tool.call_count == 2

    @pytest.mark.asyncio
    async def test_start_desktop_error(self, service: ServiceManagerService, mock_adapter) -> None:
        """Desktop 启动失败应该返回错误状态."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": "Failed to start"}],
            "is_error": True,
        }

        result = await service.start_desktop("sandbox-123")

        assert result.running is False
        assert result.status == ServiceStatus.ERROR
        assert result.error == "Failed to start"

    @pytest.mark.asyncio
    async def test_start_terminal_error(self, service: ServiceManagerService, mock_adapter) -> None:
        """Terminal 启动失败应该返回错误状态."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": "Failed to start terminal"}],
            "is_error": True,
        }

        result = await service.start_terminal("sandbox-123")

        assert result.running is False
        assert result.status == ServiceStatus.ERROR
        assert result.error == "Failed to start terminal"

    @pytest.mark.asyncio
    async def test_service_manager_no_adapter(self) -> None:
        """没有 adapter 时应该抛出错误."""
        service = ServiceManagerService(mcp_adapter=None)

        with pytest.raises(RuntimeError, match="MCP adapter not configured"):
            await service.start_desktop("sandbox-123")

    @pytest.mark.asyncio
    async def test_start_desktop_empty_content(self, service: ServiceManagerService, mock_adapter) -> None:
        """空内容响应应该返回 STOPPED 状态."""
        mock_adapter.call_tool.return_value = {
            "content": [],
            "is_error": False,
        }

        result = await service.start_desktop("sandbox-123")

        assert result.running is False
        assert result.status == ServiceStatus.STOPPED

    @pytest.mark.asyncio
    async def test_start_desktop_invalid_json(self, service: ServiceManagerService, mock_adapter) -> None:
        """无效 JSON 响应该返回 ERROR 状态."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": "invalid json {{}"}],
            "is_error": False,
        }

        result = await service.start_desktop("sandbox-123")

        assert result.running is False
        assert result.status == ServiceStatus.ERROR
        assert "Failed to parse result" in result.error

    @pytest.mark.asyncio
    async def test_start_desktop_error_without_content(self, service: ServiceManagerService, mock_adapter) -> None:
        """错误响应但没有内容应该返回 Unknown error."""
        mock_adapter.call_tool.return_value = {
            "content": [],
            "is_error": True,
        }

        result = await service.start_desktop("sandbox-123")

        assert result.running is False
        assert result.status == ServiceStatus.ERROR
        assert result.error == "Unknown error"

    @pytest.mark.asyncio
    async def test_stop_desktop_error_response(self, service: ServiceManagerService, mock_adapter) -> None:
        """stop_desktop 错误响应应该返回 False."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": "Failed to stop"}],
            "is_error": True,
        }

        result = await service.stop_desktop("sandbox-123")

        assert result is False

    @pytest.mark.asyncio
    async def test_stop_desktop_empty_content(self, service: ServiceManagerService, mock_adapter) -> None:
        """stop_desktop 空内容应该返回 False."""
        mock_adapter.call_tool.return_value = {
            "content": [],
            "is_error": False,
        }

        result = await service.stop_desktop("sandbox-123")

        assert result is False

    @pytest.mark.asyncio
    async def test_terminal_empty_content(self, service: ServiceManagerService, mock_adapter) -> None:
        """Terminal 空内容响应应该返回 STOPPED 状态."""
        mock_adapter.call_tool.return_value = {
            "content": [],
            "is_error": False,
        }

        result = await service.start_terminal("sandbox-123")

        assert result.running is False
        assert result.status == ServiceStatus.STOPPED

    @pytest.mark.asyncio
    async def test_terminal_invalid_json(self, service: ServiceManagerService, mock_adapter) -> None:
        """Terminal 无效 JSON 响应该返回 ERROR 状态."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": "broken json"}],
            "is_error": False,
        }

        result = await service.start_terminal("sandbox-123")

        assert result.running is False
        assert result.status == ServiceStatus.ERROR
        assert "Failed to parse result" in result.error

    @pytest.mark.asyncio
    async def test_terminal_error_without_content(self, service: ServiceManagerService, mock_adapter) -> None:
        """Terminal 错误响应但没有内容应该返回 Unknown error."""
        mock_adapter.call_tool.return_value = {
            "content": [],
            "is_error": True,
        }

        result = await service.start_terminal("sandbox-123")

        assert result.running is False
        assert result.status == ServiceStatus.ERROR
        assert result.error == "Unknown error"

    @pytest.mark.asyncio
    async def test_stop_terminal_error_response(self, service: ServiceManagerService, mock_adapter) -> None:
        """stop_terminal 错误响应应该返回 False."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": "Failed to stop"}],
            "is_error": True,
        }

        result = await service.stop_terminal("sandbox-123")

        assert result is False

    @pytest.mark.asyncio
    async def test_stop_terminal_empty_content(self, service: ServiceManagerService, mock_adapter) -> None:
        """stop_terminal 空内容应该返回 False."""
        mock_adapter.call_tool.return_value = {
            "content": [],
            "is_error": False,
        }

        result = await service.stop_terminal("sandbox-123")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_desktop_status_with_xvfb_pid(self, service: ServiceManagerService, mock_adapter) -> None:
        """应该正确解析 xvfb_pid."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"running": true, "xvfb_pid": 12345, "xvnc_pid": 67890, "pid": 99999}'}],
            "is_error": False,
        }

        result = await service.get_desktop_status("sandbox-123")

        # 应该优先使用 xvfb_pid
        assert result.pid == 12345

    @pytest.mark.asyncio
    async def test_get_desktop_status_with_xvnc_pid_only(self, service: ServiceManagerService, mock_adapter) -> None:
        """应该正确解析 xvnc_pid (当没有 xvfb_pid 时)."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"running": true, "xvnc_pid": 67890}'}],
            "is_error": False,
        }

        result = await service.get_desktop_status("sandbox-123")

        assert result.pid == 67890

    @pytest.mark.asyncio
    async def test_get_desktop_status_success_field(self, service: ServiceManagerService, mock_adapter) -> None:
        """应该正确解析 success 字段."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"success": true}'}],
            "is_error": False,
        }

        result = await service.get_desktop_status("sandbox-123")

        assert result.running is True
        assert result.status == ServiceStatus.RUNNING

    @pytest.mark.asyncio
    async def test_restart_desktop_with_config(self, service: ServiceManagerService, mock_adapter) -> None:
        """重启 Desktop 应该使用新配置."""
        config = DesktopConfig(resolution="1920x1080", display=":2", port=7000)
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"success": true, "running": true}'}],
            "is_error": False,
        }

        result = await service.restart_desktop("sandbox-123", config)

        assert result.running is True
        assert mock_adapter.call_tool.call_count == 2

        # 验证 start_desktop 使用了正确的配置
        start_call = mock_adapter.call_tool.call_args_list[1]
        assert start_call[0][1] == "start_desktop"
        assert start_call[0][2]["resolution"] == "1920x1080"
        assert start_call[0][2]["display"] == ":2"

    @pytest.mark.asyncio
    async def test_restart_terminal_with_config(self, service: ServiceManagerService, mock_adapter) -> None:
        """重启 Terminal 应该使用新配置."""
        config = TerminalConfig(port=8000)
        mock_adapter.call_tool.return_value = {
            "content": [{"text": '{"success": true, "running": true}'}],
            "is_error": False,
        }

        result = await service.restart_terminal("sandbox-123", config)

        assert result.running is True
        assert mock_adapter.call_tool.call_count == 2

        # 验证 start_terminal 使用了正确的配置
        start_call = mock_adapter.call_tool.call_args_list[1]
        assert start_call[0][1] == "start_terminal"
        assert start_call[0][2]["port"] == 8000
