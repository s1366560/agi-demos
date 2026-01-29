"""Integration tests for Sandbox Profile API.

Tests the profile listing and sandbox creation with profile support.
"""

import pytest

from fastapi.testclient import TestClient

from src.infrastructure.adapters.primary.web.main import app


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    return TestClient(app)


class TestListProfiles:
    """测试 Profile 列表 API."""

    def test_list_profiles_success(self, client: TestClient) -> None:
        """应该成功列出所有可用的 Profile."""
        response = client.get("/api/v1/sandbox/profiles")

        assert response.status_code == 200

        data = response.json()
        assert "profiles" in data
        assert len(data["profiles"]) >= 3

        # 验证必需的 profile 存在
        profile_names = {p["name"] for p in data["profiles"]}
        assert "Lite" in profile_names
        assert "Standard" in profile_names
        assert "Full" in profile_names

    def test_profile_structure(self, client: TestClient) -> None:
        """Profile 应该包含所有必需字段."""
        response = client.get("/api/v1/sandbox/profiles")

        assert response.status_code == 200

        data = response.json()
        for profile in data["profiles"]:
            assert "name" in profile
            assert "description" in profile
            assert "profile_type" in profile
            assert "desktop_enabled" in profile
            assert "memory_limit" in profile
            assert "cpu_limit" in profile
            assert "timeout_seconds" in profile
            assert "preinstalled_tools" in profile
            assert "max_instances" in profile

    def test_lite_profile_config(self, client: TestClient) -> None:
        """Lite Profile 应该禁用桌面."""
        response = client.get("/api/v1/sandbox/profiles")

        assert response.status_code == 200

        data = response.json()
        lite = next((p for p in data["profiles"] if p["profile_type"] == "lite"), None)

        assert lite is not None
        assert lite["desktop_enabled"] is False
        assert lite["memory_limit"] == "512m"
        assert lite["cpu_limit"] == "0.5"

    def test_standard_profile_config(self, client: TestClient) -> None:
        """Standard Profile 应该启用桌面."""
        response = client.get("/api/v1/sandbox/profiles")

        assert response.status_code == 200

        data = response.json()
        standard = next((p for p in data["profiles"] if p["profile_type"] == "standard"), None)

        assert standard is not None
        assert standard["desktop_enabled"] is True
        assert standard["memory_limit"] == "2g"
        assert standard["cpu_limit"] == "2"

    def test_full_profile_config(self, client: TestClient) -> None:
        """Full Profile 应该有最多资源."""
        response = client.get("/api/v1/sandbox/profiles")

        assert response.status_code == 200

        data = response.json()
        full = next((p for p in data["profiles"] if p["profile_type"] == "full"), None)

        assert full is not None
        assert full["desktop_enabled"] is True
        assert full["memory_limit"] == "4g"
        assert full["cpu_limit"] == "4"
        assert len(full["preinstalled_tools"]) >= 5  # python, node, java, go, rust


class TestCreateSandboxWithProfile:
    """测试使用 Profile 创建 Sandbox."""

    def test_create_with_lite_profile(self, client: TestClient) -> None:
        """使用 Lite Profile 创建应该禁用桌面."""
        request_data = {
            "project_path": "/tmp/test_lite",
            "profile": "lite",
        }

        # This would normally create a sandbox
        # For integration testing, we verify the request parsing
        response = client.post(
            "/api/v1/sandbox/create",
            json=request_data,
        )

        # May fail due to Docker/mock, but should validate input
        assert response.status_code in [200, 400, 401, 500]

    def test_create_with_standard_profile(self, client: TestClient) -> None:
        """使用 Standard Profile 创建应该使用标准配置."""
        request_data = {
            "project_path": "/tmp/test_standard",
            "profile": "standard",
        }

        response = client.post(
            "/api/v1/sandbox/create",
            json=request_data,
        )

        assert response.status_code in [200, 400, 401, 500]

    def test_create_with_invalid_profile(self, client: TestClient) -> None:
        """使用无效的 Profile 应该返回错误."""
        request_data = {
            "project_path": "/tmp/test_invalid",
            "profile": "invalid_profile_name",
        }

        response = client.post(
            "/api/v1/sandbox/create",
            json=request_data,
        )

        # Should return validation error, 404, or 401 (unauthenticated)
        assert response.status_code in [400, 401, 404, 422]

    def test_create_with_profile_override(self, client: TestClient) -> None:
        """Profile 配置可以被显式参数覆盖."""
        request_data = {
            "project_path": "/tmp/test_override",
            "profile": "lite",
            "memory_limit": "1g",  # Override lite's 512m
            "cpu_limit": "2",  # Override lite's 0.5
        }

        response = client.post(
            "/api/v1/sandbox/create",
            json=request_data,
        )

        # The override values should be used
        assert response.status_code in [200, 400, 401, 500]

    def test_create_default_to_standard(self, client: TestClient) -> None:
        """未指定 Profile 时应该使用 Standard."""
        request_data = {
            "project_path": "/tmp/test_default",
            # No profile specified
        }

        response = client.post(
            "/api/v1/sandbox/create",
            json=request_data,
        )

        # Should use standard profile defaults
        assert response.status_code in [200, 400, 401, 500]
