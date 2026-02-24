"""
Feature Flags for Agent Pool.

Provides gradual rollout capabilities:
- Per-tenant feature flags
- Per-project feature flags
- Percentage-based rollout
- Time-based activation

Usage:
    flags = FeatureFlags()

    if await flags.is_enabled("pool_v2", tenant_id="t1"):
        # Use new pool
    else:
        # Use legacy pool
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis.asyncio import Redis


logger = logging.getLogger(__name__)


class RolloutStrategy(str, Enum):
    """Rollout strategies."""

    ALL = "all"  # Enable for all
    NONE = "none"  # Disable for all
    PERCENTAGE = "percentage"  # Enable for percentage of users
    ALLOWLIST = "allowlist"  # Enable for specific tenants/projects
    DENYLIST = "denylist"  # Enable for all except specific tenants/projects
    GRADUAL = "gradual"  # Gradually increase percentage over time


@dataclass
class FeatureFlagConfig:
    """Configuration for a feature flag."""

    name: str
    description: str = ""
    enabled: bool = False
    strategy: RolloutStrategy = RolloutStrategy.NONE

    # For percentage-based rollout
    percentage: float = 0.0  # 0-100

    # For allowlist/denylist
    tenant_allowlist: set[str] = field(default_factory=set)
    tenant_denylist: set[str] = field(default_factory=set)
    project_allowlist: set[str] = field(default_factory=set)
    project_denylist: set[str] = field(default_factory=set)

    # For gradual rollout
    start_date: datetime | None = None
    end_date: datetime | None = None
    start_percentage: float = 0.0
    end_percentage: float = 100.0

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# Default feature flags for Agent Pool
DEFAULT_FLAGS: dict[str, FeatureFlagConfig] = {
    "agent_pool_enabled": FeatureFlagConfig(
        name="agent_pool_enabled",
        description="Enable new agent pool architecture",
        enabled=False,
        strategy=RolloutStrategy.NONE,
    ),
    "agent_pool_hot_tier": FeatureFlagConfig(
        name="agent_pool_hot_tier",
        description="Enable HOT tier (dedicated containers)",
        enabled=False,
        strategy=RolloutStrategy.ALLOWLIST,
    ),
    "agent_pool_warm_tier": FeatureFlagConfig(
        name="agent_pool_warm_tier",
        description="Enable WARM tier (shared pool)",
        enabled=True,
        strategy=RolloutStrategy.ALL,
    ),
    "agent_pool_cold_tier": FeatureFlagConfig(
        name="agent_pool_cold_tier",
        description="Enable COLD tier (on-demand)",
        enabled=True,
        strategy=RolloutStrategy.ALL,
    ),
    "agent_pool_health_monitor": FeatureFlagConfig(
        name="agent_pool_health_monitor",
        description="Enable health monitoring",
        enabled=True,
        strategy=RolloutStrategy.ALL,
    ),
    "agent_pool_failure_recovery": FeatureFlagConfig(
        name="agent_pool_failure_recovery",
        description="Enable automatic failure recovery",
        enabled=True,
        strategy=RolloutStrategy.ALL,
    ),
    "agent_pool_auto_scaling": FeatureFlagConfig(
        name="agent_pool_auto_scaling",
        description="Enable auto-scaling",
        enabled=False,
        strategy=RolloutStrategy.NONE,
    ),
    "agent_pool_state_recovery": FeatureFlagConfig(
        name="agent_pool_state_recovery",
        description="Enable state checkpointing and recovery",
        enabled=True,
        strategy=RolloutStrategy.ALL,
    ),
    "agent_pool_metrics": FeatureFlagConfig(
        name="agent_pool_metrics",
        description="Enable Prometheus metrics",
        enabled=True,
        strategy=RolloutStrategy.ALL,
    ),
}


class FeatureFlags:
    """
    Feature flag management for gradual rollout.

    Supports:
    - Global enable/disable
    - Per-tenant flags
    - Per-project flags
    - Percentage-based rollout
    - Gradual rollout over time
    """

    def __init__(
        self,
        flags: dict[str, FeatureFlagConfig] | None = None,
        redis_client: Redis | None = None,
    ) -> None:
        # Use default flags, then override with provided flags
        self._flags: dict[str, FeatureFlagConfig] = dict(DEFAULT_FLAGS)
        if flags:
            self._flags.update(flags)

        self._redis_client = redis_client
        self._cache: dict[str, bool] = {}
        self._lock = asyncio.Lock()

    def get_flag(self, name: str) -> FeatureFlagConfig | None:
        """Get flag configuration."""
        return self._flags.get(name)

    def set_flag(self, config: FeatureFlagConfig) -> None:
        """Set or update a flag."""
        config.updated_at = datetime.now(UTC)
        self._flags[config.name] = config
        # Clear cache for this flag
        self._cache = {k: v for k, v in self._cache.items() if not k.startswith(config.name)}

    async def is_enabled(
        self,
        name: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> bool:
        """
        Check if a feature is enabled.
        Args:
            name: Feature flag name
            tenant_id: Optional tenant ID for per-tenant checks
            project_id: Optional project ID for per-project checks
            True if feature is enabled
        """
        flag = self._flags.get(name)
        if not flag or not flag.enabled:
            return False

        # Dispatch strategy check
        strategy_handlers = {
            RolloutStrategy.ALL: lambda _f, _t, _p: True,
            RolloutStrategy.NONE: lambda _f, _t, _p: False,
            RolloutStrategy.ALLOWLIST: self._check_allowlist,
            RolloutStrategy.DENYLIST: self._check_denylist,
            RolloutStrategy.PERCENTAGE: self._check_percentage,
            RolloutStrategy.GRADUAL: self._check_gradual,
        }
        handler = strategy_handlers.get(flag.strategy)
        return handler(flag, tenant_id, project_id) if handler else False

    async def get_all_flags(self) -> dict[str, dict[str, Any]]:
        """Get all flags as dictionary."""
        return {
            name: {
                "name": flag.name,
                "description": flag.description,
                "enabled": flag.enabled,
                "strategy": flag.strategy.value,
                "percentage": flag.percentage,
            }
            for name, flag in self._flags.items()
        }

    async def enable_for_tenant(self, flag_name: str, tenant_id: str) -> bool:
        """Add tenant to allowlist."""
        flag = self._flags.get(flag_name)
        if not flag:
            return False

        flag.tenant_allowlist.add(tenant_id)
        flag.updated_at = datetime.now(UTC)

        # If currently using denylist, remove from denylist
        flag.tenant_denylist.discard(tenant_id)

        return True

    async def disable_for_tenant(self, flag_name: str, tenant_id: str) -> bool:
        """Remove tenant from allowlist or add to denylist."""
        flag = self._flags.get(flag_name)
        if not flag:
            return False

        flag.tenant_allowlist.discard(tenant_id)
        if flag.strategy == RolloutStrategy.DENYLIST:
            flag.tenant_denylist.add(tenant_id)
        flag.updated_at = datetime.now(UTC)

        return True

    async def enable_for_project(
        self,
        flag_name: str,
        tenant_id: str,
        project_id: str,
    ) -> bool:
        """Add project to allowlist."""
        flag = self._flags.get(flag_name)
        if not flag:
            return False

        key = f"{tenant_id}:{project_id}"
        flag.project_allowlist.add(key)
        flag.project_denylist.discard(key)
        flag.updated_at = datetime.now(UTC)

        return True

    async def set_percentage(self, flag_name: str, percentage: float) -> bool:
        """Set rollout percentage."""
        flag = self._flags.get(flag_name)
        if not flag:
            return False

        flag.percentage = max(0.0, min(100.0, percentage))
        flag.strategy = RolloutStrategy.PERCENTAGE
        flag.updated_at = datetime.now(UTC)

        return True

    async def start_gradual_rollout(
        self,
        flag_name: str,
        start_percentage: float = 0.0,
        end_percentage: float = 100.0,
        duration_days: int = 7,
    ) -> bool:
        """Start gradual rollout over time."""
        flag = self._flags.get(flag_name)
        if not flag:
            return False

        from datetime import timedelta

        flag.strategy = RolloutStrategy.GRADUAL
        flag.start_date = datetime.now(UTC)
        flag.end_date = flag.start_date + timedelta(days=duration_days)
        flag.start_percentage = start_percentage
        flag.end_percentage = end_percentage
        flag.enabled = True
        flag.updated_at = datetime.now(UTC)

        logger.info(
            f"Started gradual rollout for {flag_name}: "
            f"{start_percentage}% -> {end_percentage}% over {duration_days} days"
        )

        return True

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _check_allowlist(
        self,
        flag: FeatureFlagConfig,
        tenant_id: str | None,
        project_id: str | None,
    ) -> bool:
        """Check if tenant/project is in allowlist."""
        # Check project allowlist first (more specific)
        if tenant_id and project_id:
            key = f"{tenant_id}:{project_id}"
            if key in flag.project_allowlist:
                return True

        # Check tenant allowlist
        return bool(tenant_id and tenant_id in flag.tenant_allowlist)

    def _check_denylist(
        self,
        flag: FeatureFlagConfig,
        tenant_id: str | None,
        project_id: str | None,
    ) -> bool:
        """Check if tenant/project is NOT in denylist."""
        # Check project denylist first
        if tenant_id and project_id:
            key = f"{tenant_id}:{project_id}"
            if key in flag.project_denylist:
                return False

        # Check tenant denylist
        return not (tenant_id and tenant_id in flag.tenant_denylist)

    def _check_percentage(
        self,
        flag: FeatureFlagConfig,
        tenant_id: str | None,
        project_id: str | None,
    ) -> bool:
        """Check percentage-based rollout using consistent hashing."""
        if flag.percentage >= 100.0:
            return True
        if flag.percentage <= 0.0:
            return False

        # Use consistent hashing for deterministic results
        key = f"{flag.name}:{tenant_id or ''}:{project_id or ''}"
        hash_value = int(hashlib.md5(key.encode()).hexdigest(), 16)
        bucket = hash_value % 100

        return bucket < flag.percentage

    def _check_gradual(
        self,
        flag: FeatureFlagConfig,
        tenant_id: str | None,
        project_id: str | None,
    ) -> bool:
        """Check gradual rollout based on current time."""
        if not flag.start_date or not flag.end_date:
            return False

        now = datetime.now(UTC)

        # Before start
        if now < flag.start_date:
            return self._check_percentage_value(flag, flag.start_percentage, tenant_id, project_id)

        # After end
        if now >= flag.end_date:
            return self._check_percentage_value(flag, flag.end_percentage, tenant_id, project_id)

        # During rollout - calculate current percentage
        total_duration = (flag.end_date - flag.start_date).total_seconds()
        elapsed = (now - flag.start_date).total_seconds()
        progress = elapsed / total_duration

        current_percentage = (
            flag.start_percentage + (flag.end_percentage - flag.start_percentage) * progress
        )

        return self._check_percentage_value(flag, current_percentage, tenant_id, project_id)

    def _check_percentage_value(
        self,
        flag: FeatureFlagConfig,
        percentage: float,
        tenant_id: str | None,
        project_id: str | None,
    ) -> bool:
        """Check if tenant/project falls within percentage."""
        if percentage >= 100.0:
            return True
        if percentage <= 0.0:
            return False

        key = f"{flag.name}:{tenant_id or ''}:{project_id or ''}"
        hash_value = int(hashlib.md5(key.encode()).hexdigest(), 16)
        bucket = hash_value % 100

        return bucket < percentage


# Global feature flags instance
_global_flags: FeatureFlags | None = None


def get_feature_flags() -> FeatureFlags:
    """Get global feature flags instance."""
    global _global_flags
    if _global_flags is None:
        _global_flags = FeatureFlags()
    return _global_flags


def reset_feature_flags() -> None:
    """Reset global feature flags (for testing)."""
    global _global_flags
    _global_flags = None
