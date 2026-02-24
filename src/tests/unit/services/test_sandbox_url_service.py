"""Tests for SandboxUrlService."""

import pytest

from src.application.services.sandbox_url_service import (
    SandboxInstanceInfo,
    SandboxUrlService,
)


class TestSandboxUrlService:
    """测试 SandboxUrlService."""

    @pytest.fixture
    def service(self) -> SandboxUrlService:
        """创建 URL 服务实例."""
        return SandboxUrlService(default_host="localhost", api_base="/api/v1")

    @pytest.fixture
    def full_instance(self) -> SandboxInstanceInfo:
        """创建完整配置的 Sandbox 实例."""
        return SandboxInstanceInfo(
            mcp_port=18765,
            desktop_port=16080,
            terminal_port=17681,
            sandbox_id="mcp-sandbox-abc123",
            host="localhost",
        )

    @pytest.fixture
    def minimal_instance(self) -> SandboxInstanceInfo:
        """创建最小配置的 Sandbox 实例."""
        return SandboxInstanceInfo(
            sandbox_id="mcp-sandbox-xyz789",
            host="localhost",
        )

    def test_build_mcp_url_with_port(
        self, service: SandboxUrlService, full_instance: SandboxInstanceInfo
    ) -> None:
        """应该构建带端口的 MCP WebSocket URL."""
        url = service.build_mcp_url(full_instance)

        assert url == "ws://localhost:18765"

    def test_build_mcp_url_without_port(
        self, service: SandboxUrlService, minimal_instance: SandboxInstanceInfo
    ) -> None:
        """当没有 MCP 端口时，应该返回 None."""
        url = service.build_mcp_url(minimal_instance)

        assert url is None

    def test_build_desktop_url_with_port(
        self, service: SandboxUrlService, full_instance: SandboxInstanceInfo
    ) -> None:
        """应该构建带端口的 Desktop URL."""
        url = service.build_desktop_url(full_instance)

        assert url == "https://localhost:16080"

    def test_build_desktop_url_with_token(
        self, service: SandboxUrlService, full_instance: SandboxInstanceInfo
    ) -> None:
        """应该构建带 token 的 Desktop URL."""
        url = service.build_desktop_url(full_instance, token="abc123token")

        assert url == "https://localhost:16080?token=abc123token"

    def test_build_desktop_url_without_port(
        self, service: SandboxUrlService, minimal_instance: SandboxInstanceInfo
    ) -> None:
        """当没有 Desktop 端口时，应该返回 None."""
        url = service.build_desktop_url(minimal_instance)

        assert url is None

    def test_build_terminal_url_with_port(
        self, service: SandboxUrlService, full_instance: SandboxInstanceInfo
    ) -> None:
        """应该构建带端口的 Terminal WebSocket URL."""
        url = service.build_terminal_url(full_instance)

        assert url == "ws://localhost:17681"

    def test_build_terminal_url_without_port(
        self, service: SandboxUrlService, minimal_instance: SandboxInstanceInfo
    ) -> None:
        """当没有 Terminal 端口时，应该返回 None."""
        url = service.build_terminal_url(minimal_instance)

        assert url is None

    def test_build_sse_url(self, service: SandboxUrlService) -> None:
        """应该构建 SSE 事件流 URL."""
        url = service.build_sse_url("project-123")

        assert url == "/api/v1/sandbox/events/project-123"

    def test_build_sse_url_with_last_id(self, service: SandboxUrlService) -> None:
        """应该构建带 last_id 的 SSE 事件流 URL."""
        url = service.build_sse_url("project-123", last_id="1234567890-0")

        assert url == "/api/v1/sandbox/events/project-123?last_id=1234567890-0"

    def test_build_all_urls(
        self, service: SandboxUrlService, full_instance: SandboxInstanceInfo
    ) -> None:
        """应该构建所有 URL."""
        urls = service.build_all_urls(full_instance, project_id="project-123")

        assert urls.mcp_url == "ws://localhost:18765"
        assert urls.desktop_url == "https://localhost:16080"
        assert urls.desktop_url_with_token == "https://localhost:16080"
        assert urls.terminal_url == "ws://localhost:17681"
        assert urls.sse_url == "/api/v1/sandbox/events/project-123"

    def test_build_all_urls_with_token(
        self, service: SandboxUrlService, full_instance: SandboxInstanceInfo
    ) -> None:
        """应该构建带 token 的所有 URL."""
        urls = service.build_all_urls(full_instance, project_id="project-123", token="secret-token")

        assert urls.desktop_url_with_token == "https://localhost:16080?token=secret-token"

    def test_build_all_urls_minimal(
        self, service: SandboxUrlService, minimal_instance: SandboxInstanceInfo
    ) -> None:
        """应该处理最小配置的实例."""
        urls = service.build_all_urls(minimal_instance, project_id="project-456")

        assert urls.mcp_url is None
        assert urls.desktop_url is None
        assert urls.terminal_url is None
        assert urls.sse_url == "/api/v1/sandbox/events/project-456"

    def test_custom_host(self) -> None:
        """应该使用自定义主机名."""
        service = SandboxUrlService(default_host="sandbox.example.com", api_base="/api/v1")
        instance = SandboxInstanceInfo(
            mcp_port=18765,
            sandbox_id="test-abc",
            host="sandbox.example.com",
        )

        url = service.build_mcp_url(instance)

        assert url == "ws://sandbox.example.com:18765"

    def test_custom_api_base(self) -> None:
        """应该使用自定义 API 基础路径."""
        service = SandboxUrlService(default_host="localhost", api_base="/api/v2")

        url = service.build_sse_url("project-123")

        assert url == "/api/v2/sandbox/events/project-123"
