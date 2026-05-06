"""Friction Ledger port — append-only sink + windowed query for friction
signals.

Implementations: see ``infrastructure.adapters.secondary.cache``
(``RedisFrictionLedger``) and ``infrastructure.adapters.secondary.in_memory``
(``InMemoryFrictionLedger``, used in tests).

Multi-tenancy: every query MUST be scoped by ``project_id``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.domain.model.flow.friction_signal import FrictionSignal


class FrictionLedger(ABC):
    """Append-only sink + read window for friction signals."""

    @abstractmethod
    async def append(self, signal: FrictionSignal) -> None:
        """Persist a single friction signal. Idempotency is implementation-defined."""

    @abstractmethod
    async def query_window(
        self,
        project_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[FrictionSignal]:
        """Return signals for a project within an optional time window.

        Returned in ``observed_at`` ascending order. ``limit`` caps the result
        set; callers must be prepared to paginate by narrowing the window.
        """
