"""Instance channel configuration domain entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class InstanceChannelConfig(Entity):
    """Represents a channel configuration scoped to an instance."""

    instance_id: str
    channel_type: str
    name: str
    config: dict[str, object] = field(default_factory=dict)
    status: str = "pending"
    last_connected_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
