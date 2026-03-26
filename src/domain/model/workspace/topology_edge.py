from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class TopologyEdge(Entity):
    """Directed edge between topology nodes."""

    workspace_id: str
    source_node_id: str
    target_node_id: str
    label: str | None = None
    source_hex_q: int | None = None
    source_hex_r: int | None = None
    target_hex_q: int | None = None
    target_hex_r: int | None = None
    direction: str | None = None
    auto_created: bool = False
    data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("workspace_id cannot be empty")
        if not self.source_node_id:
            raise ValueError("source_node_id cannot be empty")
        if not self.target_node_id:
            raise ValueError("target_node_id cannot be empty")
