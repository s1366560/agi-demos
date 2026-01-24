"""
CUA Configuration Module.

Defines configuration settings for CUA integration with MemStack.
Supports Docker container-based execution for secure isolation.
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class CUAProviderType(str, Enum):
    """CUA Computer provider types."""

    LOCAL = "local"
    DOCKER = "docker"
    CLOUD = "cloud"


class CUAOSType(str, Enum):
    """Supported operating system types."""

    LINUX = "linux"
    MACOS = "macos"
    WINDOWS = "windows"


@dataclass
class CUADockerConfig:
    """Docker-specific configuration for CUA."""

    image: str = "ghcr.io/trycua/cua-desktop:latest"
    display: str = "1920x1080"
    memory: str = "4GB"
    cpu: str = "2"
    vnc_port: int = 5900
    novnc_port: int = 6080
    container_name: str = "memstack-cua-desktop"
    network: str = "memstack-network"
    auto_remove: bool = False
    restart_policy: str = "unless-stopped"


@dataclass
class CUAPermissionConfig:
    """Permission settings for CUA operations.

    In Docker environment, permissions can be more relaxed since
    operations are isolated from the host system.
    """

    allow_screenshot: bool = True
    allow_mouse_click: bool = True  # Safe in Docker
    allow_keyboard_input: bool = True  # Safe in Docker
    allow_browser_navigation: bool = True
    allow_file_operations: bool = False  # Disabled by default
    allow_command_execution: bool = False  # Disabled by default

    # Permission mode: "allow_all", "ask_all", "configured"
    mode: str = "configured"


@dataclass
class CUASubAgentConfig:
    """SubAgent (L3) configuration."""

    enabled: bool = True
    match_threshold: float = 0.7
    triggers: List[str] = field(
        default_factory=lambda: [
            "操作电脑",
            "点击按钮",
            "浏览网页",
            "自动化任务",
            "打开应用",
            "截图",
            "填写表单",
            "use computer",
            "click button",
            "browse web",
            "automate task",
        ]
    )


@dataclass
class CUASkillConfig:
    """Skill (L2) configuration."""

    enabled: bool = True
    match_threshold: float = 0.8
    builtin_skills: List[str] = field(
        default_factory=lambda: [
            "web_search",
            "form_fill",
            "ui_automation",
            "screenshot_analyze",
        ]
    )


@dataclass
class CUAConfig:
    """Main CUA configuration.

    Attributes:
        enabled: Whether CUA integration is enabled
        model: LLM model to use for CUA agent
        temperature: LLM temperature
        max_steps: Maximum steps per agent execution
        screenshot_delay: Delay before taking screenshot after action
        provider: Computer provider type (docker, local, cloud)
        os_type: Operating system type
        docker: Docker-specific configuration
        permissions: Permission settings
        subagent: SubAgent (L3) configuration
        skill: Skill (L2) configuration
    """

    # Basic settings
    enabled: bool = False
    model: str = "anthropic/claude-sonnet-4-20250514"
    temperature: float = 0.0
    max_steps: int = 20
    screenshot_delay: float = 0.5
    max_retries: int = 3
    telemetry_enabled: bool = False

    # Provider settings
    provider: CUAProviderType = CUAProviderType.DOCKER
    os_type: CUAOSType = CUAOSType.LINUX

    # Sub-configurations
    docker: CUADockerConfig = field(default_factory=CUADockerConfig)
    permissions: CUAPermissionConfig = field(default_factory=CUAPermissionConfig)
    subagent: CUASubAgentConfig = field(default_factory=CUASubAgentConfig)
    skill: CUASkillConfig = field(default_factory=CUASkillConfig)

    # API credentials (optional, uses main config if not set)
    api_key: Optional[str] = None
    api_base: Optional[str] = None

    @classmethod
    def from_env(cls) -> "CUAConfig":
        """Create configuration from environment variables.

        Environment variables:
            CUA_ENABLED: Enable CUA integration (default: false)
            CUA_MODEL: LLM model name
            CUA_TEMPERATURE: LLM temperature
            CUA_MAX_STEPS: Max execution steps
            CUA_SCREENSHOT_DELAY: Screenshot delay in seconds
            CUA_PROVIDER: Provider type (docker, local, cloud)
            CUA_DOCKER_IMAGE: Docker image name
            CUA_DOCKER_DISPLAY: Display resolution
            CUA_DOCKER_MEMORY: Container memory limit
            CUA_DOCKER_CPU: Container CPU limit
            CUA_ALLOW_SCREENSHOT: Allow screenshot operations
            CUA_ALLOW_MOUSE_CLICK: Allow mouse click operations
            CUA_ALLOW_KEYBOARD_INPUT: Allow keyboard input
            CUA_SUBAGENT_ENABLED: Enable L3 subagent
            CUA_SKILL_ENABLED: Enable L2 skills
        """
        docker_config = CUADockerConfig(
            image=os.getenv("CUA_DOCKER_IMAGE", CUADockerConfig.image),
            display=os.getenv("CUA_DOCKER_DISPLAY", CUADockerConfig.display),
            memory=os.getenv("CUA_DOCKER_MEMORY", CUADockerConfig.memory),
            cpu=os.getenv("CUA_DOCKER_CPU", CUADockerConfig.cpu),
            vnc_port=int(os.getenv("CUA_DOCKER_VNC_PORT", str(CUADockerConfig.vnc_port))),
            novnc_port=int(os.getenv("CUA_DOCKER_NOVNC_PORT", str(CUADockerConfig.novnc_port))),
        )

        permission_config = CUAPermissionConfig(
            allow_screenshot=os.getenv("CUA_ALLOW_SCREENSHOT", "true").lower() == "true",
            allow_mouse_click=os.getenv("CUA_ALLOW_MOUSE_CLICK", "true").lower() == "true",
            allow_keyboard_input=os.getenv("CUA_ALLOW_KEYBOARD_INPUT", "true").lower() == "true",
            allow_browser_navigation=os.getenv("CUA_ALLOW_BROWSER_NAVIGATION", "true").lower()
            == "true",
        )

        subagent_config = CUASubAgentConfig(
            enabled=os.getenv("CUA_SUBAGENT_ENABLED", "true").lower() == "true",
            match_threshold=float(os.getenv("CUA_SUBAGENT_MATCH_THRESHOLD", "0.7")),
        )

        skill_config = CUASkillConfig(
            enabled=os.getenv("CUA_SKILL_ENABLED", "true").lower() == "true",
            match_threshold=float(os.getenv("CUA_SKILL_MATCH_THRESHOLD", "0.8")),
        )

        provider_str = os.getenv("CUA_PROVIDER", "docker").lower()
        try:
            provider = CUAProviderType(provider_str)
        except ValueError:
            provider = CUAProviderType.DOCKER

        os_type_str = os.getenv("CUA_OS_TYPE", "linux").lower()
        try:
            os_type = CUAOSType(os_type_str)
        except ValueError:
            os_type = CUAOSType.LINUX

        return cls(
            enabled=os.getenv("CUA_ENABLED", "false").lower() == "true",
            model=os.getenv("CUA_MODEL", "anthropic/claude-sonnet-4-20250514"),
            temperature=float(os.getenv("CUA_TEMPERATURE", "0.0")),
            max_steps=int(os.getenv("CUA_MAX_STEPS", "20")),
            screenshot_delay=float(os.getenv("CUA_SCREENSHOT_DELAY", "0.5")),
            max_retries=int(os.getenv("CUA_MAX_RETRIES", "3")),
            telemetry_enabled=os.getenv("CUA_TELEMETRY_ENABLED", "false").lower() == "true",
            provider=provider,
            os_type=os_type,
            docker=docker_config,
            permissions=permission_config,
            subagent=subagent_config,
            skill=skill_config,
            api_key=os.getenv("CUA_API_KEY"),
            api_base=os.getenv("CUA_API_BASE"),
        )

    def to_dict(self) -> dict:
        """Convert configuration to dictionary."""
        return {
            "enabled": self.enabled,
            "model": self.model,
            "temperature": self.temperature,
            "max_steps": self.max_steps,
            "screenshot_delay": self.screenshot_delay,
            "max_retries": self.max_retries,
            "provider": self.provider.value,
            "os_type": self.os_type.value,
            "docker": {
                "image": self.docker.image,
                "display": self.docker.display,
                "memory": self.docker.memory,
                "cpu": self.docker.cpu,
            },
            "permissions": {
                "allow_screenshot": self.permissions.allow_screenshot,
                "allow_mouse_click": self.permissions.allow_mouse_click,
                "allow_keyboard_input": self.permissions.allow_keyboard_input,
            },
            "subagent": {
                "enabled": self.subagent.enabled,
                "match_threshold": self.subagent.match_threshold,
            },
            "skill": {
                "enabled": self.skill.enabled,
                "match_threshold": self.skill.match_threshold,
            },
        }
