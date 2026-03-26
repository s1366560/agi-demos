from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class WorkspaceAgent(Entity):
    """Agent attached to a workspace collaboration context."""

    workspace_id: str
    agent_id: str
    display_name: str | None = None
    description: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    hex_q: int | None = None
    hex_r: int | None = None
    theme_color: str | None = None
    label: str | None = None
    status: str = "idle"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("workspace_id cannot be empty")
        if not self.agent_id:
            raise ValueError("agent_id cannot be empty")
