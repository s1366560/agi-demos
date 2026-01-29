"""Sudo configuration validator and manager for sandbox security.

Validates and manages sudoers configuration to restrict elevated privileges.
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Set

logger = logging.getLogger(__name__)


class SudoRuleType(str, Enum):
    """Types of sudo rules."""
    ALLOW = "allow"
    DENY = "deny"


@dataclass
class SudoRule:
    """A single sudo permission rule.

    Attributes:
        command: The command pattern
        rule_type: Whether this is an allow or deny rule
        reason: Human-readable reason for the rule
    """
    command: str
    rule_type: SudoRuleType
    reason: str

    def to_sudoers_line(self, user: str = "sandbox") -> str:
        """Convert to sudoers file line format.

        Args:
            user: Username for the sudoers entry

        Returns:
            Sudoers-formatted line
        """
        if self.rule_type == SudoRuleType.ALLOW:
            return f"{user} ALL=(ALL) NOPASSWD: {self.command}"
        else:
            return f"{user} ALL=(ALL) !{self.command}"


class DANGEROUS_COMMANDS:
    """Dangerous commands that should never be allowed via sudo."""

    SYSTEM_MODIFICATION = [
        "su",
        "su -",
        "passwd",
        "chsh",
        "chfn",
        "gpasswd",
        "newgrp",
        "visudo",
        "usermod",
        "userdel",
        "adduser",
        "useradd",
        "groupmod",
        "groupdel",
    ]

    DATA_DESTRUCTION = [
        "rm -rf /",
        "rm -rf /*",
        "dd if=/dev/zero",
        "dd if=/dev/urandom",
        "mkfs",
        "fdisk",
        "parted",
    ]

    NETWORK_CONTROL = [
        "iptables",
        "iptables-restore",
        "iptables-save",
        "ip6tables",
        "ebtables",
        "arptables",
        "tcpdump",
        "wireshark",
        "nmap",
        "netcat",
    ]

    @classmethod
    def all(cls) -> Set[str]:
        """Get all dangerous command patterns."""
        return set(cls.SYSTEM_MODIFICATION + cls.DATA_DESTRUCTION + cls.NETWORK_CONTROL)


class ALLOWED_COMMANDS:
    """Commands that are allowed via sudo for sandbox operations."""

    PACKAGE_MANAGEMENT = [
        "/usr/bin/apt-get",
        "/usr/bin/apt",
        "/usr/bin/pip",
        "/usr/bin/pip3",
        "/usr/bin/dpkg",
        "/usr/bin/apt-cache",
    ]

    SERVICE_CONTROL = [
        "/bin/systemctl restart ssh.service",
        "/bin/systemctl restart nginx.service",
        "/bin/systemctl status *",
    ]

    FILE_OPERATIONS = [
        "/bin/chmod -R g+rw /workspace/*",
        "/bin/chown -R sandbox:sandbox /workspace/*",
    ]

    @classmethod
    def all(cls) -> Set[str]:
        """Get all allowed command patterns."""
        return set(cls.PACKAGE_MANAGEMENT + cls.SERVICE_CONTROL + cls.FILE_OPERATIONS)


class SudoConfigValidator:
    """Validates sudoers configuration for security compliance."""

    def __init__(self):
        """Initialize the validator."""
        self._rules: List[SudoRule] = []
        self._load_default_rules()

    def _load_default_rules(self) -> None:
        """Load default security rules."""
        # Add dangerous command denials
        for cmd in DANGEROUS_COMMANDS.SYSTEM_MODIFICATION:
            self._rules.append(SudoRule(
                command=cmd,
                rule_type=SudoRuleType.DENY,
                reason="Prevent user account modification",
            ))

        for cmd in DANGEROUS_COMMANDS.DATA_DESTRUCTION:
            self._rules.append(SudoRule(
                command=cmd,
                rule_type=SudoRuleType.DENY,
                reason="Prevent data destruction",
            ))

        for cmd in DANGEROUS_COMMANDS.NETWORK_CONTROL:
            self._rules.append(SudoRule(
                command=cmd,
                rule_type=SudoRuleType.DENY,
                reason="Prevent network configuration changes",
            ))

        # Add allowed commands
        for cmd in ALLOWED_COMMANDS.PACKAGE_MANAGEMENT:
            self._rules.append(SudoRule(
                command=cmd,
                rule_type=SudoRuleType.ALLOW,
                reason="Allow package installation",
            ))

        for cmd in ALLOWED_COMMANDS.FILE_OPERATIONS:
            self._rules.append(SudoRule(
                command=cmd,
                rule_type=SudoRuleType.ALLOW,
                reason="Allow workspace file management",
            ))

    def validate_command(self, command: str) -> bool:
        """Check if a command is allowed to run via sudo.

        Args:
            command: Command to validate

        Returns:
            True if command is allowed
        """
        # Remove 'sudo' prefix if present
        command_to_check = command
        if command_to_check.startswith("sudo "):
            command_to_check = command_to_check[5:].lstrip()

        # Check explicit denials first - from both predefined and custom rules
        denied_commands = set(DANGEROUS_COMMANDS.all())
        denied_commands.update(
            rule.command for rule in self._rules if rule.rule_type == SudoRuleType.DENY
        )

        for denied in denied_commands:
            # Check for whole word match or path match
            denied_pattern = f" {denied} " in f" {command_to_check} "
            denied_starts = command_to_check.startswith(denied + " ")
            denied_path = command_to_check.startswith(f"/{denied} ") or f"/{denied}," in command_to_check
            if denied_pattern or denied_starts or denied_path:
                logger.warning(f"Command denied by policy: {command}")
                return False

        # Check if command matches allowed patterns
        # First check built-in allowed commands
        for allowed in ALLOWED_COMMANDS.all():
            allowed_base = allowed.split()[0]  # Get the base command path
            if command_to_check.startswith(allowed_base):
                return True

        # Then check custom allowed rules
        for rule in self._rules:
            if rule.rule_type == SudoRuleType.ALLOW:
                allowed_base = rule.command.split()[0]
                if command_to_check.startswith(allowed_base):
                    return True

        # Default deny
        return False

    def is_dangerous(self, command: str) -> bool:
        """Check if a command is considered dangerous.

        Args:
            command: Command to check

        Returns:
            True if command is dangerous
        """
        # Remove 'sudo' prefix if present
        command_to_check = command
        if command_to_check.startswith("sudo "):
            command_to_check = command_to_check[5:].lstrip()

        command_lower = command_to_check.lower()

        # Check both predefined and custom dangerous rules
        dangerous_commands = set(DANGEROUS_COMMANDS.all())
        dangerous_commands.update(
            rule.command for rule in self._rules if rule.rule_type == SudoRuleType.DENY
        )

        for dangerous in dangerous_commands:
            # Check for whole word match or path match
            dangerous_pattern = f" {dangerous.lower()} " in f" {command_lower} "
            dangerous_starts = command_lower.startswith(dangerous.lower() + " ")
            dangerous_path = f"/{dangerous.lower()} " in command_lower
            if dangerous_pattern or dangerous_starts or dangerous_path:
                return True

        return False

    def generate_sudoers(self, user: str = "sandbox") -> str:
        """Generate a sudoers file content.

        Args:
            user: Username for the sudoers entry

        Returns:
            Complete sudoers file content
        """
        lines = [
            "# Sudoers configuration for sandbox user",
            "# Auto-generated - DO NOT EDIT MANUALLY",
            "",
            "# Defaults",
            "Defaults !lecture, !mail_badpass, !authenticate",
            "Defaults secure_path = /usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "",
        ]

        # Add allowed commands
        allowed_rules = [r for r in self._rules if r.rule_type == SudoRuleType.ALLOW]
        for rule in allowed_rules:
            lines.append(rule.to_sudoers_line(user))

        lines.append("")
        lines.append("# Explicitly denied commands")

        # Add denied commands
        denied_rules = [r for r in self._rules if r.rule_type == SudoRuleType.DENY]
        for rule in denied_rules:
            lines.append(rule.to_sudoers_line(user))

        return "\n".join(lines) + "\n"

    def add_allowed_command(self, command: str, reason: str = "") -> None:
        """Add a command to the allowed list.

        Args:
            command: Command pattern to allow
            reason: Reason for allowing this command
        """
        self._rules.append(SudoRule(
            command=command,
            rule_type=SudoRuleType.ALLOW,
            reason=reason or "Custom allowed command",
        ))

    def add_denied_command(self, command: str, reason: str = "") -> None:
        """Add a command to the denied list.

        Args:
            command: Command pattern to deny
            reason: Reason for denying this command
        """
        self._rules.append(SudoRule(
            command=command,
            rule_type=SudoRuleType.DENY,
            reason=reason or "Custom denied command",
        ))

    def validate_sudoers_file(self, path: Path) -> tuple[bool, List[str]]:
        """Validate an existing sudoers file.

        Args:
            path: Path to sudoers file

        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []

        if not path.exists():
            return False, ["File does not exist"]

        content = path.read_text()

        # Check for dangerous allowed commands
        for dangerous in DANGEROUS_COMMANDS.all():
            pattern = f"NOPASSWD:.*{re.escape(dangerous)}"
            if re.search(pattern, content):
                issues.append(f"Dangerous command allowed: {dangerous}")

        # Check for missing explicit denials
        for dangerous in DANGEROUS_COMMANDS.SYSTEM_MODIFICATION:
            if dangerous not in content and f"!{dangerous}" not in content:
                issues.append(f"Missing explicit denial for: {dangerous}")

        return len(issues) == 0, issues


def validate_sudo_command(command: str) -> bool:
    """Quick check if a sudo command is allowed.

    Args:
        command: Command to check

    Returns:
        True if command is safe to execute with sudo
    """
    validator = SudoConfigValidator()
    return validator.validate_command(command)


def is_dangerous_command(command: str) -> bool:
    """Quick check if a command is dangerous.

    Args:
        command: Command to check

    Returns:
        True if command is dangerous
    """
    validator = SudoConfigValidator()
    return validator.is_dangerous(command)
