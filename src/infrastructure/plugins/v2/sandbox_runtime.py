"""Generation-owned sandbox runtime Provider and application Consumer seams."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from src.application.services.sandbox_event_service import SandboxEventPublisher
from src.application.services.sandbox_orchestrator import SandboxOrchestrator
from src.application.services.sandbox_token_service import SandboxTokenService
from src.application.services.sandbox_tool_registry import SandboxToolRegistry
from src.configuration.config import get_settings
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter

from .runtime import (
    ContextV2,
    EffectResultV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.application.services.sandbox_idle_reaper import SandboxIdleReaper

SANDBOX_RUNTIME_MODULE_V2 = "builtin://memstack/sandbox/mcp-docker-runtime"
SANDBOX_RUNTIME_SERVICE_V2 = "service:sandbox.runtime"
SANDBOX_APPLICATION_MODULE_V2 = "builtin://memstack/application/sandbox-services"
SANDBOX_APPLICATION_SERVICE_V2 = "service:application.sandbox-services"
SANDBOX_RUNTIME_INJECT_V2 = "runtime"

type SandboxRuntimeFactoryV2 = Callable[
    [], MCPSandboxAdapter | None | Awaitable[MCPSandboxAdapter | None]
]

logger = logging.getLogger(__name__)


@runtime_checkable
class SandboxToolRegistryProtocolV2(Protocol):
    """Generation-owned Sandbox tool-registration seam for HTTP consumers."""

    async def register_sandbox_tools(
        self,
        sandbox_id: str,
        project_id: str,
        tenant_id: str,
        tools: list[str] | None = None,
    ) -> list[str]: ...

    async def unregister_sandbox_tools(self, sandbox_id: str) -> bool: ...

    async def get_sandbox_tools(self, sandbox_id: str) -> list[str] | None: ...


@dataclass(frozen=True, kw_only=True)
class SandboxApplicationServicesV2:
    """Root sandbox services owned by one exact generation."""

    adapter: MCPSandboxAdapter
    event_publisher: SandboxEventPublisher
    orchestrator: SandboxOrchestrator
    token_service: SandboxTokenService
    tool_registry: SandboxToolRegistryProtocolV2


@dataclass(frozen=True, kw_only=True)
class SandboxRuntimeServiceV2:
    """Generation-owned sandbox resource state, including explicit unavailability."""

    services: SandboxApplicationServicesV2 | None
    unavailable_code: str | None = None

    @property
    def available(self) -> bool:
        return self.services is not None

    def require(self) -> SandboxApplicationServicesV2:
        if self.services is None:
            raise RuntimeV2Error(
                self.unavailable_code or "sandbox_runtime_unavailable",
                "sandbox runtime is unavailable in the pinned generation",
            )
        return self.services


@runtime_checkable
class SandboxApplicationResolverProtocolV2(Protocol):
    """Resolve sandbox services without exposing the Provider implementation."""

    def resolve(
        self,
        operation: OperationContextV2 | None = None,
    ) -> SandboxApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SandboxApplicationResolverV2:
    """Resolve root services from the runtime alias pinned into this Consumer."""

    runtime: SandboxRuntimeServiceV2

    def resolve(
        self,
        operation: OperationContextV2 | None = None,
    ) -> SandboxApplicationServicesV2:
        if operation is not None:
            _ = operation.descriptor
        return self.runtime.require()


def _validate_projected_runtime_v2(
    runtime: object,
    factory: SandboxRuntimeFactoryV2 | None,
    *,
    required: bool,
) -> SandboxRuntimeServiceV2:
    if factory is not None:
        raise RuntimeV2Error(
            "sandbox_runtime_source_conflict",
            "sandbox runtime accepts either a factory or a projected runtime",
        )
    if not isinstance(runtime, SandboxRuntimeServiceV2) or (
        runtime.services is not None
        and not isinstance(cast(object, runtime.services), SandboxApplicationServicesV2)
    ):
        raise RuntimeV2Error(
            "invalid_sandbox_runtime_projection",
            "projected sandbox runtime has an invalid implementation",
        )
    if required:
        _ = runtime.require()
    return runtime


def sandbox_runtime_definition_v2(
    sandbox_runtime_factory: SandboxRuntimeFactoryV2 | None = None,
    *,
    redis_client: object | None = None,
    projected_runtime: SandboxRuntimeServiceV2 | None = None,
) -> PluginDefinitionV2:
    """Own a factory resource or borrow one held alive by the caller's generation lease."""

    async def apply_runtime(
        context: ContextV2,
        config: Mapping[str, Any],
    ) -> EffectResultV2:
        strategy = config.get("strategy")
        required = config.get("required")
        if strategy != "mcp-docker":
            raise ValueError("sandbox runtime requires strategy mcp-docker")
        if not isinstance(required, bool):
            raise ValueError("sandbox runtime requires an explicit boolean required setting")

        if projected_runtime is not None:
            runtime_value = _validate_projected_runtime_v2(
                projected_runtime, sandbox_runtime_factory, required=required
            )
            # The caller holds the owner generation lease. This projection neither
            # initializes maintenance nor takes physical ownership or scope authority.
            _provide_sandbox_runtime_v2(context, runtime_value)
            return None

        if sandbox_runtime_factory is None:
            _provide_sandbox_runtime_v2(
                context,
                _unavailable_runtime_v2(required, "sandbox_runtime_factory_unavailable"),
            )
            return None

        adapter = sandbox_runtime_factory()
        if inspect.isawaitable(adapter):
            adapter = await adapter
        if adapter is None:
            _provide_sandbox_runtime_v2(
                context,
                _unavailable_runtime_v2(required, "sandbox_runtime_factory_unavailable"),
            )
            return None
        adapter_value = cast(object, adapter)
        if not isinstance(adapter_value, MCPSandboxAdapter):
            raise RuntimeV2Error(
                "invalid_sandbox_runtime",
                "sandbox runtime factory returned an invalid adapter",
            )
        adapter = adapter_value

        cleanup = AsyncExitStack()
        _ = cleanup.push_async_callback(adapter.close)
        _ = cleanup.callback(adapter.set_access_persist_callback, None)
        try:
            _ = await adapter.sync_from_docker()
            event_publisher = _build_event_publisher_v2(redis_client)
            tool_registry = SandboxToolRegistry(
                redis_client=cast("Redis | None", redis_client),
                mcp_adapter=adapter,
            )
            _ = await tool_registry.refresh_all_from_redis()
            settings = get_settings()
            services = SandboxApplicationServicesV2(
                adapter=adapter,
                event_publisher=event_publisher,
                orchestrator=SandboxOrchestrator(
                    sandbox_adapter=adapter,
                    event_publisher=event_publisher,
                    default_timeout=settings.sandbox_timeout_seconds,
                ),
                token_service=SandboxTokenService(
                    secret_key=settings.secret_key,
                    token_ttl=300,
                ),
                tool_registry=tool_registry,
            )
            _provide_sandbox_runtime_v2(
                context,
                SandboxRuntimeServiceV2(services=services),
            )
            idle_reaper = await _start_idle_reaper_v2(adapter)
            _ = cleanup.push_async_callback(_stop_idle_reaper_v2, idle_reaper)
        except BaseException:
            try:
                await cleanup.aclose()
            except Exception:
                logger.exception("Failed to clean up rejected sandbox runtime candidate")
            raise

        async def dispose() -> None:
            await cleanup.aclose()

        return dispose

    return PluginDefinitionV2(
        module_ref=SANDBOX_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SANDBOX_RUNTIME_MODULE_V2),
        apply=apply_runtime,
    )


