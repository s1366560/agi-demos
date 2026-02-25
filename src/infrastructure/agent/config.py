"""Unified Configuration Management for ReActAgent.

This module provides centralized configuration management with support for
tenant-level overrides and dynamic configuration updates.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ExecutionMode(Enum):
    """Execution mode for the agent."""

    NORMAL = "normal"
    PLAN = "plan"
    EXPLORE = "explore"
    BUILD = "build"


@dataclass
class AgentConfig:
    """Unified flat configuration for ReActAgent.

    All fields from the former nested configs (ExecutionConfig,
    PerformanceConfig, CostConfig, PermissionConfig, MonitoringConfig)
    are promoted to top-level fields.

    Backward-compatibility: ``config.execution.max_steps`` etc. still
    work because the ``execution`` / ``performance`` / ``cost`` /
    ``permission`` / ``monitoring`` properties return ``self``.
    """

    # -- Execution ---------------------------------------------------------
    max_steps: int = 20
    max_retries: int = 3
    skill_match_threshold: float = 0.9
    subagent_match_threshold: float = 0.5
    allow_direct_execution: bool = True
    enable_plan_mode: bool = True
    enable_subagent_routing: bool = True
    default_timeout_seconds: float = 30.0
    tool_timeout_seconds: float = 120.0
    llm_timeout_seconds: float = 60.0

    # -- Performance -------------------------------------------------------
    context_limit: int = 128000
    context_compression_threshold: float = 0.8
    max_history_messages: int = 100
    max_parallel_tasks: int = 5
    enable_parallel_tool_execution: bool = True
    enable_cache: bool = True
    cache_ttl_seconds: int = 300
    max_memory_mb: int = 2048
    gc_threshold_messages: int = 50

    # -- Cost --------------------------------------------------------------
    max_cost_per_request: float = 1.0
    max_cost_per_session: float = 10.0
    cost_warning_threshold: float = 0.8
    enable_cost_tracking: bool = True
    log_cost_details: bool = True
    cached_input_discount: float = 0.5
    cached_output_discount: float = 0.5

    # -- Permission --------------------------------------------------------
    permission_default_mode: str = "ask"
    auto_approve_safe_tools: bool = True
    safe_tools: set[str] = field(
        default_factory=lambda: {
            "read_file",
            "list_directory",
            "search",
        }
    )
    remember_approvals: bool = True
    approval_ttl_seconds: int = 3600

    # -- Monitoring --------------------------------------------------------
    log_level: str = "INFO"
    log_execution_details: bool = True
    log_tool_calls: bool = True
    enable_metrics: bool = True
    metrics_export_interval_seconds: int = 60
    enable_tracing: bool = False
    trace_sample_rate: float = 0.1
    enable_doom_loop_detection: bool = True
    doom_loop_threshold: int = 5
    doom_loop_window: int = 10

    # -- Tenant ------------------------------------------------------------
    tenant_id: str | None = None
    environment: str = "production"

    # -- Backward-compatibility property shims -----------------------------
    # ``config.execution.max_steps`` -> ``self.max_steps`` (self is returned)

    @property
    def execution(self) -> "AgentConfig":
        """Backward-compat shim: return self so .execution.X works."""
        return self

    @property
    def performance(self) -> "AgentConfig":
        """Backward-compat shim: return self so .performance.X works."""
        return self

    @property
    def cost(self) -> "AgentConfig":
        """Backward-compat shim: return self so .cost.X works."""
        return self

    @property
    def permission(self) -> "AgentConfig":
        """Backward-compat shim: return self so .permission.X works."""
        return self

    @property
    def monitoring(self) -> "AgentConfig":
        """Backward-compat shim: return self so .monitoring.X works."""
        return self

    @property
    def default_mode(self) -> str:
        """Backward-compat shim: config.permission.default_mode works."""
        return self.permission_default_mode

    # -- Validation --------------------------------------------------------

    def validate(self) -> None:
        """Validate all configuration values."""
        # Execution
        if not 1 <= self.max_steps <= 100:
            raise ValueError(f"max_steps must be 1-100, got {self.max_steps}")
        if not 0.0 <= self.skill_match_threshold <= 1.0:
            raise ValueError(f"skill_match_threshold must be 0-1, got {self.skill_match_threshold}")
        if not 0.0 <= self.subagent_match_threshold <= 1.0:
            raise ValueError(
                f"subagent_match_threshold must be 0-1, got {self.subagent_match_threshold}"
            )

        # Performance
        if self.context_limit < 1000:
            raise ValueError(f"context_limit must be >= 1000, got {self.context_limit}")
        if not 0.0 <= self.context_compression_threshold <= 1.0:
            raise ValueError(
                f"context_compression_threshold must be 0-1, "
                f"got {self.context_compression_threshold}"
            )

        # Cost
        if self.max_cost_per_request < 0:
            raise ValueError(f"max_cost_per_request must be >= 0, got {self.max_cost_per_request}")
        if not 0.0 <= self.cost_warning_threshold <= 1.0:
            raise ValueError(
                f"cost_warning_threshold must be 0-1, got {self.cost_warning_threshold}"
            )

        # Permission
        if self.permission_default_mode not in ("allow", "deny", "ask"):
            raise ValueError(
                f"default_mode must be allow/deny/ask, got {self.permission_default_mode}"
            )

        # Monitoring
        valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.log_level not in valid_log_levels:
            raise ValueError(f"log_level must be one of {valid_log_levels}, got {self.log_level}")
        if not 0.0 <= self.trace_sample_rate <= 1.0:
            raise ValueError(f"trace_sample_rate must be 0-1, got {self.trace_sample_rate}")

    # -- Serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to nested dictionary (API-compatible)."""
        return {
            "execution": {
                "max_steps": self.max_steps,
                "skill_match_threshold": self.skill_match_threshold,
                "subagent_match_threshold": self.subagent_match_threshold,
                "default_timeout_seconds": self.default_timeout_seconds,
            },
            "performance": {
                "context_limit": self.context_limit,
                "max_parallel_tasks": self.max_parallel_tasks,
                "enable_cache": self.enable_cache,
            },
            "cost": {
                "max_cost_per_request": self.max_cost_per_request,
                "max_cost_per_session": self.max_cost_per_session,
                "enable_cost_tracking": self.enable_cost_tracking,
            },
            "permission": {
                "default_mode": self.permission_default_mode,
                "auto_approve_safe_tools": self.auto_approve_safe_tools,
            },
            "monitoring": {
                "log_level": self.log_level,
                "enable_metrics": self.enable_metrics,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentConfig":
        """Create configuration from nested dictionary.

        Args:
            data: Dictionary with configuration values (nested structure)

        Returns:
            A new AgentConfig instance
        """
        execution_data = data.get("execution", {})
        performance_data = data.get("performance", {})
        cost_data = data.get("cost", {})
        permission_data = data.get("permission", {})
        monitoring_data = data.get("monitoring", {})

        # Map nested "default_mode" to flat "permission_default_mode"
        flat: dict[str, Any] = {}
        flat.update(execution_data)
        flat.update(performance_data)
        flat.update(cost_data)
        flat.update(
            {k: v for k, v in permission_data.items() if k not in ("default_mode", "safe_tools")}
        )
        if "default_mode" in permission_data:
            flat["permission_default_mode"] = permission_data["default_mode"]
        flat.update(monitoring_data)

        if "tenant_id" in data:
            flat["tenant_id"] = data["tenant_id"]
        if "environment" in data:
            flat["environment"] = data["environment"]

        return cls(**flat)

    @classmethod
    def get_default(cls) -> "AgentConfig":
        """Get default configuration."""
        return cls()

    def with_tenant_override(self, overrides: dict[str, Any]) -> "AgentConfig":
        """Create a copy with tenant-specific overrides.

        Args:
            overrides: Dictionary of override values

        Returns:
            A new AgentConfig with overrides applied
        """
        config_dict = self.to_dict()
        config_dict.update(overrides)
        return self.from_dict(config_dict)


# Backward-compatibility alias: external code importing ExecutionConfig
# will receive AgentConfig (which has all the same fields).
ExecutionConfig = AgentConfig


class ConfigManager:
    """Manages agent configuration with support for dynamic updates."""

    def __init__(self, default_config: AgentConfig | None = None) -> None:
        """Initialize the configuration manager.

        Args:
            default_config: Default configuration to use
        """
        self._default = default_config or AgentConfig()
        self._tenant_configs: dict[str, AgentConfig] = {}
        self._change_callbacks: set[Callable[..., Any]] = set()

    def get_config(self, tenant_id: str | None = None) -> AgentConfig:
        """Get configuration for a tenant.

        Args:
            tenant_id: Optional tenant ID for tenant-specific config

        Returns:
            Configuration for the tenant (or default if no tenant config exists)
        """
        if tenant_id and tenant_id in self._tenant_configs:
            return self._tenant_configs[tenant_id]
        return self._default

    def set_tenant_config(self, tenant_id: str, config: AgentConfig) -> None:
        """Set configuration for a specific tenant.

        Args:
            tenant_id: The tenant ID
            config: The tenant-specific configuration
        """
        config.validate()
        config.tenant_id = tenant_id
        self._tenant_configs[tenant_id] = config

        # Notify listeners of configuration change
        self._notify_change(tenant_id)

    def update_default(self, **kwargs: Any) -> None:
        """Update default configuration with new values.

        Args:
            **kwargs: Configuration values to update
        """
        config_dict = self._default.to_dict()
        self._merge_dict(config_dict, kwargs)
        self._default = AgentConfig.from_dict(config_dict)
        self._default.validate()

        self._notify_change(None)

    def register_change_callback(self, callback: Callable[..., Any]) -> None:
        """Register a callback to be called on configuration changes.

        Args:
            callback: Function to call with (tenant_id, config)
        """
        self._change_callbacks.add(callback)

    def unregister_change_callback(self, callback: Callable[..., Any]) -> None:
        """Unregister a change callback.

        Args:
            callback: The callback to remove
        """
        self._change_callbacks.discard(callback)

    def _notify_change(self, tenant_id: str | None) -> None:
        """Notify listeners of a configuration change."""
        for callback in self._change_callbacks:
            try:
                callback(tenant_id, self.get_config(tenant_id))
            except Exception as e:
                logger.warning(f"Config change callback failed: {e}")

    def _merge_dict(self, base: dict[str, Any], updates: dict[str, Any]) -> None:
        """Recursively merge updates into base dictionary."""
        for key, value in updates.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_dict(base[key], value)
            else:
                base[key] = value


# Global configuration instance
_global_config: ConfigManager = ConfigManager()


def get_config(tenant_id: str | None = None) -> AgentConfig:
    """Get the global configuration for a tenant.

    Args:
        tenant_id: Optional tenant ID

    Returns:
        The agent configuration
    """
    return _global_config.get_config(tenant_id)


def set_config(manager: ConfigManager) -> None:
    """Set the global configuration manager.

    Args:
        manager: The configuration manager to use
    """
    global _global_config
    _global_config = manager


def get_default_config() -> AgentConfig:
    """Get the default configuration.

    Returns:
        The default AgentConfig
    """
    return _global_config.get_config(None)
