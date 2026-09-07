"""Generation-owned process lifecycle for IM channel long connections."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any, NoReturn, Protocol, cast, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.channels.message import Message
from src.infrastructure.adapters.secondary.persistence.channel_models import ChannelConfigModel
from src.infrastructure.channels.connection_manager import (
    ChannelAdapterResolverLeaseFactoryV2,
    ChannelAdapterResolverLeaseProtocolV2,
    ChannelConnectionManager,
    ManagedConnection,
)

from .channel_adapters import ChannelAdapterResolverProtocolV2
from .runtime import (
    ContextV2,
    EffectResultV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CHANNEL_RUNTIME_MODULE_V2 = "builtin://memstack/runtime/channel-manager"
CHANNEL_RUNTIME_SERVICE_V2 = "service:runtime.channel-manager"
CHANNEL_RUNTIME_SESSIONS_INJECT_V2 = "sessions"
CHANNEL_RUNTIME_ADAPTERS_INJECT_V2 = "adapters"

logger = logging.getLogger(__name__)

type ChannelRuntimeSessionFactoryV2 = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type ChannelConnectionManagerFactoryV2 = Callable[..., ChannelConnectionManager]


@runtime_checkable
class AsyncSessionFactoryProviderProtocolV2(Protocol):
    """Structural contract for the injected process session factory."""

    @property
    def factory(self) -> ChannelRuntimeSessionFactoryV2: ...


@dataclass(frozen=True, kw_only=True)
class ChannelRuntimeConfigV2:
    """Process channel runtime settings projected from one Profile entry."""

    strict_startup: bool


@runtime_checkable
class ChannelRuntimeServiceProtocolV2(Protocol):
    """Consumer contract for generation-pinned channel runtime operations."""

    @property
    def connections(self) -> dict[str, ManagedConnection]: ...

    async def add_connection(self, config: ChannelConfigModel) -> ManagedConnection: ...

    async def restart_connection(self, config_id: str) -> bool: ...

    async def remove_connection(self, config_id: str) -> bool: ...

    async def build_adapter(self, config: ChannelConfigModel) -> object: ...

    def get_status(self, config_id: str) -> dict[str, Any] | None: ...

    def get_all_status(self) -> list[dict[str, Any]]: ...


@dataclass(kw_only=True)
class _ResolverRegistrationV2:
    resolver: ChannelAdapterResolverProtocolV2
    generation_active: bool = True
    connection_leases: int = 0


@dataclass(kw_only=True)
class ChannelAdapterResolverLeaseV2:
    """Reference-counted lease for one generation's immutable adapter resolver."""

    runtime: ChannelRuntimeManagerV2
    generation_token: int
    resolver: ChannelAdapterResolverProtocolV2
    _released: bool = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self.runtime.release_connection(self.generation_token)


@dataclass(frozen=True, kw_only=True)
class ChannelRuntimeServiceV2:
    """Generation-scoped facade over the shared process connection manager."""

    runtime: ChannelRuntimeManagerV2
    generation_token: int

    @property
    def connections(self) -> dict[str, ManagedConnection]:
        return self._manager().connections

    async def add_connection(self, config: ChannelConfigModel) -> ManagedConnection:
        return await self._manager().add_connection(
            config,
            resolver_lease_factory=self._lease_factory(),
        )

    async def restart_connection(self, config_id: str) -> bool:
        return await self._manager().restart_connection(
            config_id,
            resolver_lease_factory=self._lease_factory(),
        )

    async def remove_connection(self, config_id: str) -> bool:
        return await self._manager().remove_connection(config_id)

    async def build_adapter(self, config: ChannelConfigModel) -> object:
        return await self._manager().build_adapter(
            config,
            resolver_lease_factory=self._lease_factory(),
        )

    def get_status(self, config_id: str) -> dict[str, Any] | None:
        return self._manager().get_status(config_id)

    def get_all_status(self) -> list[dict[str, Any]]:
        return self._manager().get_all_status()

    def _manager(self) -> ChannelConnectionManager:
        manager = self.runtime.manager
        if manager is None:
            raise RuntimeV2Error(
                "channel_runtime_unavailable",
                "channel connection manager is not active",
            )
        return manager

    def _lease_factory(self) -> ChannelAdapterResolverLeaseFactoryV2:
        async def acquire() -> ChannelAdapterResolverLeaseProtocolV2:
            return await self.runtime.acquire_connection(self.generation_token)

        return acquire


