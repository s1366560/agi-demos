"""Channel reload planning and reconciliation helpers."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.channel_models import ChannelConfigModel
from src.infrastructure.adapters.secondary.persistence.channel_repository import (
    ChannelConfigRepository,
)
from src.infrastructure.channels.connection_manager import (
    ChannelConnectionManager,
    ManagedConnection,
)
from src.infrastructure.plugins.v2.boundary import (
    current_process_generation_host_v2,
    pin_operation_context_v2,
)
from src.infrastructure.plugins.v2.channel_adapters import CHANNEL_RUNTIME_RELOAD_EVENT_V2

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
    """Dispatch the declared reload event through an independently leased V2 operation."""
    host = current_process_generation_host_v2()
    operation_id = f"channel-reload:{uuid.uuid4().hex}"
    async with pin_operation_context_v2(
        host,
        operation_id=operation_id,
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ) as operation:
        _ = await operation.dispatch(
            CHANNEL_RUNTIME_RELOAD_EVENT_V2,
            {
                "dry_run": dry_run,
                "generation_digest": operation.generation.digest,
                "operation_id": operation.operation_id,
                "plan": plan.summary(),
            },
        )
