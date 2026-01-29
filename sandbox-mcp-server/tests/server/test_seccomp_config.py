"""Tests for Seccomp configuration."""

import json
import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from server.seccomp_config import (
    SeccompAction,
    SeccompProfile,
    SyscallRule,
    get_seccomp_profile_path,
    load_seccomp_profile,
)


class TestSeccompAction:
    """测试 SeccompAction 枚举."""

    def test_allow_value(self) -> None:
        """应该有正确的 ALLOW 值."""
        assert SeccompAction.ALLOW.value == "SCMP_ACT_ALLOW"

    def test_errno_value(self) -> None:
        """应该有正确的 ERRNO 值."""
        assert SeccompAction.ERRNO.value == "SCMP_ACT_ERRNO"


class TestSyscallRule:
    """测试 SyscallRule."""

    def test_to_dict(self) -> None:
        """应该转换为字典."""
        rule = SyscallRule(
            names=["read", "write"],
            action=SeccompAction.ALLOW,
        )

        result = rule.to_dict()

        assert result["names"] == ["read", "write"]
        assert result["action"] == "SCMP_ACT_ALLOW"
        assert "args" in result
        assert result["args"] == []


class TestSeccompProfile:
    """测试 SeccompProfile."""

    @pytest.fixture
    def profile_manager(self) -> SeccompProfile:
        """创建 SeccompProfile 实例."""
        return SeccompProfile()

    def test_get_default_profile(self, profile_manager: SeccompProfile) -> None:
        """应该获取默认 profile."""
        profile = profile_manager.get_profile("default")

        assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
        assert "syscalls" in profile
        assert len(profile["syscalls"]) > 0

    def test_default_profile_blocks_dangerous_syscalls(self, profile_manager: SeccompProfile) -> None:
        """默认 profile 应该阻止危险的系统调用."""
        profile = profile_manager.get_profile("default")

        # 检查被阻止的系统调用
        blocked_syscalls = set()
        for syscall in profile["syscalls"]:
            if syscall["action"] == "SCMP_ACT_ERRNO":
                blocked_syscalls.update(syscall["names"])

        # 应该包含 kexec_load (系统管理)
        assert "kexec_load" in blocked_syscalls
        # 应该包含 ptrace (进程跟踪)
        assert "ptrace" in blocked_syscalls
        # 应该包含 reboot (重启)
        assert "reboot" in blocked_syscalls

    def test_get_strict_profile(self, profile_manager: SeccompProfile) -> None:
        """应该获取严格 profile."""
        profile = profile_manager.get_profile("strict")

        assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
        assert "syscalls" in profile

    def test_strict_profile_blocks_more_syscalls(self, profile_manager: SeccompProfile) -> None:
        """严格 profile 应该阻止更多系统调用."""
        default_profile = profile_manager.get_profile("default")
        strict_profile = profile_manager.get_profile("strict")

        # 收集被阻止的系统调用
        default_blocked = set()
        strict_blocked = set()

        for syscall in default_profile["syscalls"]:
            if syscall["action"] == "SCMP_ACT_ERRNO":
                default_blocked.update(syscall["names"])

        for syscall in strict_profile["syscalls"]:
            if syscall["action"] == "SCMP_ACT_ERRNO":
                strict_blocked.update(syscall["names"])

        # Strict 应该至少包含 default 的所有限制
        assert default_blocked.issubset(strict_blocked)

    def test_get_minimal_profile(self, profile_manager: SeccompProfile) -> None:
        """应该获取最小 profile."""
        profile = profile_manager.get_profile("minimal")

        assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
        assert "syscalls" in profile

    def test_minimal_profile_whitelist_mode(self, profile_manager: SeccompProfile) -> None:
        """最小 profile 应该使用白名单模式."""
        profile = profile_manager.get_profile("minimal")

        # 找到允许的系统调用
        allowed_syscalls = set()
        for syscall in profile["syscalls"]:
            if syscall["action"] == "SCMP_ACT_ALLOW":
                allowed_syscalls.update(syscall["names"])

        # 应该包含基本的 I/O 系统调用
        assert "read" in allowed_syscalls
        assert "write" in allowed_syscalls
        assert "open" in allowed_syscalls
        assert "close" in allowed_syscalls

        # 应该包含基本的进程系统调用
        assert "clone" in allowed_syscalls or "fork" in allowed_syscalls
        assert "execve" in allowed_syscalls
        assert "exit" in allowed_syscalls

    def test_profile_caching(self, profile_manager: SeccompProfile) -> None:
        """Profile 应该被缓存."""
        profile1 = profile_manager.get_profile("default")
        profile2 = profile_manager.get_profile("default")

        # 应该返回同一个对象
        assert profile1 is profile2

    def test_save_profile(self, profile_manager: SeccompProfile, tmp_path: Path) -> None:
        """应该能够保存 profile."""
        custom_profile = {
            "defaultAction": "SCMP_ACT_ERRNO",
            "architectures": ["SCMP_ARCH_X86_64"],
            "syscalls": [
                {
                    "names": ["read", "write"],
                    "action": "SCMP_ACT_ALLOW",
                    "args": [],
                }
            ],
        }

        profile_manager.save_profile("custom", custom_profile, path=tmp_path / "custom.json")

        # 验证文件存在
        assert (tmp_path / "custom.json").exists()

        # 验证内容
        with open(tmp_path / "custom.json") as f:
            saved = json.load(f)

        assert saved["defaultAction"] == "SCMP_ACT_ERRNO"
        assert len(saved["syscalls"]) == 1

    def test_get_nonexistent_profile_raises(self, profile_manager: SeccompProfile) -> None:
        """不存在的 profile 应该抛出异常."""
        with pytest.raises(FileNotFoundError):
            profile_manager.get_profile("nonexistent")

    def test_profile_has_architectures(self, profile_manager: SeccompProfile) -> None:
        """Profile 应该包含架构信息."""
        profile = profile_manager.get_profile("default")

        assert "architectures" in profile
        assert len(profile["architectures"]) > 0

        # 应该包含 x86_64
        assert "SCMP_ARCH_X86_64" in profile["architectures"]


class TestSeccompHelpers:
    """测试 seccomp 辅助函数."""

    def test_load_seccomp_profile(self) -> None:
        """应该能够加载 profile."""
        profile = load_seccomp_profile("default")

        assert profile is not None
        assert "defaultAction" in profile

    def test_get_seccomp_profile_path(self) -> None:
        """应该能够获取 profile 路径."""
        # 检查 docker 目录下的 profile
        path = get_seccomp_profile_path("seccomp-profile")

        # 如果文件存在，应该返回路径
        if path:
            assert Path(path).exists()

    def test_load_seccomp_profile_nonexistent(self) -> None:
        """加载不存在的 profile 应该抛出异常."""
        # 需要使用新的 manager 实例，请求不存在的内置 profile
        from server.seccomp_config import SeccompProfile

        manager = SeccompProfile()
        manager._profile_dir = Path("/nonexistent")

        # "nonexistent" 不是内置 profile，目录也不存在
        with pytest.raises(FileNotFoundError):
            manager.get_profile("nonexistent")