@dataclass(frozen=True, kw_only=True)
class UnavailableChannelRuntimeServiceV2:
    """Fail-closed service used by hosts that did not install a data-plane manager."""

    unavailable_code: str = "channel_runtime_manager_unavailable"

    @property
    def connections(self) -> dict[str, ManagedConnection]:
        self._raise()

    async def add_connection(self, config: ChannelConfigModel) -> ManagedConnection:
        del config
        self._raise()

    async def restart_connection(self, config_id: str) -> bool:
        del config_id
        self._raise()

    async def remove_connection(self, config_id: str) -> bool:
        del config_id
        self._raise()

    async def build_adapter(self, config: ChannelConfigModel) -> object:
        del config
        self._raise()

    def get_status(self, config_id: str) -> dict[str, Any] | None:
        del config_id
        self._raise()

    def get_all_status(self) -> list[dict[str, Any]]:
        self._raise()

    def _raise(self) -> NoReturn:
        raise RuntimeV2Error(
            self.unavailable_code,
            "channel runtime manager is not installed on this data plane",
        )


def _default_manager_factory(
    *,
    message_router: Callable[[Message], object],
    session_factory: ChannelRuntimeSessionFactoryV2,
) -> ChannelConnectionManager:
    return ChannelConnectionManager(
        message_router=cast("Callable[[Message], None]", message_router),
        session_factory=session_factory,
    )


