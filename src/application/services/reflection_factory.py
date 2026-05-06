"""Factories that wire ``ReflectionService`` and ``ReflectionRunner`` from DI.

These live in the application layer so the DI container can stay thin and
infrastructure choices (Redis vs in-memory ledger, LiteLLM vs stub
completion) remain swappable per call site.
"""

from __future__ import annotations

import logging
from typing import Any

from src.application.services.reflection_service import ReflectionService
from src.domain.ports.repositories.friction_ledger import FrictionLedger
from src.domain.ports.repositories.playbook_repository import PlaybookRepository
from src.domain.ports.services.reflector_port import ReflectorPort
from src.infrastructure.adapters.secondary.in_memory.friction_loop import (
    InMemoryFrictionLedger,
    InMemoryPlaybookRepository,
)
from src.infrastructure.adapters.secondary.llm_reflector import LLMReflector

logger = logging.getLogger(__name__)


def build_reflection_service(
    *,
    ledger: FrictionLedger,
    playbooks: PlaybookRepository,
    reflector: ReflectorPort,
    window_minutes: int = 60 * 24,
) -> ReflectionService:
    """Assemble a ``ReflectionService`` from already-built ports."""
    return ReflectionService(
        ledger=ledger,
        playbooks=playbooks,
        reflector=reflector,
        window_minutes=window_minutes,
    )


def default_in_memory_playbooks() -> InMemoryPlaybookRepository:
    """Return a process-singleton in-memory playbook repository.

    Used until ``SqlPlaybookRepository`` ships. Holds verdicts only for the
    lifetime of this process — restart wipes learned playbooks.
    """
    global _default_playbooks
    if _default_playbooks is None:
        _default_playbooks = InMemoryPlaybookRepository()
    return _default_playbooks


_default_playbooks: InMemoryPlaybookRepository | None = None


def default_in_memory_ledger() -> InMemoryFrictionLedger:
    """Return a process-singleton in-memory friction ledger.

    Fallback when no Redis client is available (tests, local dev with
    ``REDIS_URL`` unset). Production should use ``RedisFrictionLedger``.
    """
    global _default_ledger
    if _default_ledger is None:
        _default_ledger = InMemoryFrictionLedger()
    return _default_ledger


_default_ledger: InMemoryFrictionLedger | None = None


def build_litellm_reflector(litellm_client: Any) -> LLMReflector:  # noqa: ANN401
    """Wrap a ``LiteLLMClient`` so it satisfies ``LLMCompletion``.

    ``LiteLLMClient.generate`` does not accept ``response_format``; we adapt
    by ignoring it. The system prompt in ``LLMReflector`` already requests
    JSON, and the adapter validates structurally before returning verdicts.
    """

    async def _completion(
        *,
        messages: list[dict[str, str]],
        response_format: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        del response_format  # not supported by LiteLLMClient.generate
        return await litellm_client.generate(messages=messages)

    return LLMReflector(completion=_completion)


__all__ = [
    "build_litellm_reflector",
    "build_reflection_service",
    "default_in_memory_ledger",
    "default_in_memory_playbooks",
]
