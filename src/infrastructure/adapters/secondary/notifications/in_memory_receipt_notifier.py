"""In-memory receipt notifier adapter (Track B · P2-3 phase-2).

Captures termination receipts in-process; useful for tests and as a no-op
fallback when no external notification adapter is configured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, override

from src.domain.ports.agent.receipt_notifier import ReceiptNotifier


@dataclass
class _Delivered:
    conversation_id: str
    user_id: str
    reason: str
    rationale: str
    terminal_state: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)


class InMemoryReceiptNotifier(ReceiptNotifier):
    """Stores receipts in a list for inspection."""

    def __init__(self) -> None:
        self.delivered: list[_Delivered] = []

    @override
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
        self.delivered.append(
            _Delivered(
                conversation_id=conversation_id,
                user_id=user_id,
                reason=reason,
                rationale=rationale,
                terminal_state=dict(terminal_state),
                payload=dict(payload or {}),
            )
        )
        return True


__all__ = ["InMemoryReceiptNotifier"]