@dataclass(kw_only=True)
class ChannelRuntimeManagerV2:
    """Share one manager while exact generation resolver leases remain registered."""

    manager_factory: ChannelConnectionManagerFactoryV2 = _default_manager_factory
    _manager: ChannelConnectionManager | None = None
    _config: ChannelRuntimeConfigV2 | None = None
    _session_factory: ChannelRuntimeSessionFactoryV2 | None = None
    _registrations: dict[int, _ResolverRegistrationV2] = field(default_factory=dict)
    _next_token: int = 0
    _active_token: int | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def manager(self) -> ChannelConnectionManager | None:
        return self._manager

    @property
    def generation_references(self) -> int:
        return sum(item.generation_active for item in self._registrations.values())

    @property
    def connection_leases(self) -> int:
        return sum(item.connection_leases for item in self._registrations.values())

    @property
    def active_generation_token(self) -> int | None:
        return self._active_token

    async def acquire_generation(
        self,
        *,
        sessions: AsyncSessionFactoryProviderProtocolV2,
        adapters: ChannelAdapterResolverProtocolV2,
        config: ChannelRuntimeConfigV2,
    ) -> ChannelRuntimeServiceV2:
        """Stage one resolver, starting only the initial process manager immediately."""
        async with self._lock:
            if self._registrations and (
                self._config != config or self._session_factory is not sessions.factory
            ):
                raise RuntimeV2Error(
                    "channel_runtime_process_boundary_mismatch",
                    "channel runtime config or session factory changed inside a process boundary",
                )
            self._next_token += 1
            token = self._next_token
            self._registrations[token] = _ResolverRegistrationV2(resolver=adapters)
            initial = self._manager is None
            if initial:
                from src.application.services.channels import route_channel_message

                self._manager = self.manager_factory(
                    message_router=route_channel_message,
                    session_factory=sessions.factory,
                )
                self._config = config
                self._session_factory = sessions.factory
                self._active_token = token
            manager = self._manager

        if manager is None:
            raise RuntimeV2Error(
                "channel_runtime_unavailable",
                "channel connection manager was not constructed",
            )
        service = ChannelRuntimeServiceV2(runtime=self, generation_token=token)
        try:
            if initial:
                _ = await manager.start_all(
                    sessions.factory,
                    resolver_lease_factory=service._lease_factory(),
                    strict=config.strict_startup,
                )
            else:
                _ = await manager.preflight_all(
                    resolver_lease_factory=service._lease_factory(),
                )
        except BaseException:
            await self._discard_failed_generation(token, initial=initial)
            raise
        return service

    async def acquire_connection(self, token: int) -> ChannelAdapterResolverLeaseV2:
        """Lease the exact resolver registered by one still-live generation service."""
        async with self._lock:
            registration = self._registrations.get(token)
            if registration is None or not registration.generation_active:
                raise RuntimeV2Error(
                    "channel_generation_resolver_unavailable",
                    "channel generation resolver is no longer active",
                )
            registration.connection_leases += 1
            return ChannelAdapterResolverLeaseV2(
                runtime=self,
                generation_token=token,
                resolver=registration.resolver,
            )

    async def release_connection(self, token: int) -> None:
        """Release one connection resolver lease and discard drained retired state."""
        async with self._lock:
            registration = self._registrations.get(token)
            if registration is None or registration.connection_leases <= 0:
                raise RuntimeV2Error(
                    "channel_connection_lease_underflow",
                    "channel resolver connection lease is not active",
                )
            registration.connection_leases -= 1
            if not registration.generation_active and registration.connection_leases == 0:
                _ = self._registrations.pop(token, None)

    async def release_generation(self, token: int) -> None:
        """Retire one generation, rebinding only after a replacement was published."""
        async with self._lock:
            registration = self._registrations.get(token)
            if registration is None or not registration.generation_active:
                raise RuntimeV2Error(
                    "channel_generation_reference_underflow",
                    "channel runtime generation reference is not active",
                )
            registration.generation_active = False
            if token != self._active_token:
                if registration.connection_leases == 0:
                    _ = self._registrations.pop(token, None)
                return
            replacements = [
                candidate
                for candidate, item in self._registrations.items()
                if item.generation_active
            ]
            replacement = max(replacements, default=None)
            manager = self._manager

        if manager is None:
            await self._finish_release(token, replacement=replacement)
            return
        if replacement is None:
            try:
                await manager.shutdown_all()
            finally:
                await self._finish_release(token, replacement=None, clear_manager=True)
            return

        async def acquire_replacement() -> ChannelAdapterResolverLeaseProtocolV2:
            return await self.acquire_connection(replacement)

        try:
            _ = await manager.rebind_all(resolver_lease_factory=acquire_replacement)
        except Exception:
            logger.exception(
                "Failed to rebind channel connections; existing adapters remain last-good"
            )
        finally:
            await self._finish_release(token, replacement=replacement)

    async def _discard_failed_generation(self, token: int, *, initial: bool) -> None:
        manager = self._manager
        if initial and manager is not None:
            try:
                await manager.shutdown_all()
            except Exception:
                logger.exception("Failed to clean up channel runtime candidate")
        async with self._lock:
            registration = self._registrations.get(token)
            if registration is not None:
                registration.generation_active = False
                if registration.connection_leases == 0:
                    _ = self._registrations.pop(token, None)
            if initial:
                self._manager = None
                self._active_token = None
                self._config = None
                self._session_factory = None

    async def _finish_release(
        self,
        token: int,
        *,
        replacement: int | None,
        clear_manager: bool = False,
    ) -> None:
        async with self._lock:
            registration = self._registrations.get(token)
            if registration is not None and registration.connection_leases == 0:
                _ = self._registrations.pop(token, None)
            self._active_token = replacement
            if clear_manager:
                self._manager = None
                self._config = None
                self._session_factory = None
                for retired_token, retired in tuple(self._registrations.items()):
                    if not retired.generation_active and retired.connection_leases == 0:
                        _ = self._registrations.pop(retired_token, None)


