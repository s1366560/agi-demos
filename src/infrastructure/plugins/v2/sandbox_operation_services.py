"""Operation-scoped sandbox Provider and application Consumer seams."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.project_sandbox_lifecycle_service import (
    ProjectSandboxLifecycleService,
)
from src.application.services.sandbox_profile import SandboxProfileType
from src.application.services.unified_sandbox_service import UnifiedSandboxService
from src.application.services.workspace_sync_service import WorkspaceSyncService
from src.configuration.config import Settings, get_settings
from src.domain.ports.services.distributed_lock_port import DistributedLockPort
from src.domain.ports.services.sandbox_resource_port import SandboxResourcePort
from src.infrastructure.adapters.secondary.cache.redis_lock_adapter import (
    RedisDistributedLockAdapter,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
    SqlProjectSandboxRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .sandbox_runtime import SandboxRuntimeServiceV2

if TYPE_CHECKING:
    from redis.asyncio import Redis

SANDBOX_OPERATION_PROVIDER_MODULE_V2 = "builtin://memstack/sandbox/operation-service-provider"
SANDBOX_OPERATION_PROVIDER_SERVICE_V2 = "service:sandbox.operation-service-provider"
SANDBOX_OPERATION_APPLICATION_MODULE_V2 = (
    "builtin://memstack/application/sandbox-operation-services"
)
SANDBOX_OPERATION_APPLICATION_SERVICE_V2 = "service:application.sandbox-operation-services"
SANDBOX_OPERATION_RUNTIME_INJECT_V2 = "runtime"
SANDBOX_OPERATION_PROVIDER_INJECT_V2 = "provider"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SandboxOperationServicesV2:
    """Sandbox services bound to one exact operation AsyncSession."""

    sandbox_resource: SandboxResourcePort
    lifecycle_service: ProjectSandboxLifecycleService


@runtime_checkable
class SandboxOperationServiceFactoryProtocolV2(Protocol):
    """Provider contract hiding SQL, Redis, and runtime implementations."""

    def build(self, operation: OperationContextV2) -> SandboxOperationServicesV2: ...


@runtime_checkable
class SandboxOperationApplicationResolverProtocolV2(Protocol):
    """Application-facing resolver injected through a declared service alias."""

    def resolve(self, operation: OperationContextV2) -> SandboxOperationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class DefaultSandboxOperationServiceFactoryV2:
    """Build request-owned sandbox services from declared operation inputs."""

    runtime: SandboxRuntimeServiceV2
    redis_client: object | None = None

    def build(self, operation: OperationContextV2) -> SandboxOperationServicesV2:
        # Imported lazily because boundary owns the runtime host and therefore
        # imports builtin definitions while this module is being initialized.
        from .boundary import OPERATION_DB_SESSION_SERVICE_V2

        runtime_services = self.runtime.require()
        db = operation.require(OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "sandbox operation services require an AsyncSession operation service",
            )
        settings = get_settings()
        distributed_lock = _build_distributed_lock_v2(self.redis_client)
        common = _sandbox_service_options_v2(settings)
        return SandboxOperationServicesV2(
            sandbox_resource=UnifiedSandboxService(
                repository=SqlProjectSandboxRepository(db),
                sandbox_adapter=runtime_services.adapter,
                distributed_lock=distributed_lock,
                **common,
            ),
            lifecycle_service=ProjectSandboxLifecycleService(
                repository=SqlProjectSandboxRepository(db),
                sandbox_adapter=runtime_services.adapter,
                distributed_lock=distributed_lock,
                workspace_sync=WorkspaceSyncService(
                    workspace_base=settings.sandbox_workspace_base,
                ),
                **common,
            ),
        )


@dataclass(frozen=True, kw_only=True)
class SandboxOperationApplicationResolverV2:
    """Resolve operation services without exposing the Provider implementation."""

    provider: SandboxOperationServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> SandboxOperationServicesV2:
        return self.provider.build(operation)


def sandbox_operation_provider_definition_v2(
    *,
    redis_client: object | None = None,
) -> PluginDefinitionV2:
    """Build the sandbox operation Provider definition."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "request-async-session":
            raise ValueError("sandbox operation provider requires strategy request-async-session")
        runtime = context.require(SANDBOX_OPERATION_RUNTIME_INJECT_V2)
        if not isinstance(runtime, SandboxRuntimeServiceV2):
            raise RuntimeV2Error(
                "invalid_sandbox_runtime_inject",
                "sandbox operation provider runtime inject has an invalid implementation",
            )
        _ = context.provide(
            SANDBOX_OPERATION_PROVIDER_SERVICE_V2,
            DefaultSandboxOperationServiceFactoryV2(
                runtime=runtime,
                redis_client=redis_client,
            ),
            label="sandbox-operation-provider",
        )

    return PluginDefinitionV2(
        module_ref=SANDBOX_OPERATION_PROVIDER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SANDBOX_OPERATION_PROVIDER_MODULE_V2),
        apply=apply,
    )


