"""Generation-owned lifecycle for the process LLM provider health checker."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.llm.resilience.health_checker import (
    HealthChecker,
    get_health_checker,
    start_health_checker,
    stop_health_checker,
)
from src.infrastructure.persistence.llm_providers_repository import SQLAlchemyProviderRepository

from .runtime import (
    ContextV2,
    EffectResultV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

LLM_HEALTH_RUNTIME_MODULE_V2 = "builtin://memstack/runtime/llm-health-checker"
LLM_HEALTH_RUNTIME_SERVICE_V2 = "service:runtime.llm-health-checker"
LLM_HEALTH_SESSIONS_INJECT_V2 = "sessions"

type LlmHealthSessionFactoryV2 = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type LlmHealthStartV2 = Callable[[], Awaitable[None]]
type LlmHealthStopV2 = Callable[[], Awaitable[None]]
type LlmHealthSyncV2 = Callable[..., Awaitable[int]]

logger = logging.getLogger(__name__)


@runtime_checkable
class AsyncSessionFactoryProviderProtocolV2(Protocol):
    """Structural contract for the injected process session factory."""

    @property
    def factory(self) -> LlmHealthSessionFactoryV2: ...


async def sync_llm_health_checker_providers_v2(
    *,
    session_factory: LlmHealthSessionFactoryV2,
    checker: HealthChecker | None = None,
) -> int:
    """Replace the health registry with active LLM provider representatives."""
    async with session_factory() as session:
        repository = SQLAlchemyProviderRepository(session=session)
        all_active = await repository.list_active()

    providers = [
        provider
        for provider in all_active
        if provider.is_active and provider.is_enabled and provider.operation_type.value == "llm"
    ]
    providers_by_type: dict[ProviderType, list[ProviderConfig]] = defaultdict(list)
    for provider in providers:
        providers_by_type[provider.provider_type].append(provider)

    active_checker = checker or get_health_checker()
    active_types = set(providers_by_type)
    for provider_type in list(active_checker.get_current_status()):
        if provider_type not in active_types:
            active_checker.unregister_provider(provider_type)

    for provider_type, typed_providers in providers_by_type.items():
        representative = min(
            typed_providers,
            key=lambda provider: (
                0 if provider.is_default else 1,
                provider.created_at,
                str(provider.id),
            ),
        )
        active_checker.register_provider(provider_type, representative)

    registered_types = len(providers_by_type)
    logger.info(
        "Synchronized V2 LLM health checker registry with %d provider types",
        registered_types,
    )
    return registered_types


@dataclass(kw_only=True)
class LlmHealthCheckerRuntimeV2:
    """Reference-count the process health loop across overlapping generations."""

    start: LlmHealthStartV2
    sync: LlmHealthSyncV2
    stop: LlmHealthStopV2
    _generation_references: int = 0
    _registered_provider_types: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def generation_references(self) -> int:
        return self._generation_references

    @property
    def registered_provider_types(self) -> int:
        return self._registered_provider_types

    async def acquire_generation(
        self,
        *,
        sessions: AsyncSessionFactoryProviderProtocolV2,
    ) -> None:
        """Hydrate and start only for the first staged generation."""
        async with self._lock:
            if self._generation_references > 0:
                self._generation_references += 1
                return

            start_attempted = False
            try:
                self._registered_provider_types = await self.sync(session_factory=sessions.factory)
                start_attempted = True
                await self.start()
            except BaseException:
                self._registered_provider_types = 0
                if start_attempted:
                    try:
                        await self.stop()
                    except Exception:
                        logger.exception("Failed to clean up LLM health checker candidate")
                raise
            self._generation_references = 1

    async def release_generation(self) -> None:
        """Stop only after every active or draining generation releases the effect."""
        async with self._lock:
            if self._generation_references <= 0:
                raise RuntimeV2Error(
                    "llm_health_checker_reference_underflow",
                    "LLM health checker generation reference count underflow",
                )
            self._generation_references -= 1
            if self._generation_references != 0:
                return
            await self.stop()
            self._registered_provider_types = 0


def llm_health_runtime_definition_v2() -> PluginDefinitionV2:
    """Bind provider synchronization and health polling to a V2 effect."""
    runtime = LlmHealthCheckerRuntimeV2(
        start=start_health_checker,
        sync=sync_llm_health_checker_providers_v2,
        stop=stop_health_checker,
    )

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> EffectResultV2:
        if config.get("strategy") != "resilience-health-checker":
            raise ValueError("LLM health runtime requires strategy resilience-health-checker")
        sessions = context.require(LLM_HEALTH_SESSIONS_INJECT_V2)
        if not isinstance(sessions, AsyncSessionFactoryProviderProtocolV2):
            raise RuntimeV2Error(
                "invalid_llm_health_sessions",
                "LLM health checker sessions inject has an invalid implementation",
            )
        await runtime.acquire_generation(sessions=sessions)
        try:
            _ = context.provide(
                LLM_HEALTH_RUNTIME_SERVICE_V2,
                runtime,
                label="llm-health-checker",
            )
        except Exception:
            await runtime.release_generation()
            raise

        async def dispose() -> None:
            await runtime.release_generation()

        return dispose

    return PluginDefinitionV2(
        module_ref=LLM_HEALTH_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(LLM_HEALTH_RUNTIME_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "LLM_HEALTH_RUNTIME_MODULE_V2",
    "LLM_HEALTH_RUNTIME_SERVICE_V2",
    "LLM_HEALTH_SESSIONS_INJECT_V2",
    "AsyncSessionFactoryProviderProtocolV2",
    "LlmHealthCheckerRuntimeV2",
    "LlmHealthSessionFactoryV2",
    "llm_health_runtime_definition_v2",
    "sync_llm_health_checker_providers_v2",
]
