"""Composable guard chain for pre-compression context sanitation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class ContextGuard(Protocol):
    """Protocol for context guards."""

    name: str

    def apply(
        self,
        messages: list[dict[str, Any]],
        *,
        estimate_message_tokens: Callable[[dict[str, Any]], int],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Apply guard transformation."""
        ...


@dataclass
class GuardChainResult:
    """Result of guard-chain execution."""

    messages: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


class ContextGuardChain:
    """Run context guards sequentially and aggregate diagnostics."""

    def __init__(self, guards: list[ContextGuard] | None = None) -> None:
        self._guards = guards or []

    @property
    def guards(self) -> list[ContextGuard]:
        return list(self._guards)

    def apply(
        self,
        messages: list[dict[str, Any]],
        *,
        estimate_message_tokens: Callable[[dict[str, Any]], int],
    ) -> GuardChainResult:
        current = list(messages)
        metadata: dict[str, Any] = {
            "applied_guards": [],
            "modified_messages": 0,
            "details": {},
        }

        for guard in self._guards:
            try:
                current, guard_meta = guard.apply(
                    current,
                    estimate_message_tokens=estimate_message_tokens,
                )
            except Exception as exc:
                logger.warning("[ContextGuardChain] Guard %s failed: %s", guard.name, exc)
                metadata["details"][guard.name] = {"error": str(exc)}
                continue

            modified_messages = int(guard_meta.get("modified_messages", 0))
            metadata["applied_guards"].append(guard.name)
            metadata["modified_messages"] += max(0, modified_messages)
            metadata["details"][guard.name] = guard_meta

        return GuardChainResult(messages=current, metadata=metadata)

