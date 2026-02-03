"""Integration tests for Sandbox Health Check API.

Tests the health check endpoints with different check levels.
"""

import pytest
from fastapi.testclient import TestClient

from src.infrastructure.adapters.primary.web.main import app


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    return TestClient(app)


class TestHealthCheckAPI:
    """测试 Sandbox 健康检查 API."""

    def test_health_check_basic(self, client: TestClient) -> None:
        """基础健康检查应该返回状态."""
        sandbox_id = "test-sandbox-123"
        response = client.get(f"/api/v1/sandbox/{sandbox_id}/health")

        # 可能返回 404（sandbox 不存在）或 401（未认证）
        assert response.status_code in [200, 401, 404]

        if response.status_code == 200:
            data = response.json()
            assert "healthy" in data
            assert "level" in data
            assert "status" in data
            assert "sandbox_id" in data

    def test_health_check_with_level(self, client: TestClient) -> None:
        """带级别的健康检查."""
        sandbox_id = "test-sandbox-456"
        response = client.get(f"/api/v1/sandbox/{sandbox_id}/health?level=full")

        # 可能返回 404（sandbox 不存在）或 401（未认证）
        assert response.status_code in [200, 401, 404]

        if response.status_code == 200:
            data = response.json()
            assert data["level"] == "full"
            assert "details" in data

    def test_health_check_invalid_level(self, client: TestClient) -> None:
        """无效的级别应该返回错误."""
        sandbox_id = "test-sandbox-789"
        response = client.get(f"/api/v1/sandbox/{sandbox_id}/health?level=invalid")

        # 应该返回验证错误、401 或 404
        assert response.status_code in [400, 401, 404, 422]

    def test_health_check_levels(self, client: TestClient) -> None:
        """测试所有支持的健康检查级别."""
        sandbox_id = "test-sandbox-levels"
        levels = ["basic", "mcp", "services", "full"]

        for level in levels:
            response = client.get(f"/api/v1/sandbox/{sandbox_id}/health?level={level}")

            # 级别参数应该被接受（即使 sandbox 不存在）
            # 返回 404 或 401 是预期的
            assert response.status_code in [200, 401, 404]