def _channel_runtime_config_v2(config: Mapping[str, Any]) -> ChannelRuntimeConfigV2:
    if config.get("strategy") != "generation-resolver-leases":
        raise ValueError("channel runtime requires strategy generation-resolver-leases")
    strict_startup = config.get("strict_startup")
    if not isinstance(strict_startup, bool):
        raise ValueError("channel runtime strict_startup must be a boolean")
    return ChannelRuntimeConfigV2(strict_startup=strict_startup)


def channel_runtime_definition_v2(
    runtime: ChannelRuntimeManagerV2 | None = None,
) -> PluginDefinitionV2:
    """Bind the process channel manager to reversible generation resolver effects."""

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> EffectResultV2:
        runtime_manager = runtime
        if runtime_manager is None:
            _ = _channel_runtime_config_v2(config)
            _ = context.provide(
                CHANNEL_RUNTIME_SERVICE_V2,
                UnavailableChannelRuntimeServiceV2(),
                label="channel-runtime-unavailable",
            )
            return None
        sessions = context.require(CHANNEL_RUNTIME_SESSIONS_INJECT_V2)
        if not isinstance(sessions, AsyncSessionFactoryProviderProtocolV2):
            raise RuntimeV2Error(
                "invalid_channel_runtime_sessions",
                "channel runtime sessions inject has an invalid implementation",
            )
        adapters = context.require(CHANNEL_RUNTIME_ADAPTERS_INJECT_V2)
        if not isinstance(adapters, ChannelAdapterResolverProtocolV2):
            raise RuntimeV2Error(
                "invalid_channel_runtime_adapters",
                "channel runtime adapters inject has an invalid implementation",
            )
        service = await runtime_manager.acquire_generation(
            sessions=sessions,
            adapters=adapters,
            config=_channel_runtime_config_v2(config),
        )
        try:
            _ = context.provide(
                CHANNEL_RUNTIME_SERVICE_V2,
                service,
                label="channel-runtime",
            )
        except Exception:
            await runtime_manager.release_generation(service.generation_token)
            raise

        async def dispose() -> None:
            await runtime_manager.release_generation(service.generation_token)

        return dispose

    return PluginDefinitionV2(
        module_ref=CHANNEL_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(CHANNEL_RUNTIME_MODULE_V2),
        apply=apply,
    )


def current_channel_runtime_v2() -> ChannelRuntimeServiceProtocolV2:
    """Resolve the channel runtime facade from the currently pinned generation."""
    from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

    from .boundary import current_generation_v2

    service = current_generation_v2().resolve(
        CHANNEL_RUNTIME_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    if not isinstance(service, ChannelRuntimeServiceProtocolV2):
        raise RuntimeV2Error(
            "invalid_channel_runtime",
            "resolved channel runtime service has an invalid implementation",
        )
    return service


__all__ = [
    "CHANNEL_RUNTIME_ADAPTERS_INJECT_V2",
    "CHANNEL_RUNTIME_MODULE_V2",
    "CHANNEL_RUNTIME_SERVICE_V2",
    "CHANNEL_RUNTIME_SESSIONS_INJECT_V2",
    "AsyncSessionFactoryProviderProtocolV2",
    "ChannelAdapterResolverLeaseV2",
    "ChannelConnectionManagerFactoryV2",
    "ChannelRuntimeConfigV2",
    "ChannelRuntimeManagerV2",
    "ChannelRuntimeServiceProtocolV2",
    "ChannelRuntimeServiceV2",
    "ChannelRuntimeSessionFactoryV2",
    "UnavailableChannelRuntimeServiceV2",
    "channel_runtime_definition_v2",
    "current_channel_runtime_v2",
]