def sandbox_application_definition_v2() -> PluginDefinitionV2:
    """Build the sandbox application Consumer definition."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "generation-runtime":
            raise ValueError("sandbox application requires strategy generation-runtime")
        runtime = context.require(SANDBOX_RUNTIME_INJECT_V2)
        if not isinstance(runtime, SandboxRuntimeServiceV2):
            raise RuntimeV2Error(
                "invalid_sandbox_runtime_inject",
                "sandbox runtime inject has an invalid implementation",
            )
        _ = context.provide(
            SANDBOX_APPLICATION_SERVICE_V2,
            SandboxApplicationResolverV2(runtime=runtime),
            label="sandbox-application",
        )

    return PluginDefinitionV2(
        module_ref=SANDBOX_APPLICATION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SANDBOX_APPLICATION_MODULE_V2),
        apply=apply,
    )


def sandbox_service_definitions_v2(
    sandbox_runtime_factory: SandboxRuntimeFactoryV2 | None = None,
    *,
    redis_client: object | None = None,
) -> tuple[PluginDefinitionV2, ...]:
    """Build the sandbox Provider/Consumer definition pair."""
    return (
        sandbox_runtime_definition_v2(
            sandbox_runtime_factory,
            redis_client=redis_client,
        ),
        sandbox_application_definition_v2(),
    )


def _unavailable_runtime_v2(required: bool, code: str) -> SandboxRuntimeServiceV2:
    if required:
        raise RuntimeV2Error(code, "required sandbox runtime has no data-plane factory")
    return SandboxRuntimeServiceV2(services=None, unavailable_code=code)


def _provide_sandbox_runtime_v2(
    context: ContextV2,
    runtime: SandboxRuntimeServiceV2,
) -> None:
    _ = context.provide(
        SANDBOX_RUNTIME_SERVICE_V2,
        runtime,
        label="sandbox-runtime",
    )


def _build_event_publisher_v2(redis_client: object | None) -> SandboxEventPublisher:
    if redis_client is None:
        return SandboxEventPublisher()
    try:
        from src.infrastructure.adapters.secondary.event.redis_event_bus import (
            RedisEventBusAdapter,
        )

        return SandboxEventPublisher(event_bus=RedisEventBusAdapter(cast("Redis", redis_client)))
    except Exception as exc:
        logger.warning(
            "Could not create sandbox event bus: error_type=%s",
            type(exc).__name__,
        )
        return SandboxEventPublisher()


async def _start_idle_reaper_v2(adapter: MCPSandboxAdapter) -> SandboxIdleReaper | None:
    from src.infrastructure.adapters.primary.web.startup.sandbox_reaper import (
        start_sandbox_idle_reaper_v2,
    )

    return await start_sandbox_idle_reaper_v2(adapter)


async def _stop_idle_reaper_v2(reaper: SandboxIdleReaper | None) -> None:
    from src.infrastructure.adapters.primary.web.startup.sandbox_reaper import (
        stop_sandbox_idle_reaper_v2,
    )

    await stop_sandbox_idle_reaper_v2(reaper)


__all__ = [
    "SANDBOX_APPLICATION_MODULE_V2",
    "SANDBOX_APPLICATION_SERVICE_V2",
    "SANDBOX_RUNTIME_INJECT_V2",
    "SANDBOX_RUNTIME_MODULE_V2",
    "SANDBOX_RUNTIME_SERVICE_V2",
    "SandboxApplicationResolverProtocolV2",
    "SandboxApplicationResolverV2",
    "SandboxApplicationServicesV2",
    "SandboxRuntimeFactoryV2",
    "SandboxRuntimeServiceV2",
    "SandboxToolRegistryProtocolV2",
    "sandbox_application_definition_v2",
    "sandbox_runtime_definition_v2",
    "sandbox_service_definitions_v2",
]
