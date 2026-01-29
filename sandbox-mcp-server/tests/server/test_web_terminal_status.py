"""Tests for Web Terminal Status (simplified, no start/stop)."""

import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from server.web_terminal_status import (
    TerminalStatus,
    WebTerminalStatus,
    WebTerminalManager,  # Backward compatibility alias
)


class TestTerminalStatus:
    """测试 TerminalStatus 数据类."""

    def test_to_dict(self) -> None:
        """应该转换为字典."""
        status = TerminalStatus(
            running=True,
            port=7681,
            pid=12345,
            url="ws://localhost:7681",
            session_id="term-abc",
        )

        result = status.to_dict()

        assert result["running"] is True
        assert result["port"] == 7681
        assert result["pid"] == 12345
        assert result["url"] == "ws://localhost:7681"
        assert result["session_id"] == "term-abc"

    def test_to_dict_minimal(self) -> None:
        """应该处理最小状态."""
        status = TerminalStatus(
            running=False,
            port=7681,
        )

        result = status.to_dict()

        assert result["running"] is False
        assert result["pid"] is None
        assert result["url"] is None


class TestWebTerminalStatus:
    """测试 WebTerminalStatus."""

    @pytest.fixture
    def status(self) -> WebTerminalStatus:
        """创建状态检查器实例."""
        return WebTerminalStatus()

    def test_default_port(self, status: WebTerminalStatus) -> None:
        """应该使用默认端口."""
        assert status.port == 7681
        assert status.host == "localhost"

    def test_custom_port(self) -> None:
        """应该支持自定义端口."""
        status = WebTerminalStatus(port=8080, host="0.0.0.0")

        assert status.port == 8080
        assert status.host == "0.0.0.0"

    def test_get_port(self, status: WebTerminalStatus) -> None:
        """应该返回端口."""
        assert status.get_port() == 7681

    def test_get_status(self, status: WebTerminalStatus) -> None:
        """应该获取状态对象."""
        terminal_status = status.get_status()

        assert isinstance(terminal_status, TerminalStatus)
        assert terminal_status.port == 7681

    def test_get_status_not_running(self, status: WebTerminalStatus) -> None:
        """未运行时状态应该正确."""
        terminal_status = status.get_status()

        # 在测试环境中 ttyd 可能不在运行
        assert terminal_status.port == 7681
        assert isinstance(terminal_status.running, bool)

    def test_get_websocket_url_not_running(self, status: WebTerminalStatus) -> None:
        """未运行时 WebSocket URL 应该为 None."""
        # 假设测试环境中没有运行 ttyd
        if not status.is_running():
            url = status.get_websocket_url()
            assert url is None

    def test_is_running_bool(self, status: WebTerminalStatus) -> None:
        """is_running 应该返回布尔值."""
        result = status.is_running()

        assert isinstance(result, bool)


class TestWebTerminalManagerAlias:
    """测试向后兼容别名."""

    def test_web_terminal_manager_is_alias(self) -> None:
        """WebTerminalManager 应该是 WebTerminalStatus 的别名."""
        assert WebTerminalManager is WebTerminalStatus

    def test_can_instantiate_manager(self) -> None:
        """应该能使用旧名称创建实例."""
        from server.web_terminal_status import WebTerminalManager

        manager = WebTerminalManager(port=7681)
        assert manager.port == 7681


class TestWebTerminalHealthCheck:
    """测试健康检查功能."""

    @pytest.fixture
    def status(self) -> WebTerminalStatus:
        """创建状态检查器实例."""
        return WebTerminalStatus()

    @pytest.mark.asyncio
    async def test_health_check_when_not_running(self, status: WebTerminalStatus) -> None:
        """未运行时健康检查应该返回 False."""
        if not status.is_running():
            result = await status.health_check()
            assert result is False
        else:
            # 如果 ttyd 正在运行，跳过此测试
            pytest.skip("ttyd is running, cannot test not-running case")

    @pytest.mark.asyncio
    async def test_health_check_when_running(self, status: WebTerminalStatus) -> None:
        """运行时健康检查应该返回 True."""
        if status.is_running():
            result = await status.health_check()
            assert result is True
        else:
            # 如果 ttyd 未运行，跳过此测试
            pytest.skip("ttyd is not running, cannot test running case")
