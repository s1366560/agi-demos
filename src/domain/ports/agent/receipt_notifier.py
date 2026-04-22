"""Receipt notifier port (Track B · Agent First · P2-3 phase-2).

When a conversation terminates, the system notifies the human operator via
their configured channel (email / webhook / Feishu adapter).  The domain
exposes the minimal interface the termination service needs; concrete
implementations live in infrastructure (they fan-out to the existing user
notification chain).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ReceiptNotifier(ABC):
    """Deliver a termination receipt to the user-facing channel.

    Implementations MUST be non-blocking and MUST NOT raise — delivery
    failures are logged + retried out-of-band.  A failed notification MUST
    NOT block the conversation from finishing.
    """

    @abstractmethod
    async def deliver(
        self,
        *,
        conversation_id: str,
        user_id: str,
        reason: str,
        rationale: str,
        terminal_state: dict[str, Any],
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Deliver the receipt.

        Returns:
            True if delivery succeeded (or was queued for async delivery);
            False on permanent failure (caller logs it but does NOT retry).
        """
        ...


__all__ = ["ReceiptNotifier"]
