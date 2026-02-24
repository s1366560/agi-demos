"""Sandbox Profile - Sandbox 配置模板.

定义不同类型的 Sandbox 配置模板，用于控制资源使用和功能启用:
- lite: 轻量级，无桌面，仅 MCP + Terminal
- standard: 标准配置，包含 XFCE 桌面
- full: 完整开发环境，预装所有工具
"""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class SandboxProfileType(str, Enum):
    """Sandbox 配置类型."""

    LITE = "lite"
    STANDARD = "standard"
    FULL = "full"


@dataclass
class SandboxProfile:
    """Sandbox 配置模板.

    定义 Sandbox 的资源配置、功能启用和预装工具。
    """

    name: str
    description: str
    profile_type: SandboxProfileType
    desktop_enabled: bool
    memory_limit: str
    cpu_limit: str
    timeout_seconds: int
    preinstalled_tools: list[str] = field(default_factory=list)
    max_instances: int = 5
    image_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return asdict(self)

    def get_config(self) -> dict[str, Any]:
        """获取 Sandbox 创建配置."""
        return {
            "memory_limit": self.memory_limit,
            "cpu_limit": self.cpu_limit,
            "timeout_seconds": self.timeout_seconds,
            "desktop_enabled": self.desktop_enabled,
        }


# 预定义配置模板
SANDBOX_PROFILES: dict[SandboxProfileType, SandboxProfile] = {
    SandboxProfileType.LITE: SandboxProfile(
        name="Lite",
        description="轻量级 sandbox，无桌面，仅 MCP + Terminal",
        profile_type=SandboxProfileType.LITE,
        desktop_enabled=False,
        memory_limit="512m",
        cpu_limit="0.5",
        timeout_seconds=1800,
        preinstalled_tools=["python", "node"],
        max_instances=20,
        image_name="sandbox-mcp-server:lite",
    ),
    SandboxProfileType.STANDARD: SandboxProfile(
        name="Standard",
        description="标准 sandbox，包含 XFCE 桌面",
        profile_type=SandboxProfileType.STANDARD,
        desktop_enabled=True,
        memory_limit="2g",
        cpu_limit="2",
        timeout_seconds=3600,
        preinstalled_tools=["python", "node", "java"],
        max_instances=5,
        image_name="sandbox-mcp-server:latest",
    ),
    SandboxProfileType.FULL: SandboxProfile(
        name="Full",
        description="完整开发环境，预装所有工具",
        profile_type=SandboxProfileType.FULL,
        desktop_enabled=True,
        memory_limit="4g",
        cpu_limit="4",
        timeout_seconds=7200,
        preinstalled_tools=["python", "node", "java", "go", "rust"],
        max_instances=2,
        image_name="sandbox-mcp-server:full",
    ),
}


def get_profile(profile_type: SandboxProfileType) -> SandboxProfile:
    """获取指定类型的配置模板.

    Args:
        profile_type: 配置类型

    Returns:
        SandboxProfile 实例

    Raises:
        ValueError: 如果配置类型不存在
    """
    if profile_type not in SANDBOX_PROFILES:
        raise ValueError(f"Unknown profile type: {profile_type}")
    return SANDBOX_PROFILES[profile_type]


def register_profile(profile: SandboxProfile) -> None:
    """注册自定义配置模板.

    Args:
        profile: 配置模板
    """
    SANDBOX_PROFILES[profile.profile_type] = profile


def list_profiles() -> list[SandboxProfile]:
    """列出所有可用的配置模板.

    Returns:
        配置模板列表
    """
    return list(SANDBOX_PROFILES.values())


def get_default_profile() -> SandboxProfile:
    """获取默认配置模板.

    Returns:
        默认的 SandboxProfile
    """
    return SANDBOX_PROFILES[SandboxProfileType.STANDARD]
