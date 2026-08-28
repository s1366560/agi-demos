"""Generation-owned process lifecycle for the Skill Evolution scheduler."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.plugins.skill_evolution.config import SkillEvolutionConfig
from src.infrastructure.agent.plugins.skill_evolution.plugin import (
    build_skill_evolution_runtime,
)

from .llm_client_service import (
    TenantLlmClientFactoryProtocolV2,
    lease_tenant_llm_client_v2,
)
from .runtime import (
    ContextV2,
    EffectResultV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SKILL_EVOLUTION_RUNTIME_MODULE_V2 = "builtin://memstack/runtime/skill-evolution-scheduler"
SKILL_EVOLUTION_RUNTIME_SERVICE_V2 = "service:runtime.skill-evolution-scheduler"
SKILL_EVOLUTION_SESSIONS_INJECT_V2 = "sessions"
SKILL_EVOLUTION_LLM_CLIENTS_INJECT_V2 = "llm_clients"

_ENABLED_ENV_V2 = "SKILL_EVOLUTION_ENABLED"

logger = logging.getLogger(__name__)

type SkillEvolutionSessionFactoryV2 = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type SkillEvolutionRuntimeBuilderV2 = Callable[..., object]


@runtime_checkable
class AsyncSessionFactoryProviderProtocolV2(Protocol):
    """Structural contract for the injected process session factory."""

    @property
    def factory(self) -> SkillEvolutionSessionFactoryV2: ...


@runtime_checkable
class SkillEvolutionPluginProtocolV2(Protocol):
    """Lifecycle and management surface owned by the V2 runtime effect."""

    async def on_enable(self) -> None: ...

    async def on_disable(self) -> None: ...

    async def record_tool_event(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    async def capture_turn(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def schedule_evolution(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        skill_name: str | None = None,
        reason: str = "manual",
    ) -> dict[str, Any]: ...


@runtime_checkable
class SkillEvolutionSchedulerProtocolV2(Protocol):
    """Consumer-visible scheduler contract; callers never name the implementation."""

    async def record_tool_event(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    async def capture_turn(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...

    def schedule_evolution(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        skill_name: str | None = None,
        reason: str = "manual",
    ) -> dict[str, Any]: ...


def _llm_client_registry_v2() -> dict[int, TenantLlmClientFactoryProtocolV2]:
    return {}


@dataclass(kw_only=True)
class SkillEvolutionSchedulerRuntimeV2:
    """Own one scheduler while active and draining generations overlap."""

    build: SkillEvolutionRuntimeBuilderV2
    _plugin: SkillEvolutionPluginProtocolV2 | None = None
    _config: SkillEvolutionConfig | None = None
    _session_factory: SkillEvolutionSessionFactoryV2 | None = None
    _llm_clients_by_token: dict[int, TenantLlmClientFactoryProtocolV2] = field(
        default_factory=_llm_client_registry_v2
    )
    _next_token: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def generation_references(self) -> int:
        return len(self._llm_clients_by_token)

    @property
    def plugin(self) -> SkillEvolutionPluginProtocolV2 | None:
        return self._plugin

    async def acquire_generation(
        self,
        *,
        sessions: AsyncSessionFactoryProviderProtocolV2,
        llm_clients: TenantLlmClientFactoryProtocolV2,
        config: SkillEvolutionConfig,
    ) -> int:
        """Register one generation and start the process scheduler only once."""
        async with self._lock:
            if self._llm_clients_by_token:
                if self._config != config or self._session_factory is not sessions.factory:
                    raise RuntimeV2Error(
                        "skill_evolution_process_boundary_mismatch",
                        "Skill Evolution config or session factory changed inside a process boundary",
                    )
                self._next_token += 1
                token = self._next_token
                self._llm_clients_by_token[token] = llm_clients
                return token

            self._next_token += 1
            token = self._next_token
            self._llm_clients_by_token[token] = llm_clients
            self._config = config
            self._session_factory = sessions.factory
            try:
                plugin = self.build(
                    config=config,
                    skill_service=None,
                    llm_client_lease=lease_tenant_llm_client_v2,
                    session_factory=sessions.factory,
                )
                if not isinstance(plugin, SkillEvolutionPluginProtocolV2):
                    raise RuntimeV2Error(
                        "invalid_skill_evolution_runtime",
                        "Skill Evolution builder returned an invalid runtime",
                    )
                self._plugin = plugin
                await plugin.on_enable()
            except BaseException:
                plugin = self._plugin
                if plugin is not None:
                    try:
                        await plugin.on_disable()
                    except Exception:
                        logger.exception("Failed to clean up Skill Evolution candidate")
                self._plugin = None
                self._config = None
                self._session_factory = None
                _ = self._llm_clients_by_token.pop(token, None)
                raise
            return token

    async def release_generation(self, token: int) -> None:
        """Stop the scheduler after the final active or draining generation releases it."""
        async with self._lock:
            if token not in self._llm_clients_by_token:
                raise RuntimeV2Error(
                    "skill_evolution_reference_underflow",
                    "Skill Evolution generation reference is not active",
                )
            _ = self._llm_clients_by_token.pop(token)
            if self._llm_clients_by_token:
                return
            plugin = self._plugin
            try:
                if plugin is not None:
                    await plugin.on_disable()
            finally:
                self._plugin = None
                self._config = None
                self._session_factory = None

    async def record_tool_event(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Record one observation through the active generation-owned plugin."""
        plugin = self._plugin
        if plugin is None:
            raise RuntimeV2Error(
                "skill_evolution_runtime_unavailable",
                "Skill Evolution runtime has no active generation",
            )
        return await plugin.record_tool_event(payload)

    async def capture_turn(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Capture one completed turn through the active generation-owned plugin."""
        plugin = self._plugin
        if plugin is None:
            raise RuntimeV2Error(
                "skill_evolution_runtime_unavailable",
                "Skill Evolution runtime has no active generation",
            )
        return await plugin.capture_turn(payload)

    def schedule_evolution(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        skill_name: str | None = None,
        reason: str = "manual",
    ) -> dict[str, Any]:
        """Queue work only through the generation-owned scheduler instance."""
        plugin = self._plugin
        if plugin is None:
            raise RuntimeV2Error(
                "skill_evolution_runtime_unavailable",
                "Skill Evolution scheduler has no active generation",
            )
        return plugin.schedule_evolution(
            tenant_id=tenant_id,
            project_id=project_id,
            skill_name=skill_name,
            reason=reason,
        )


def _skill_evolution_config_v2(config: Mapping[str, Any]) -> SkillEvolutionConfig:
    if config.get("strategy") != "periodic-skill-evolution":
        raise ValueError("Skill Evolution requires strategy periodic-skill-evolution")
    enabled = config.get("enabled")
    environment_overrides = config.get("environment_overrides")
    if not isinstance(enabled, bool):
        raise ValueError("Skill Evolution enabled must be a boolean")
    if not isinstance(environment_overrides, bool):
        raise ValueError("Skill Evolution environment_overrides must be a boolean")

    resolved = SkillEvolutionConfig.from_env() if environment_overrides else SkillEvolutionConfig()
    if not environment_overrides or _ENABLED_ENV_V2 not in os.environ:
        resolved = replace(resolved, enabled=enabled)
    return resolved


def skill_evolution_scheduler_definition_v2(
    builder: SkillEvolutionRuntimeBuilderV2 | None = None,
) -> PluginDefinitionV2:
    """Bind capture scheduling and periodic evolution to one reversible effect."""
    runtime = SkillEvolutionSchedulerRuntimeV2(
        build=builder or build_skill_evolution_runtime,
    )

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> EffectResultV2:
        sessions = context.require(SKILL_EVOLUTION_SESSIONS_INJECT_V2)
        if not isinstance(sessions, AsyncSessionFactoryProviderProtocolV2):
            raise RuntimeV2Error(
                "invalid_skill_evolution_sessions",
                "Skill Evolution sessions inject has an invalid implementation",
            )
        llm_clients = context.require(SKILL_EVOLUTION_LLM_CLIENTS_INJECT_V2)
        if not isinstance(llm_clients, TenantLlmClientFactoryProtocolV2):
            raise RuntimeV2Error(
                "invalid_skill_evolution_llm_clients",
                "Skill Evolution LLM client inject has an invalid implementation",
            )
        token = await runtime.acquire_generation(
            sessions=sessions,
            llm_clients=llm_clients,
            config=_skill_evolution_config_v2(config),
        )
        try:
            _ = context.provide(
                SKILL_EVOLUTION_RUNTIME_SERVICE_V2,
                runtime,
                label="skill-evolution-scheduler",
            )
        except Exception:
            await runtime.release_generation(token)
            raise

        async def dispose() -> None:
            await runtime.release_generation(token)

        return dispose

    return PluginDefinitionV2(
        module_ref=SKILL_EVOLUTION_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SKILL_EVOLUTION_RUNTIME_MODULE_V2),
        apply=apply,
    )


def current_skill_evolution_scheduler_v2() -> SkillEvolutionSchedulerProtocolV2:
    """Resolve the scheduler from the immutable generation pinned to this request."""
    from .boundary import current_generation_v2

    runtime = current_generation_v2().resolve(
        SKILL_EVOLUTION_RUNTIME_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    if not isinstance(runtime, SkillEvolutionSchedulerProtocolV2):
        raise RuntimeV2Error(
            "invalid_skill_evolution_runtime",
            "Resolved Skill Evolution service has an invalid implementation",
        )
    return runtime


__all__ = [
    "SKILL_EVOLUTION_LLM_CLIENTS_INJECT_V2",
    "SKILL_EVOLUTION_RUNTIME_MODULE_V2",
    "SKILL_EVOLUTION_RUNTIME_SERVICE_V2",
    "SKILL_EVOLUTION_SESSIONS_INJECT_V2",
    "AsyncSessionFactoryProviderProtocolV2",
    "SkillEvolutionPluginProtocolV2",
    "SkillEvolutionRuntimeBuilderV2",
    "SkillEvolutionSchedulerProtocolV2",
    "SkillEvolutionSchedulerRuntimeV2",
    "SkillEvolutionSessionFactoryV2",
    "current_skill_evolution_scheduler_v2",
    "skill_evolution_scheduler_definition_v2",
]
