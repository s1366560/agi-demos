"""Channel reload planning and reconciliation helpers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.infrastructure.adapters.secondary.persistence.channel_models import ChannelConfigModel
from src.infrastructure.adapters.secondary.persistence.channel_repository import (
    ChannelConfigRepository,
)
from src.infrastructure.agent.plugins.registry import PluginDiagnostic, get_plugin_registry
from src.infrastructure.channels.connection_manager import (
    ChannelConnectionManager,
    ManagedConnection,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChannelReloadPlan:
    """Planned channel connection changes."""

    to_add: tuple[str, ...] = ()
    to_remove: tuple[str, ...] = ()
    to_restart: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool:
        """Whether plan contains add/remove/restart operations."""
        return bool(self.to_add or self.to_remove or self.to_restart)

    def summary(self) -> dict[str, int]:
        """Summarize plan counts for logging and plugin hooks."""
        return {
            "add": len(self.to_add),
            "remove": len(self.to_remove),
            "restart": len(self.to_restart),
            "unchanged": len(self.unchanged),
        }


def build_channel_reload_plan(
    enabled_configs: list[ChannelConfigModel],
    current_connections: dict[str, ManagedConnection],
) -> ChannelReloadPlan:
    """Build a deterministic reload plan from DB enabled configs and active connections."""
    enabled_by_id = {config.id: config for config in enabled_configs}
    enabled_ids = set(enabled_by_id.keys())
    connection_ids = set(current_connections.keys())

    to_add = sorted(enabled_ids - connection_ids)
    to_remove = sorted(connection_ids - enabled_ids)
    to_restart: list[str] = []
    unchanged: list[str] = []

    shared_ids = sorted(enabled_ids & connection_ids)
    for config_id in shared_ids:
        config = enabled_by_id[config_id]
        connection = current_connections[config_id]
        if _should_restart_connection(config, connection):
            to_restart.append(config_id)
        else:
            unchanged.append(config_id)

    return ChannelReloadPlan(
        to_add=tuple(to_add),
        to_remove=tuple(to_remove),
        to_restart=tuple(to_restart),
        unchanged=tuple(unchanged),
    )


async def collect_channel_reload_plan(
    manager: ChannelConnectionManager,
    session_factory: Callable[..., Any],
) -> tuple[ChannelReloadPlan, dict[str, ChannelConfigModel]]:
    """Collect current reload plan and enabled config snapshot from DB."""
    async with session_factory() as session:
        repo = ChannelConfigRepository(session)
        enabled_configs = await repo.list_all_enabled()

    enabled_by_id = {config.id: config for config in enabled_configs}
    plan = build_channel_reload_plan(enabled_configs, manager.connections)
    return plan, enabled_by_id


async def reconcile_channel_connections(
    manager: ChannelConnectionManager,
    session_factory: Callable[..., Any],
    *,
    apply_changes: bool = False,
) -> ChannelReloadPlan:
    """Build and optionally apply channel reload plan."""
    plan, enabled_by_id = await collect_channel_reload_plan(manager, session_factory)

    logger.info(
        "[ChannelReload] plan=%s apply_changes=%s",
        plan.summary(),
        apply_changes,
    )

    if apply_changes:
        for config_id in plan.to_remove:
            await manager.remove_connection(config_id)
        for config_id in plan.to_restart:
            await manager.restart_connection(config_id)
        for config_id in plan.to_add:
            config = enabled_by_id.get(config_id)
            if config is None:
                logger.warning(
                    "[ChannelReload] Missing config while applying add for %s", config_id
                )
                continue
            await manager.add_connection(config)

    await _notify_plugin_reload_hooks(plan=plan, dry_run=not apply_changes)
    return plan


def _should_restart_connection(config: ChannelConfigModel, connection: ManagedConnection) -> bool:
    """Heuristic restart detection for already-managed enabled connections."""
    if not config.updated_at:
        return False
    if connection.last_heartbeat is None:
        return False

    updated_at = _ensure_utc(config.updated_at)
    last_heartbeat = _ensure_utc(connection.last_heartbeat)
    return updated_at > last_heartbeat


def _ensure_utc(dt: datetime) -> datetime:
    """Normalize datetime to UTC-aware value."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


async def _notify_plugin_reload_hooks(*, plan: ChannelReloadPlan, dry_run: bool) -> None:
    """Send reload plan summary to registered plugin hooks."""
    registry = get_plugin_registry()
    diagnostics = await registry.notify_channel_reload(plan_summary=plan.summary(), dry_run=dry_run)
    for diagnostic in diagnostics:
        _log_plugin_diagnostic(diagnostic)


def _log_plugin_diagnostic(diagnostic: PluginDiagnostic) -> None:
    """Log plugin diagnostics emitted during channel reload hooks."""
    message = (
        f"[ChannelReload][Plugin:{diagnostic.plugin_name}] {diagnostic.code}: {diagnostic.message}"
    )
    if diagnostic.level == "error":
        logger.error(message)
        return
    logger.warning(message)
