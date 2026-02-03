"""Tests for SandboxProfile."""

import pytest

from src.application.services.sandbox_profile import (
    SANDBOX_PROFILES,
    SandboxProfile,
    SandboxProfileType,
    get_default_profile,
    get_profile,
    list_profiles,
    register_profile,
)


class TestSandboxProfile:
    """测试 SandboxProfile 数据类."""

    def test_lite_profile_config(self) -> None:
        """lite 配置应该禁用桌面，低资源占用."""
        profile = SandboxProfile(
            name="Lite",
            description="轻量级 sandbox",
            profile_type=SandboxProfileType.LITE,
            desktop_enabled=False,
            memory_limit="512m",
            cpu_limit="0.5",
            timeout_seconds=1800,
            preinstalled_tools=["python", "node"],
            max_instances=20,
        )

        assert profile.name == "Lite"
        assert profile.desktop_enabled is False
        assert profile.memory_limit == "512m"
        assert profile.cpu_limit == "0.5"
        assert profile.timeout_seconds == 1800
        assert profile.preinstalled_tools == ["python", "node"]
        assert profile.max_instances == 20

    def test_standard_profile_config(self) -> None:
        """standard 配置应该启用桌面，中等资源."""
        profile = SandboxProfile(
            name="Standard",
            description="标准 sandbox",
            profile_type=SandboxProfileType.STANDARD,
            desktop_enabled=True,
            memory_limit="2g",
            cpu_limit="2",
            timeout_seconds=3600,
            preinstalled_tools=["python", "node", "java"],
            max_instances=5,
        )

        assert profile.desktop_enabled is True
        assert profile.memory_limit == "2g"
        assert profile.cpu_limit == "2"
        assert profile.max_instances == 5

    def test_full_profile_config(self) -> None:
        """full 配置应该启用桌面，高资源，所有工具."""
        profile = SandboxProfile(
            name="Full",
            description="完整开发环境",
            profile_type=SandboxProfileType.FULL,
            desktop_enabled=True,
            memory_limit="4g",
            cpu_limit="4",
            timeout_seconds=7200,
            preinstalled_tools=["python", "node", "java", "go", "rust"],
            max_instances=2,
        )

        assert profile.desktop_enabled is True
        assert profile.memory_limit == "4g"
        assert profile.cpu_limit == "4"
        assert profile.max_instances == 2

    def test_to_dict(self) -> None:
        """应该转换为字典."""
        profile = SandboxProfile(
            name="Test",
            description="测试配置",
            profile_type=SandboxProfileType.LITE,
            desktop_enabled=False,
            memory_limit="1g",
            cpu_limit="1",
            timeout_seconds=1800,
            preinstalled_tools=["python"],
            max_instances=10,
        )

        result = profile.to_dict()

        assert result["name"] == "Test"
        assert result["desktop_enabled"] is False
        assert result["memory_limit"] == "1g"
        assert result["preinstalled_tools"] == ["python"]

    def test_get_config(self) -> None:
        """应该返回 Sandbox 创建配置."""
        profile = SandboxProfile(
            name="Test",
            description="测试配置",
            profile_type=SandboxProfileType.LITE,
            desktop_enabled=False,
            memory_limit="1g",
            cpu_limit="1",
            timeout_seconds=1800,
        )

        config = profile.get_config()

        assert config["memory_limit"] == "1g"
        assert config["cpu_limit"] == "1"
        assert config["timeout_seconds"] == 1800


class TestSandboxProfileFunctions:
    """测试 SandboxProfile 函数."""

    def test_get_profile_lite(self) -> None:
        """应该获取 lite 配置."""
        profile = get_profile(SandboxProfileType.LITE)

        assert profile.profile_type == SandboxProfileType.LITE
        assert profile.desktop_enabled is False
        assert profile.memory_limit == "512m"

    def test_get_profile_standard(self) -> None:
        """应该获取 standard 配置."""
        profile = get_profile(SandboxProfileType.STANDARD)

        assert profile.profile_type == SandboxProfileType.STANDARD
        assert profile.desktop_enabled is True
        assert profile.memory_limit == "2g"

    def test_get_profile_full(self) -> None:
        """应该获取 full 配置."""
        profile = get_profile(SandboxProfileType.FULL)

        assert profile.profile_type == SandboxProfileType.FULL
        assert profile.desktop_enabled is True
        assert profile.memory_limit == "4g"

    def test_get_profile_invalid(self) -> None:
        """不存在的配置类型应该抛出 ValueError."""
        # 由于 SandboxProfileType 是 Enum，直接创建无效值会抛出异常
        # 我们测试从字典中删除后的情况
        original = SANDBOX_PROFILES.copy()
        SANDBOX_PROFILES.clear()

        try:
            with pytest.raises(ValueError, match="Unknown profile type"):
                get_profile(SandboxProfileType.LITE)
        finally:
            # 恢复原始配置
            SANDBOX_PROFILES.update(original)

    def test_get_default_profile(self) -> None:
        """默认配置应该是 standard."""
        profile = get_default_profile()

        assert profile.profile_type == SandboxProfileType.STANDARD

    def test_list_profiles(self) -> None:
        """应该列出所有配置."""
        profiles = list_profiles()

        assert len(profiles) == 3
        profile_types = {p.profile_type for p in profiles}
        assert profile_types == {
            SandboxProfileType.LITE,
            SandboxProfileType.STANDARD,
            SandboxProfileType.FULL,
        }

    def test_register_profile(self) -> None:
        """应该能够注册自定义配置."""
        # 使用自定义类型避免污染现有配置

        # 先保存原始配置
        original_lite = SANDBOX_PROFILES.get(SandboxProfileType.LITE)

        custom_profile = SandboxProfile(
            name="Custom",
            description="自定义配置",
            profile_type=SandboxProfileType.LITE,
            desktop_enabled=False,
            memory_limit="256m",
            cpu_limit="0.25",
            timeout_seconds=900,
        )

        register_profile(custom_profile)

        # 验证已注册
        profiles = list_profiles()
        custom_profiles = [p for p in profiles if p.name == "Custom"]
        assert len(custom_profiles) == 1

        # 恢复原始配置
        if original_lite:
            SANDBOX_PROFILES[SandboxProfileType.LITE] = original_lite

    def test_sandbox_profiles_constant(self) -> None:
        """SANDBOX_PROFILES 应该包含所有预定义配置."""
        assert SandboxProfileType.LITE in SANDBOX_PROFILES
        assert SandboxProfileType.STANDARD in SANDBOX_PROFILES
        assert SandboxProfileType.FULL in SANDBOX_PROFILES
