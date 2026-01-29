"""Tests for Sudo configuration."""

import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from server.sudo_config import (
    ALLOWED_COMMANDS,
    DANGEROUS_COMMANDS,
    SudoConfigValidator,
    SudoRule,
    SudoRuleType,
    is_dangerous_command,
    validate_sudo_command,
)


class TestDANGEROUS_COMMANDS:
    """测试危险命令列表."""

    def test_system_modification_commands(self) -> None:
        """应该包含系统修改命令."""
        assert "su" in DANGEROUS_COMMANDS.SYSTEM_MODIFICATION
        assert "usermod" in DANGEROUS_COMMANDS.SYSTEM_MODIFICATION
        assert "passwd" in DANGEROUS_COMMANDS.SYSTEM_MODIFICATION

    def test_data_destruction_commands(self) -> None:
        """应该包含数据销毁命令."""
        assert "rm -rf /" in DANGEROUS_COMMANDS.DATA_DESTRUCTION
        assert "dd if=/dev/zero" in DANGEROUS_COMMANDS.DATA_DESTRUCTION
        assert "mkfs" in DANGEROUS_COMMANDS.DATA_DESTRUCTION

    def test_network_control_commands(self) -> None:
        """应该包含网络控制命令."""
        assert "iptables" in DANGEROUS_COMMANDS.NETWORK_CONTROL
        assert "tcpdump" in DANGEROUS_COMMANDS.NETWORK_CONTROL

    def test_all_contains_all_dangerous(self) -> None:
        """all() 应该包含所有危险命令."""
        all_dangerous = DANGEROUS_COMMANDS.all()

        assert "su" in all_dangerous
        assert "rm -rf /" in all_dangerous
        assert "iptables" in all_dangerous


class TestALLOWED_COMMANDS:
    """测试允许的命令列表."""

    def test_package_management_commands(self) -> None:
        """应该包含包管理命令."""
        assert "/usr/bin/apt-get" in ALLOWED_COMMANDS.PACKAGE_MANAGEMENT
        assert "/usr/bin/pip" in ALLOWED_COMMANDS.PACKAGE_MANAGEMENT
        assert "/usr/bin/pip3" in ALLOWED_COMMANDS.PACKAGE_MANAGEMENT

    def test_file_operations(self) -> None:
        """应该包含文件操作命令."""
        assert "/bin/chmod -R g+rw /workspace/*" in ALLOWED_COMMANDS.FILE_OPERATIONS
        assert "/bin/chown -R sandbox:sandbox /workspace/*" in ALLOWED_COMMANDS.FILE_OPERATIONS

    def test_all_contains_all_allowed(self) -> None:
        """all() 应该包含所有允许的命令."""
        all_allowed = ALLOWED_COMMANDS.all()

        assert "/usr/bin/apt-get" in all_allowed
        # FILE_OPERATIONS 包含完整命令路径
        assert "/bin/chmod" in str(all_allowed)  # 检查包含 chmod 命令


class TestSudoRule:
    """测试 SudoRule."""

    def test_to_sudoers_line_allow(self) -> None:
        """应该生成允许规则的 sudoers 行."""
        rule = SudoRule(
            command="/usr/bin/apt-get",
            rule_type=SudoRuleType.ALLOW,
            reason="Allow package management",
        )

        line = rule.to_sudoers_line("sandbox")

        assert line == "sandbox ALL=(ALL) NOPASSWD: /usr/bin/apt-get"

    def test_to_sudoers_line_deny(self) -> None:
        """应该生成拒绝规则的 sudoers 行."""
        rule = SudoRule(
            command="su",
            rule_type=SudoRuleType.DENY,
            reason="Prevent user switching",
        )

        line = rule.to_sudoers_line("sandbox")

        assert line == "sandbox ALL=(ALL) !su"


