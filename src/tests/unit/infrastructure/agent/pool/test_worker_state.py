"""
Agent Worker State Pool Integration Tests.

测试 agent_worker_state.py 中的池适配器相关功能。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


class TestPoolAdapterState:
    """测试池适配器状态管理."""

    def test_set_and_get_pool_adapter(self):
        """测试设置和获取池适配器."""
        from src.infrastructure.agent.state import agent_worker_state

        # 清理状态
        agent_worker_state._pool_adapter = None

        # 创建 mock 适配器
        mock_adapter = MagicMock()
        mock_adapter._running = True

        # 设置
        agent_worker_state.set_pool_adapter(mock_adapter)

        # 获取
        adapter = agent_worker_state.get_pool_adapter()
        assert adapter is mock_adapter

    def test_is_pool_enabled_true(self):
        """测试池启用检查 - 已启用."""
        from src.infrastructure.agent.state import agent_worker_state

        mock_adapter = MagicMock()
        mock_adapter._running = True
        agent_worker_state._pool_adapter = mock_adapter

        assert agent_worker_state.is_pool_enabled() is True

    def test_is_pool_enabled_false_not_running(self):
        """测试池启用检查 - 未运行."""
        from src.infrastructure.agent.state import agent_worker_state

        mock_adapter = MagicMock()
        mock_adapter._running = False
        agent_worker_state._pool_adapter = mock_adapter

        assert agent_worker_state.is_pool_enabled() is False

    def test_is_pool_enabled_false_no_adapter(self):
        """测试池启用检查 - 无适配器."""
        from src.infrastructure.agent.state import agent_worker_state

        agent_worker_state._pool_adapter = None

        assert agent_worker_state.is_pool_enabled() is False

    def teardown_method(self):
        """测试后清理."""
        from src.infrastructure.agent.state import agent_worker_state

        agent_worker_state._pool_adapter = None