def sandbox_operation_application_definition_v2() -> PluginDefinitionV2:
    """Build the sandbox operation application Consumer definition."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "operation-scoped-provider":
            raise ValueError(
                "sandbox operation application requires strategy operation-scoped-provider"
            )
        provider = context.require(SANDBOX_OPERATION_PROVIDER_INJECT_V2)
        if not isinstance(provider, SandboxOperationServiceFactoryProtocolV2):
            raise RuntimeV2Error(
                "invalid_sandbox_operation_provider",
                "sandbox operation provider inject does not implement the factory contract",
            )
        _ = context.provide(
            SANDBOX_OPERATION_APPLICATION_SERVICE_V2,
            SandboxOperationApplicationResolverV2(provider=provider),
            label="sandbox-operation-application",
        )

    return PluginDefinitionV2(
        module_ref=SANDBOX_OPERATION_APPLICATION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SANDBOX_OPERATION_APPLICATION_MODULE_V2),
        apply=apply,
    )


def sandbox_operation_service_definitions_v2(
    *,
    redis_client: object | None = None,
) -> tuple[PluginDefinitionV2, ...]:
    """Return the explicit operation Provider/Consumer definition pair."""
    return (
        sandbox_operation_provider_definition_v2(redis_client=redis_client),
        sandbox_operation_application_definition_v2(),
    )


def _build_distributed_lock_v2(redis_client: object | None) -> DistributedLockPort | None:
    if redis_client is None:
        return None
    return RedisDistributedLockAdapter(
        redis=cast("Redis", redis_client),
        namespace="memstack:lock",
        default_ttl=120,
        retry_interval=0.1,
        max_retries=300,
    )


def _sandbox_service_options_v2(settings: Settings) -> dict[str, Any]:
    return {
        "default_profile": SandboxProfileType(settings.sandbox_profile_type),
        "health_check_interval_seconds": 60,
        "auto_recover": True,
        "memory_limit_override": settings.sandbox_memory_limit,
        "cpu_limit_override": settings.sandbox_cpu_limit,
        "host_source_volume": (
            {settings.sandbox_host_source_path: settings.sandbox_host_source_mount_point}
            if settings.sandbox_host_source_path
            else None
        ),
        "host_memstack_volume": _resolve_memstack_volume_v2(settings),
        "host_docker_socket_volume": _resolve_docker_socket_volume_v2(settings),
    }


def _resolve_memstack_volume_v2(settings: Settings) -> dict[str, str] | None:
    mount_point = settings.sandbox_host_memstack_mount_point
    if settings.sandbox_host_memstack_path:
        return {settings.sandbox_host_memstack_path: mount_point}
    if settings.sandbox_host_source_path:
        derived = Path(settings.sandbox_host_source_path).parent / ".memstack"
        if derived.is_dir():
            logger.debug("Auto-derived sandbox memstack volume from host source")
            return {str(derived): mount_point}
    cwd_memstack = Path.cwd() / ".memstack"
    if cwd_memstack.is_dir():
        logger.debug("Auto-derived sandbox memstack volume from working directory")
        return {str(cwd_memstack): mount_point}
    return None


def _resolve_docker_socket_volume_v2(settings: Settings) -> dict[str, str] | None:
    if not settings.sandbox_docker_socket_enabled:
        return None
    socket_path = Path(settings.sandbox_docker_socket_path)
    if not socket_path.exists():
        logger.warning("Configured sandbox Docker socket path is unavailable")
        return None
    return {str(socket_path): "/var/run/docker.sock"}


__all__ = [
    "SANDBOX_OPERATION_APPLICATION_MODULE_V2",
    "SANDBOX_OPERATION_APPLICATION_SERVICE_V2",
    "SANDBOX_OPERATION_PROVIDER_INJECT_V2",
    "SANDBOX_OPERATION_PROVIDER_MODULE_V2",
    "SANDBOX_OPERATION_PROVIDER_SERVICE_V2",
    "SANDBOX_OPERATION_RUNTIME_INJECT_V2",
    "DefaultSandboxOperationServiceFactoryV2",
    "SandboxOperationApplicationResolverProtocolV2",
    "SandboxOperationApplicationResolverV2",
    "SandboxOperationServiceFactoryProtocolV2",
    "SandboxOperationServicesV2",
    "sandbox_operation_application_definition_v2",
    "sandbox_operation_provider_definition_v2",
    "sandbox_operation_service_definitions_v2",
]
