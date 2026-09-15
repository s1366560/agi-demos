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
from .plugin_config_repository_lease_v2 import lease_plugin_config_repository_v2
from .plugin_config_services import PluginConfigApplicationResolverProtocolV2
from .runtime import (
    ContextV2,
    EffectResultV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .skill_evolution_repository_lease_v2 import lease_skill_evolution_repository_v2
from .skill_evolution_repository_services import (
    SkillEvolutionRepositoryApplicationResolverProtocolV2,
)
from .skill_repository_services import SkillRepositoryApplicationResolverProtocolV2

SKILL_EVOLUTION_RUNTIME_MODULE_V2 = "builtin://memstack/runtime/skill-evolution-scheduler"
SKILL_EVOLUTION_RUNTIME_SERVICE_V2 = "service:runtime.skill-evolution-scheduler"
SKILL_EVOLUTION_SESSIONS_INJECT_V2 = "sessions"
SKILL_EVOLUTION_LLM_CLIENTS_INJECT_V2 = "llm_clients"
SKILL_EVOLUTION_PLUGIN_CONFIGS_INJECT_V2 = "plugin_configs"
SKILL_EVOLUTION_REPOSITORIES_INJECT_V2 = "repositories"
SKILL_EVOLUTION_SKILLS_INJECT_V2 = "skills"

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


@runtime_checkable
class SkillEvolutionActivationProtocolV2(Protocol):
    """Explicit process admission, separate from the consumer contract."""

    async def activate(self, operation: OperationContextV2) -> None: ...


@dataclass(frozen=True)
class SkillEvolutionGenerationSchedulerV2:
    """A candidate cannot consume through another generation's activation."""

    runtime: SkillEvolutionSchedulerRuntimeV2
    token: int

    async def activate(self, operation: OperationContextV2) -> None:
        service = SKILL_EVOLUTION_RUNTIME_SERVICE_V2
        if (
            operation.require(service) is not self
            or operation.generation.resolve(service, ScopeV2(kind=ScopeKindV2.ROOT)) is not self
        ):
            raise RuntimeV2Error(
                "skill_evolution_activation_mismatch", "Activation belongs to another generation"
            )
        await self.runtime.activate_generation(self.token)

    def _require_active(self) -> None:
        self.runtime.require_activated_generation(self.token)

    def _require_capture(self, payload: Mapping[str, Any]) -> None:
        from .skill_evolution_capture_admission_v2 import require_worker_skill_capture_v2

        if self.token not in self.runtime._activated_tokens:
            require_worker_skill_capture_v2(self, payload)

    async def record_tool_event(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self._require_capture(payload)
        return await self.runtime.record_tool_event(payload)

    async def capture_turn(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self._require_capture(payload)
        return await self.runtime.capture_turn(payload)

    def schedule_evolution(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        skill_name: str | None = None,
        reason: str = "manual",
    ) -> dict[str, Any]:
        self._require_active()
        return self.runtime.schedule_evolution(
            tenant_id=tenant_id, project_id=project_id, skill_name=skill_name, reason=reason
        )


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
    _activated_tokens: set[int] = field(default_factory=lambda: set[int]())
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
        """Register a paused candidate without starting background work."""
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
                    plugin_config_repository_lease=lease_plugin_config_repository_v2,
                    skill_evolution_repository_lease=(lease_skill_evolution_repository_v2),
                )
                if not isinstance(plugin, SkillEvolutionPluginProtocolV2):
                    raise RuntimeV2Error(
                        "invalid_skill_evolution_runtime",
                        "Skill Evolution builder returned an invalid runtime",
                    )
                self._plugin = plugin
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

    def require_activated_generation(self, token: int) -> None:
        """Reject consumers belonging to an unadmitted or retired generation."""
        if token not in self._activated_tokens:
            raise RuntimeV2Error(
                "skill_evolution_runtime_unavailable", "Skill Evolution generation is not admitted"
            )

    async def activate_generation(self, token: int) -> None:
        """Start only after the owner has durably admitted this generation."""
        async with self._lock:
            if token not in self._llm_clients_by_token or self._plugin is None:
                raise RuntimeV2Error(
                    "skill_evolution_runtime_unavailable", "Generation has already retired"
                )
            if token in self._activated_tokens:
                return
            if not self._activated_tokens:
                try:
                    await self._plugin.on_enable()
                except BaseException as error:
                    try:
                        await self._plugin.on_disable()
                    except BaseException as cleanup_error:
                        raise BaseExceptionGroup(
                            "Skill Evolution activation and cleanup failed", [error, cleanup_error]
                        ) from None
                    raise
            self._activated_tokens.add(token)

    async def release_generation(self, token: int) -> None:
        """Paused candidates do not retain an activated scheduler's lifetime."""
        async with self._lock:
            if token not in self._llm_clients_by_token:
                raise RuntimeV2Error(
                    "skill_evolution_reference_underflow",
                    "Skill Evolution generation reference is not active",
                )
            _ = self._llm_clients_by_token.pop(token)
            was_active = token in self._activated_tokens
            self._activated_tokens.discard(token)
            try:
                if was_active and not self._activated_tokens and self._plugin is not None:
                    await self._plugin.on_disable()
            finally:
                if not self._llm_clients_by_token:
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
        plugin_configs = context.require(SKILL_EVOLUTION_PLUGIN_CONFIGS_INJECT_V2)
        if not isinstance(plugin_configs, PluginConfigApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_skill_evolution_plugin_configs",
                "Skill Evolution plugin config inject has an invalid implementation",
            )
        repositories = context.require(SKILL_EVOLUTION_REPOSITORIES_INJECT_V2)
        if not isinstance(
            repositories,
            SkillEvolutionRepositoryApplicationResolverProtocolV2,
        ):
            raise RuntimeV2Error(
                "invalid_skill_evolution_repositories",
                "Skill Evolution repositories inject has an invalid implementation",
            )
        skills = context.require(SKILL_EVOLUTION_SKILLS_INJECT_V2)
        if not isinstance(skills, SkillRepositoryApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_skill_evolution_skills",
                "Skill Evolution Skill repositories inject has an invalid implementation",
            )
        token = await runtime.acquire_generation(
            sessions=sessions,
            llm_clients=llm_clients,
            config=_skill_evolution_config_v2(config),
        )
        try:
            _ = context.provide(
                SKILL_EVOLUTION_RUNTIME_SERVICE_V2,
                SkillEvolutionGenerationSchedulerV2(runtime, token),
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
    "SKILL_EVOLUTION_PLUGIN_CONFIGS_INJECT_V2",
    "SKILL_EVOLUTION_REPOSITORIES_INJECT_V2",
    "SKILL_EVOLUTION_RUNTIME_MODULE_V2",
    "SKILL_EVOLUTION_RUNTIME_SERVICE_V2",
    "SKILL_EVOLUTION_SESSIONS_INJECT_V2",
    "SKILL_EVOLUTION_SKILLS_INJECT_V2",
    "AsyncSessionFactoryProviderProtocolV2",
    "SkillEvolutionActivationProtocolV2",
    "SkillEvolutionGenerationSchedulerV2",
    "SkillEvolutionPluginProtocolV2",
    "SkillEvolutionRuntimeBuilderV2",
    "SkillEvolutionSchedulerProtocolV2",
    "SkillEvolutionSchedulerRuntimeV2",
    "SkillEvolutionSessionFactoryV2",
    "current_skill_evolution_scheduler_v2",
    "skill_evolution_scheduler_definition_v2",
]
