"""Port: workspace supervisor — drives plan execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class TickReport:
    """What the supervisor did in one tick."""

    workspace_id: str
    allocations_made: int = 0
    verifications_ran: int = 0
    nodes_completed: int = 0
    nodes_blocked: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)


class WorkspaceSupervisorPort(Protocol):
    """Drives a workspace plan forward. Single-writer per workspace."""

    async def start(self, workspace_id: str) -> None:
        """Begin supervising this workspace (idempotent)."""
        ...

    async def stop(self, workspace_id: str) -> None:
        """Stop supervising (idempotent)."""
        ...

    async def tick(self, workspace_id: str) -> TickReport:
        """Run one supervision step. Idempotent — safe to call on timer."""
        ...

    async def is_running(self, workspace_id: str) -> bool: ...
