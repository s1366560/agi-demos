"""Generation-owned Provider/Consumer seams for the admin dead-letter queue."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from src.domain.ports.services.dead_letter_queue_port import DeadLetterQueuePort
from src.infrastructure.adapters.secondary.messaging.redis_dlq import RedisDLQAdapter
from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
    RedisUnifiedEventBusAdapter,
)

from .redis_runtime import RedisRuntimeServiceV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

ADMIN_DLQ_PROVIDER_MODULE_V2 = "builtin://memstack/messaging/admin-dlq-provider"
ADMIN_DLQ_PROVIDER_SERVICE_V2 = "service:messaging.admin-dlq-provider"
ADMIN_DLQ_APPLICATION_MODULE_V2 = "builtin://memstack/application/admin-dlq-services"
ADMIN_DLQ_APPLICATION_SERVICE_V2 = "service:application.admin-dlq-services"
ADMIN_DLQ_PROVIDER_INJECT_V2 = "provider"
ADMIN_DLQ_REDIS_INJECT_V2 = "redis"


@runtime_checkable
class AdminDlqFactoryProtocolV2(Protocol):
    """Build the queue selected by the active generation."""

    def build(self, operation: OperationContextV2) -> DeadLetterQueuePort: ...


@dataclass(frozen=True, kw_only=True)
class RedisAdminDlqFactoryV2:
    """Construct the Redis queue only when an operation actually resolves it."""

    redis_runtime: RedisRuntimeServiceV2

    def build(self, operation: OperationContextV2) -> DeadLetterQueuePort:
        _ = operation.descriptor
        if self.redis_runtime.client is None:
            raise RuntimeV2Error(
                "admin_dlq_redis_unavailable",
                "admin DLQ requires the configured Redis runtime",
            )
        redis_client = cast("Redis", self.redis_runtime.client)
        return RedisDLQAdapter(
            redis_client=redis_client,
            event_bus=RedisUnifiedEventBusAdapter(redis_client),
        )


@dataclass(frozen=True, kw_only=True)
class AdminDlqApplicationServicesV2:
    """Operation-owned application services consumed by HTTP handlers."""

    queue: DeadLetterQueuePort


@runtime_checkable
class AdminDlqApplicationResolverProtocolV2(Protocol):
    """Resolve the application seam through the Profile-selected Provider alias."""

    def resolve(self, operation: OperationContextV2) -> AdminDlqApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class AdminDlqApplicationResolverV2:
    """Consumer that never imports or selects a concrete queue implementation."""

    provider: AdminDlqFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> AdminDlqApplicationServicesV2:
        return AdminDlqApplicationServicesV2(queue=self.provider.build(operation))


def _apply_admin_dlq_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "generation-redis-adapter":
        raise ValueError("admin DLQ provider requires strategy generation-redis-adapter")
    redis_runtime = context.require(ADMIN_DLQ_REDIS_INJECT_V2)
    if not isinstance(redis_runtime, RedisRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_admin_dlq_redis_runtime",
            "admin DLQ redis inject is not the runtime Redis projection",
        )
    _ = context.provide(
        ADMIN_DLQ_PROVIDER_SERVICE_V2,
        RedisAdminDlqFactoryV2(redis_runtime=redis_runtime),
        label="admin-dlq-provider",
    )


def _apply_admin_dlq_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("admin DLQ resolver requires strategy operation-scoped-provider")
    provider = context.require(ADMIN_DLQ_PROVIDER_INJECT_V2)
    if not isinstance(provider, AdminDlqFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_admin_dlq_provider",
            "admin DLQ provider inject does not implement the factory contract",
        )
    _ = context.provide(
        ADMIN_DLQ_APPLICATION_SERVICE_V2,
        AdminDlqApplicationResolverV2(provider=provider),
        label="admin-dlq-application",
    )


def admin_dlq_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent admin DLQ Provider and application Consumer definitions."""

    return (
        PluginDefinitionV2(
            module_ref=ADMIN_DLQ_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(ADMIN_DLQ_PROVIDER_MODULE_V2),
            apply=_apply_admin_dlq_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=ADMIN_DLQ_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(ADMIN_DLQ_APPLICATION_MODULE_V2),
            apply=_apply_admin_dlq_application_v2,
        ),
    )


__all__ = [
    "ADMIN_DLQ_APPLICATION_MODULE_V2",
    "ADMIN_DLQ_APPLICATION_SERVICE_V2",
    "ADMIN_DLQ_PROVIDER_INJECT_V2",
    "ADMIN_DLQ_PROVIDER_MODULE_V2",
    "ADMIN_DLQ_PROVIDER_SERVICE_V2",
    "ADMIN_DLQ_REDIS_INJECT_V2",
    "AdminDlqApplicationResolverProtocolV2",
    "AdminDlqApplicationResolverV2",
    "AdminDlqApplicationServicesV2",
    "AdminDlqFactoryProtocolV2",
    "RedisAdminDlqFactoryV2",
    "admin_dlq_service_definitions_v2",
]
