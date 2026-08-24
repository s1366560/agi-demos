"""Generation-owned process lifecycle for Docker sandbox event monitoring."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.sandbox_status_sync_service import SandboxStatusSyncService
from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
    SqlProjectSandboxRepository,
)
from src.infrastructure.adapters.secondary.sandbox.docker_event_monitor import (
    start_docker_event_monitor,
    stop_docker_event_monitor,
)

from .runtime import (
    ContextV2,
    EffectResultV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .sandbox_runtime import SandboxApplicationResolverProtocolV2, SandboxApplicationServicesV2

DOCKER_EVENT_MONITOR_MODULE_V2 = "builtin://memstack/runtime/docker-event-monitor"
DOCKER_EVENT_MONITOR_SERVICE_V2 = "service:runtime.docker-event-monitor"
DOCKER_EVENT_MONITOR_SESSIONS_INJECT_V2 = "sessions"
DOCKER_EVENT_MONITOR_SANDBOX_INJECT_V2 = "sandbox"

_DOCKER_SERVICES_ENABLED_ENV_V2 = "SANDBOX_DOCKER_SERVICES_ENABLED"

logger = logging.getLogger(__name__)

type DockerMonitorSessionFactoryV2 = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type DockerMonitorStartV2 = Callable[..., Awaitable[object]]
type DockerMonitorStopV2 = Callable[[], Awaitable[None]]


@runtime_checkable
class AsyncSessionFactoryProviderProtocolV2(Protocol):
    """Structural contract for the injected process session factory."""

    @property
    def factory(self) -> DockerMonitorSessionFactoryV2: ...


def _sandbox_resolver_registry_v2() -> dict[int, SandboxApplicationResolverProtocolV2]:
    return {}


@dataclass(frozen=True, kw_only=True)
class DockerEventMonitorConfigV2:
    """Process-boundary monitor settings after environment projection."""

    enabled: bool


@dataclass(kw_only=True)
class DockerEventMonitorRuntimeV2:
    """Own one Docker monitor while one or more generations reference it."""

    start: DockerMonitorStartV2
    stop: DockerMonitorStopV2
    _monitor: object | None = None
    _config: DockerEventMonitorConfigV2 | None = None
    _session_factory: DockerMonitorSessionFactoryV2 | None = None
    _sandbox_by_token: dict[int, SandboxApplicationResolverProtocolV2] = field(
        default_factory=_sandbox_resolver_registry_v2
    )
    _next_token: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def generation_references(self) -> int:
        return len(self._sandbox_by_token)

    @property
    def monitor(self) -> object | None:
        return self._monitor

    async def acquire_generation(
        self,
        *,
        sessions: AsyncSessionFactoryProviderProtocolV2,
        sandbox: SandboxApplicationResolverProtocolV2,
        config: DockerEventMonitorConfigV2,
    ) -> int:
        """Register one generation and start the process monitor only once."""
        async with self._lock:
            if self._sandbox_by_token and self._config != config:
                raise RuntimeV2Error(
                    "docker_monitor_process_boundary_mismatch",
                    "Docker event monitor config changed inside a process boundary",
                )

            self._next_token += 1
            token = self._next_token
            self._sandbox_by_token[token] = sandbox
            self._session_factory = sessions.factory
            if len(self._sandbox_by_token) > 1:
                return token

            self._config = config
            if not config.enabled:
                return token

            start_attempted = False
            try:
                start_attempted = True
                self._monitor = await self.start(on_status_change=self.handle_status_change)
            except BaseException:
                if start_attempted:
                    try:
                        await self.stop()
                    except Exception:
                        logger.exception("Failed to clean up Docker monitor candidate")
                self._monitor = None
                self._config = None
                self._session_factory = None
                _ = self._sandbox_by_token.pop(token, None)
                raise
            return token

    async def release_generation(self, token: int) -> None:
        """Release one generation and stop after the final registration drains."""
        async with self._lock:
            if token not in self._sandbox_by_token:
                raise RuntimeV2Error(
                    "docker_monitor_reference_underflow",
                    "Docker event monitor generation reference is not active",
                )
            _ = self._sandbox_by_token.pop(token)
            if self._sandbox_by_token:
                return
            try:
                if self._monitor is not None:
                    await self.stop()
            finally:
                self._monitor = None
                self._config = None
                self._session_factory = None

    async def handle_status_change(
        self,
        project_id: str,
        sandbox_id: str,
        new_status: str,
        event_type: str,
    ) -> bool:
        """Resolve the event publisher from the current exact generation."""
        from .boundary import current_process_generation_host_v2, pin_generation_v2
        from .sandbox_projection import current_sandbox_application_services_v2

        session_factory = self._session_factory
        fallback = next(reversed(self._sandbox_by_token.values()), None)
        if session_factory is None or fallback is None:
            raise RuntimeV2Error(
                "docker_monitor_runtime_unavailable",
                "Docker event monitor has no active generation dependencies",
            )

        try:
            host = current_process_generation_host_v2()
        except RuntimeV2Error as error:
            if error.code != "process_generation_host_not_configured":
                raise
            return await _synchronize_status_v2(
                session_factory=session_factory,
                services=fallback.resolve(),
                project_id=project_id,
                sandbox_id=sandbox_id,
                new_status=new_status,
                event_type=event_type,
            )

        async with pin_generation_v2(host):
            return await _synchronize_status_v2(
                session_factory=session_factory,
                services=current_sandbox_application_services_v2(),
                project_id=project_id,
                sandbox_id=sandbox_id,
                new_status=new_status,
                event_type=event_type,
            )


async def _synchronize_status_v2(
    *,
    session_factory: DockerMonitorSessionFactoryV2,
    services: SandboxApplicationServicesV2,
    project_id: str,
    sandbox_id: str,
    new_status: str,
    event_type: str,
) -> bool:
    @asynccontextmanager
    async def sandbox_repository_factory() -> AsyncIterator[SqlProjectSandboxRepository]:
        async with session_factory() as session:
            yield SqlProjectSandboxRepository(session)

    sync_service = SandboxStatusSyncService(
        repository_factory=sandbox_repository_factory,
        event_publisher=services.event_publisher,
    )
    return await sync_service.handle_status_change(
        project_id,
        sandbox_id,
        new_status,
        event_type,
    )


def _docker_monitor_config_v2(config: Mapping[str, Any]) -> DockerEventMonitorConfigV2:
    if config.get("strategy") != "docker-events":
        raise ValueError("Docker event monitor requires strategy docker-events")
    enabled = config.get("enabled")
    environment_overrides = config.get("environment_overrides")
    if not isinstance(enabled, bool):
        raise ValueError("Docker event monitor enabled must be a boolean")
    if not isinstance(environment_overrides, bool):
        raise ValueError("Docker event monitor environment_overrides must be a boolean")
    if environment_overrides:
        raw_enabled = os.environ.get(_DOCKER_SERVICES_ENABLED_ENV_V2)
        if raw_enabled is not None:
            enabled = raw_enabled.strip().casefold() in {"1", "true", "yes", "on"}
    return DockerEventMonitorConfigV2(enabled=enabled)


def docker_event_monitor_definition_v2() -> PluginDefinitionV2:
    """Bind Docker event monitoring to one reversible process-boundary effect."""
    runtime = DockerEventMonitorRuntimeV2(
        start=start_docker_event_monitor,
        stop=stop_docker_event_monitor,
    )

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> EffectResultV2:
        sessions = context.require(DOCKER_EVENT_MONITOR_SESSIONS_INJECT_V2)
        if not isinstance(sessions, AsyncSessionFactoryProviderProtocolV2):
            raise RuntimeV2Error(
                "invalid_docker_monitor_sessions",
                "Docker event monitor sessions inject has an invalid implementation",
            )
        sandbox = context.require(DOCKER_EVENT_MONITOR_SANDBOX_INJECT_V2)
        if not isinstance(sandbox, SandboxApplicationResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_docker_monitor_sandbox",
                "Docker event monitor sandbox inject has an invalid implementation",
            )
        token = await runtime.acquire_generation(
            sessions=sessions,
            sandbox=sandbox,
            config=_docker_monitor_config_v2(config),
        )
        try:
            _ = context.provide(
                DOCKER_EVENT_MONITOR_SERVICE_V2,
                runtime,
                label="docker-event-monitor",
            )
        except Exception:
            await runtime.release_generation(token)
            raise

        async def dispose() -> None:
            await runtime.release_generation(token)

        return dispose

    return PluginDefinitionV2(
        module_ref=DOCKER_EVENT_MONITOR_MODULE_V2,
        contract_digest=generated_contract_digest_v2(DOCKER_EVENT_MONITOR_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "DOCKER_EVENT_MONITOR_MODULE_V2",
    "DOCKER_EVENT_MONITOR_SANDBOX_INJECT_V2",
    "DOCKER_EVENT_MONITOR_SERVICE_V2",
    "DOCKER_EVENT_MONITOR_SESSIONS_INJECT_V2",
    "AsyncSessionFactoryProviderProtocolV2",
    "DockerEventMonitorConfigV2",
    "DockerEventMonitorRuntimeV2",
    "DockerMonitorSessionFactoryV2",
    "docker_event_monitor_definition_v2",
]
