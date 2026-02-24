"""
TenantAgentConfig entity (T093).

Represents tenant-level agent configuration that controls
agent behavior at the tenant level.

Configuration Options:
- LLM model selection and temperature
- Pattern learning enablement
- Multi-level thinking enablement
- Work plan limits
- Tool availability and timeouts
- Custom tool settings

Access Control (FR-021, FR-022):
- All authenticated users can READ config
- Only tenant admins can MODIFY config
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ConfigType(Enum):
    """Type of configuration."""

    DEFAULT = "default"
    CUSTOM = "custom"


@dataclass
class TenantAgentConfig:
    """
    Tenant-level agent configuration.

    This entity controls agent behavior at the tenant level,
    allowing tenant administrators to customize how the agent works
    within their tenant.

    Attributes:
        id: Unique identifier for this config
        tenant_id: ID of the tenant that owns this config
        config_type: Type of configuration (default or custom)
        llm_model: LLM model to use for agent
        llm_temperature: Temperature for LLM (0-2)
        pattern_learning_enabled: Whether pattern learning is enabled
        multi_level_thinking_enabled: Whether multi-level thinking is enabled
        max_work_plan_steps: Maximum number of steps in work plan
        tool_timeout_seconds: Default timeout for tool execution
        enabled_tools: List of explicitly enabled tools
        disabled_tools: List of explicitly disabled tools
        created_at: When this config was created
        updated_at: When this config was last modified
    """

    id: str
    tenant_id: str
    config_type: ConfigType
    llm_model: str
    llm_temperature: float
    pattern_learning_enabled: bool
    multi_level_thinking_enabled: bool
    max_work_plan_steps: int
    tool_timeout_seconds: int
    enabled_tools: list[str] = field(default_factory=list)
    disabled_tools: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate the configuration."""
        if not self.tenant_id:
            raise ValueError("tenant_id cannot be empty")
        if not self.llm_model:
            raise ValueError("llm_model cannot be empty")
        if not 0 <= self.llm_temperature <= 2:
            raise ValueError("llm_temperature must be between 0 and 2")
        if self.max_work_plan_steps <= 0:
            raise ValueError("max_work_plan_steps must be positive")
        if self.tool_timeout_seconds <= 0:
            raise ValueError("tool_timeout_seconds must be positive")

    def is_tool_enabled(self, tool_name: str) -> bool:
        """
        Check if a tool is enabled for this tenant.

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if tool is enabled, False if disabled
        """
        # Explicitly disabled
        if tool_name in self.disabled_tools:
            return False
        # Explicitly enabled or not in either list (default to enabled)
        return tool_name in self.enabled_tools or len(self.enabled_tools) == 0

    def update_llm_settings(
        self,
        model: str | None = None,
        temperature: float | None = None,
    ) -> "TenantAgentConfig":
        """
        Update LLM settings.

        Args:
            model: New model name (optional)
            temperature: New temperature (optional)

        Returns:
            Updated configuration
        """
        if temperature is not None and not 0 <= temperature <= 2:
            raise ValueError("llm_temperature must be between 0 and 2")

        return TenantAgentConfig(
            id=self.id,
            tenant_id=self.tenant_id,
            config_type=ConfigType.CUSTOM,
            llm_model=model or self.llm_model,
            llm_temperature=temperature if temperature is not None else self.llm_temperature,
            pattern_learning_enabled=self.pattern_learning_enabled,
            multi_level_thinking_enabled=self.multi_level_thinking_enabled,
            max_work_plan_steps=self.max_work_plan_steps,
            tool_timeout_seconds=self.tool_timeout_seconds,
            enabled_tools=list(self.enabled_tools),
            disabled_tools=list(self.disabled_tools),
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
        )

    def update_pattern_learning(self, enabled: bool) -> "TenantAgentConfig":
        """
        Update pattern learning setting.

        Args:
            enabled: Whether to enable pattern learning

        Returns:
            Updated configuration
        """
        return TenantAgentConfig(
            id=self.id,
            tenant_id=self.tenant_id,
            config_type=ConfigType.CUSTOM,
            llm_model=self.llm_model,
            llm_temperature=self.llm_temperature,
            pattern_learning_enabled=enabled,
            multi_level_thinking_enabled=self.multi_level_thinking_enabled,
            max_work_plan_steps=self.max_work_plan_steps,
            tool_timeout_seconds=self.tool_timeout_seconds,
            enabled_tools=list(self.enabled_tools),
            disabled_tools=list(self.disabled_tools),
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
        )

    def update_tool_settings(
        self,
        enabled_tools: list[str] | None = None,
        disabled_tools: list[str] | None = None,
        timeout_seconds: int | None = None,
    ) -> "TenantAgentConfig":
        """
        Update tool settings.

        Args:
            enabled_tools: List of enabled tools
            disabled_tools: List of disabled tools
            timeout_seconds: Tool timeout in seconds

        Returns:
            Updated configuration
        """
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("tool_timeout_seconds must be positive")

        return TenantAgentConfig(
            id=self.id,
            tenant_id=self.tenant_id,
            config_type=ConfigType.CUSTOM,
            llm_model=self.llm_model,
            llm_temperature=self.llm_temperature,
            pattern_learning_enabled=self.pattern_learning_enabled,
            multi_level_thinking_enabled=self.multi_level_thinking_enabled,
            max_work_plan_steps=self.max_work_plan_steps,
            tool_timeout_seconds=timeout_seconds
            if timeout_seconds is not None
            else self.tool_timeout_seconds,
            enabled_tools=list(enabled_tools)
            if enabled_tools is not None
            else list(self.enabled_tools),
            disabled_tools=list(disabled_tools)
            if disabled_tools is not None
            else list(self.disabled_tools),
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "config_type": self.config_type.value,
            "llm_model": self.llm_model,
            "llm_temperature": self.llm_temperature,
            "pattern_learning_enabled": self.pattern_learning_enabled,
            "multi_level_thinking_enabled": self.multi_level_thinking_enabled,
            "max_work_plan_steps": self.max_work_plan_steps,
            "tool_timeout_seconds": self.tool_timeout_seconds,
            "enabled_tools": list(self.enabled_tools),
            "disabled_tools": list(self.disabled_tools),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def create_default(cls, tenant_id: str) -> "TenantAgentConfig":
        """
        Create a default configuration for a tenant.

        Args:
            tenant_id: Tenant ID

        Returns:
            Default configuration
        """
        config_id = f"tenant-config-{tenant_id}"

        return cls(
            id=config_id,
            tenant_id=tenant_id,
            config_type=ConfigType.DEFAULT,
            llm_model="default",
            llm_temperature=0.7,
            pattern_learning_enabled=True,
            multi_level_thinking_enabled=True,
            max_work_plan_steps=10,
            tool_timeout_seconds=30,
            enabled_tools=[],
            disabled_tools=[],
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TenantAgentConfig":
        """Create from dictionary (e.g., from database)."""
        return cls(
            id=data["id"],
            tenant_id=data["tenant_id"],
            config_type=ConfigType(data.get("config_type", "default")),
            llm_model=data.get("llm_model", "default"),
            llm_temperature=data.get("llm_temperature", 0.7),
            pattern_learning_enabled=data.get("pattern_learning_enabled", True),
            multi_level_thinking_enabled=data.get("multi_level_thinking_enabled", True),
            max_work_plan_steps=data.get("max_work_plan_steps", 10),
            tool_timeout_seconds=data.get("tool_timeout_seconds", 30),
            enabled_tools=data.get("enabled_tools", []),
            disabled_tools=data.get("disabled_tools", []),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if "updated_at" in data
            else datetime.now(UTC),
        )


# Default configuration values
DEFAULT_CONFIG = {
    "llm_model": "default",
    "llm_temperature": 0.7,
    "pattern_learning_enabled": True,
    "multi_level_thinking_enabled": True,
    "max_work_plan_steps": 10,
    "tool_timeout_seconds": 30,
}
