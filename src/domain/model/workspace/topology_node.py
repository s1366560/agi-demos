from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.domain.shared_kernel import Entity


class TopologyNodeType(str, Enum):
    """Node kind in workspace topology graph."""

    USER = "user"
    AGENT = "agent"
    TASK = "task"
    NOTE = "note"
    CORRIDOR = "corridor"
    HUMAN_SEAT = "human_seat"
    OBJECTIVE = "objective"


@dataclass(kw_only=True)
class TopologyNode(Entity):
    """A positioned node in workspace topology."""

    workspace_id: str
    node_type: TopologyNodeType
    ref_id: str | None = None
    title: str = ""
    position_x: float = 0.0
    position_y: float = 0.0
    hex_q: int | None = None
    hex_r: int | None = None
    status: str = "active"
    tags: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("workspace_id cannot be empty")