class TestSudoConfigValidator:
    """测试 SudoConfigValidator."""

    @pytest.fixture
    def validator(self) -> SudoConfigValidator:
        """创建验证器实例."""
        return SudoConfigValidator()

    def test_validate_dangerous_command(self, validator: SudoConfigValidator) -> None:
        """危险命令应该被拒绝."""
        assert validator.validate_command("sudo su") is False
        assert validator.validate_command("sudo usermod test") is False
        assert validator.validate_command("sudo rm -rf /") is False

    def test_validate_allowed_command(self, validator: SudoConfigValidator) -> None:
        """允许的命令应该通过验证."""
        assert validator.validate_command("sudo /usr/bin/apt-get update") is True
        assert validator.validate_command("sudo /usr/bin/pip install requests") is True

    def test_validate_unknown_command_deny(self, validator: SudoConfigValidator) -> None:
        """未知命令应该被拒绝（默认拒绝）."""
        assert validator.validate_command("sudo unknown-command") is False

    def test_is_dangerous(self, validator: SudoConfigValidator) -> None:
        """应该正确识别危险命令."""
        assert validator.is_dangerous("sudo su root") is True
        assert validator.is_dangerous("sudo iptables -L") is True
        assert validator.is_dangerous("sudo dd if=/dev/zero of=/dev/sda") is True

    def test_is_dangerous_safe_command(self, validator: SudoConfigValidator) -> None:
        """安全命令不应该被标记为危险."""
        assert validator.is_dangerous("sudo /usr/bin/apt-get install git") is False
        assert validator.is_dangerous("sudo /bin/chmod +x /workspace/script.sh") is False

    def test_case_insensitive_dangerous(self, validator: SudoConfigValidator) -> None:
        """危险命令检查应该不区分大小写."""
        assert validator.is_dangerous("sudo SU root") is True
        assert validator.is_dangerous("sudo UserMod test") is True

    def test_generate_sudoers(self, validator: SudoConfigValidator) -> None:
        """应该生成有效的 sudoers 文件内容."""
        sudoers = validator.generate_sudoers("sandbox")

        # 检查头部
        assert "# Sudoers configuration" in sudoers

        # 检查 Defaults
        assert "Defaults !lecture" in sudoers
        assert "Defaults secure_path" in sudoers

        # 检查允许的命令
        assert "NOPASSWD: /usr/bin/apt-get" in sudoers
        assert "NOPASSWD: /usr/bin/pip" in sudoers

        # 检查拒绝的命令
        assert "!su" in sudoers
        assert "!passwd" in sudoers
        assert "!rm -rf /" in sudoers

    def test_add_allowed_command(self, validator: SudoConfigValidator) -> None:
        """应该能够添加允许的命令."""
        validator.add_allowed_command("/usr/bin/git", "Allow git operations")

        assert validator.validate_command("sudo /usr/bin/git status") is True

    def test_add_denied_command(self, validator: SudoConfigValidator) -> None:
        """应该能够添加拒绝的命令."""
        validator.add_denied_command("nc", "Block netcat")

        assert validator.is_dangerous("sudo nc -l 8080") is True

    def test_validate_sudoers_file_missing(self, validator: SudoConfigValidator, tmp_path: Path) -> None:
        """不存在的文件应该返回 False."""
        is_valid, issues = validator.validate_sudoers_file(tmp_path / "nonexistent")

        assert is_valid is False
        assert "does not exist" in issues[0]

    def test_validate_sudoers_file_content(self, validator: SudoConfigValidator, tmp_path: Path) -> None:
        """应该验证 sudoers 文件内容."""
        # 创建一个安全的 sudoers 文件 - 包含所有必要的拒绝规则
        safe_sudoers = tmp_path / "safe_sudoers"
        safe_sudoers.write_text("""
# Sudoers for sandbox
sandbox ALL=(ALL) NOPASSWD: /usr/bin/apt-get, /usr/bin/pip
# Explicitly deny dangerous commands
sandbox ALL=(ALL) !su, !su -, !passwd, !chsh, !chfn
sandbox ALL=(ALL) !gpasswd, !newgrp, !visudo, !usermod, !userdel
sandbox ALL=(ALL) !adduser, !useradd, !groupmod, !groupdel
""")

        is_valid, issues = validator.validate_sudoers_file(safe_sudoers)

        assert is_valid is True
        assert len(issues) == 0

    def test_validate_sudoers_file_dangerous_allowed(self, validator: SudoConfigValidator, tmp_path: Path) -> None:
        """应该检测到允许的危险命令."""
        # 创建一个不安全的 sudoers 文件
        unsafe_sudoers = tmp_path / "unsafe_sudoers"
        unsafe_sudoers.write_text("""
sandbox ALL=(ALL) NOPASSWD: /bin/su
sandbox ALL=(ALL) NOPASSWD: /usr/bin/passwd
""")

        is_valid, issues = validator.validate_sudoers_file(unsafe_sudoers)

        assert is_valid is False
        assert len(issues) > 0
        assert any("su" in issue for issue in issues)


class TestSudoHelperFunctions:
    """测试 sudo 配置辅助函数."""

    def test_validate_sudo_command(self) -> None:
        """应该正确验证 sudo 命令."""
        assert validate_sudo_command("sudo /usr/bin/apt-get install git") is True
        assert validate_sudo_command("sudo su root") is False

    def test_is_dangerous_command(self) -> None:
        """应该正确识别危险命令."""
        assert is_dangerous_command("sudo iptables -L") is True
        assert is_dangerous_command("sudo /usr/bin/pip list") is False

    def test_is_dangerous_command_case_insensitive(self) -> None:
        """应该不区分大小写."""
        assert is_dangerous_command("sudo IPTABLES -L") is True
        assert is_dangerous_command("sudo UserMod test") is True
