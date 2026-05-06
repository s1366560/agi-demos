"""Execution lease repository port.

Implementations:
- ``RedisExecutionLeaseRepository`` (production: SET NX EX with instance id)
- ``InMemoryExecutionLeaseRepository`` (tests + local dev)

Multi-tenancy: leases are scoped by ``project_id``; callers must always pass it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.model.recovery.lease import ExecutionLease


class ExecutionLeaseRepository(ABC):
    """Holder of execution leases."""

    @abstractmethod
    async def get(self, *, project_id: str, task_id: str) -> ExecutionLease | None:
        """Return the current lease for a task, if any."""

    @abstractmethod
    async def upsert(self, *, project_id: str, lease: ExecutionLease) -> None:
        """Replace or insert the lease for a task."""

    @abstractmethod
    async def release(self, *, project_id: str, task_id: str) -> None:
        """Drop the lease (used when reconciliation marks a foreign lease dead)."""

    @abstractmethod
    async def list_running(self, *, project_id: str) -> list[ExecutionLease]:
        """Return every active lease in the project (for the recovery scanner)."""
