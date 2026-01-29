"""Tests for VNC Authentication."""

import sys
import time
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from server.vnc_auth import (
    AuthToken,
    VNCTokenManager,
)


class TestAuthToken:
    """测试 AuthToken 数据类."""

    def test_is_valid_when_fresh(self) -> None:
        """新创建的 token 应该有效."""
        token = AuthToken(
            token="test-token",
            expires_at=time.time() + 3600,
            workspace_dir="/workspace",
        )

        assert token.is_valid() is True

    def test_is_valid_when_expired(self) -> None:
        """过期的 token 应该无效."""
        token = AuthToken(
            token="test-token",
            expires_at=time.time() - 100,
            workspace_dir="/workspace",
        )

        assert token.is_valid() is False

    def test_to_dict(self) -> None:
        """应该转换为字典."""
        token = AuthToken(
            token="test-token",
            expires_at=1234567890.0,
            workspace_dir="/workspace",
        )

        result = token.to_dict()

        assert result["token"] == "test-token"
        assert result["expires_at"] == 1234567890.0
        assert result["workspace_dir"] == "/workspace"


class TestVNCTokenManager:
    """测试 VNCTokenManager."""

    @pytest.fixture
    def manager(self) -> VNCTokenManager:
        """创建 token 管理器实例."""
        return VNCTokenManager(secret_key="test-secret")

    def test_generate_token(self, manager: VNCTokenManager) -> None:
        """应该生成有效的 token."""
        token = manager.generate_token("/workspace")

        assert isinstance(token, AuthToken)
        assert len(token.token) > 0
        assert token.workspace_dir == "/workspace"
        assert token.is_valid() is True

    def test_generate_token_different_workspaces(self, manager: VNCTokenManager) -> None:
        """不同 workspace 应该生成不同的 token."""
        token1 = manager.generate_token("/workspace1")
        token2 = manager.generate_token("/workspace2")

        assert token1.token != token2.token
        assert token1.workspace_dir == "/workspace1"
        assert token2.workspace_dir == "/workspace2"

    def test_validate_token_valid(self, manager: VNCTokenManager) -> None:
        """应该验证有效的 token."""
        token = manager.generate_token("/workspace")

        is_valid = manager.validate_token(token.token, "/workspace")

        assert is_valid is True

    def test_validate_token_wrong_workspace(self, manager: VNCTokenManager) -> None:
        """不同 workspace 的 token 应该无效."""
        token = manager.generate_token("/workspace1")

        is_valid = manager.validate_token(token.token, "/workspace2")

        assert is_valid is False

    def test_validate_token_invalid_format(self, manager: VNCTokenManager) -> None:
        """错误格式的 token 应该无效."""
        is_valid = manager.validate_token("invalid-token", "/workspace")

        assert is_valid is False

    def test_validate_token_expired(self, manager: VNCTokenManager) -> None:
        """过期的 token 应该无效."""
        # 创建一个 TTL 为 0 的 manager
        short_manager = VNCTokenManager(
            secret_key="test-secret",
            token_ttl_seconds=0,
        )
        token = short_manager.generate_token("/workspace")

        # 等待 token 过期
        time.sleep(0.1)

        is_valid = short_manager.validate_token(token.token, "/workspace")

        assert is_valid is False

    def test_validate_token_wrong_secret(self) -> None:
        """不同 secret 的 token 应该无效."""
        manager1 = VNCTokenManager(secret_key="secret1")
        manager2 = VNCTokenManager(secret_key="secret2")

        token = manager1.generate_token("/workspace")

        is_valid = manager2.validate_token(token.token, "/workspace")

        assert is_valid is False

    def test_parse_token(self, manager: VNCTokenManager) -> None:
        """应该解析 token."""
        token = manager.generate_token("/workspace")

        parsed = manager.parse_token(token.token)

        assert parsed is not None
        assert parsed.workspace_dir == "/workspace"
        assert parsed.token == token.token

    def test_parse_token_invalid_format(self, manager: VNCTokenManager) -> None:
        """错误格式的 token 应该返回 None."""
        parsed = manager.parse_token("invalid-token")

        assert parsed is None

    def test_revoke_token(self, manager: VNCTokenManager) -> None:
        """应该能够撤销 token."""
        token = manager.generate_token("/workspace")

        result = manager.revoke_token(token.token)

        assert result is True

        # 被撤销的 token 应该无效
        is_valid = manager.validate_token(token.token, "/workspace")
        assert is_valid is False

    def test_revoke_nonexistent_token(self, manager: VNCTokenManager) -> None:
        """撤销不存在的 token 应该返回 False."""
        result = manager.revoke_token("nonexistent-token")

        assert result is False

    def test_token_format_consistent(self, manager: VNCTokenManager) -> None:
        """Token 格式应该一致."""
        token = manager.generate_token("/workspace")

        # Token 应该包含三部分，用冒号分隔
        parts = token.token.split(":")
        assert len(parts) == 3

        # 第一部分应该是 HMAC（hex，64 字符）
        assert len(parts[0]) == 64

        # 第二部分应该是时间戳
        expires_at = float(parts[1])
        assert expires_at > time.time()

        # 第三部分应该是 workspace
        assert parts[2] == "/workspace"
