"""Explicit project enrollment boundary for cloud synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.domain.model.knowledge_sync.contracts import KnowledgeSyncScope


@dataclass(frozen=True, kw_only=True)
class KnowledgeSyncEnrollmentState:
    scope: KnowledgeSyncScope
    enabled: bool
    can_enroll: bool
    bootstrap_count: int
    next_cursor: int
    replayed: bool = False

    def to_dict(self) -> dict[str, str | int | bool]:
        return {
            "contract_version": "1.0.0",
            "tenant_id": self.scope.tenant_id,
            "project_id": self.scope.project_id,
            "actor_id": self.scope.actor_id,
            "enabled": self.enabled,
            "can_enroll": self.can_enroll,
            "bootstrap_count": self.bootstrap_count,
            "next_cursor": self.next_cursor,
            "replayed": self.replayed,
        }


class KnowledgeSyncEnrollmentRepository(Protocol):
    async def status(self) -> KnowledgeSyncEnrollmentState: ...

    async def bootstrap(self) -> KnowledgeSyncEnrollmentState: ...
