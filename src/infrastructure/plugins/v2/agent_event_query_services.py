"""Generation-owned persistence and application seams for Agent event queries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol, runtime_checkable

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.execution.agent_execution_event import AgentExecutionEvent
from src.domain.ports.repositories.agent_repository import AgentExecutionEventRepository
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    SqlAgentExecutionEventRepository,
)

from .redis_runtime import RedisRuntimeServiceV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AGENT_EVENT_QUERY_REPOSITORY_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/agent-event-query-repository-provider"
)
AGENT_EVENT_QUERY_REPOSITORY_PROVIDER_SERVICE_V2 = (
    "service:persistence.agent-event-query-repository-provider"
)
AGENT_EVENT_QUERY_MODULE_V2 = "builtin://memstack/application/agent-event-query"
AGENT_EVENT_QUERY_SERVICE_V2 = "service:application.agent-event-query"
AGENT_EVENT_QUERY_REPOSITORIES_INJECT_V2 = "repositories"
AGENT_EVENT_QUERY_REDIS_INJECT_V2 = "redis"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class AgentEventQueryRepositoryFactoryProtocolV2(Protocol):
    """Build an event repository from one operation-owned DB session."""

    def build(self, operation: OperationContextV2) -> AgentExecutionEventRepository: ...


@dataclass(frozen=True, kw_only=True)
class SqlAgentEventQueryRepositoryFactoryV2:
    """Hide the SQL event repository behind an explicit Provider seam."""

    strategy: str

    def build(self, operation: OperationContextV2) -> AgentExecutionEventRepository:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "Agent event queries require an AsyncSession operation service",
            )
        return SqlAgentExecutionEventRepository(db)


@runtime_checkable
class AgentEventQueryRedisReadProtocolV2(Protocol):
    """Redis subset used to resolve the currently running message."""

    async def get(self, key: str) -> object | None: ...


@runtime_checkable
class AgentEventQueryRedisStreamProtocolV2(Protocol):
    """Redis Stream subset used for recovery readiness checks."""

    async def xinfo_stream(self, key: str) -> object: ...

    async def xrevrange(
        self,
        key: str,
        *,
        count: int,
    ) -> list[tuple[object, Mapping[object, object]]]: ...


@dataclass(frozen=True, kw_only=True)
class AgentEventRecoveryStateV2:
    """Transport-neutral recovery state for one execution status query."""

    can_recover: bool
    stream_exists: bool = False
    recovery_source: str = "none"
    missed_events_count: int = 0


@dataclass(frozen=True, kw_only=True)
class AgentEventExecutionStatusV2:
    """Transport-neutral persisted and live execution status."""

    is_running: bool
    last_event_time_us: int
    last_event_counter: int
    current_message_id: str | None
    recovery: AgentEventRecoveryStateV2 | None = None


@dataclass(frozen=True, kw_only=True)
class AgentEventQueryServiceV2:
    """Operation-owned event replay and status application surface."""

    event_repository: AgentExecutionEventRepository
    redis_client: object | None

    async def get_events(
        self,
        *,
        conversation_id: str,
        from_time_us: int,
        from_counter: int,
        limit: int,
    ) -> list[AgentExecutionEvent]:
        _require_identifier(conversation_id, field_name="conversation_id")
        if from_time_us < 0 or from_counter < 0:
            raise ValueError("event replay cursors must be non-negative")
        if limit < 1:
            raise ValueError("event replay limit must be positive")
        return await self.event_repository.get_events(
            conversation_id=conversation_id,
            from_time_us=from_time_us,
            from_counter=from_counter,
            limit=limit,
        )

    async def get_execution_status(
        self,
        *,
        conversation_id: str,
        include_recovery: bool,
        from_time_us: int,
    ) -> AgentEventExecutionStatusV2:
        _require_identifier(conversation_id, field_name="conversation_id")
        if from_time_us < 0:
            raise ValueError("event recovery cursor must be non-negative")

        last_event_time_us, last_event_counter = await self.event_repository.get_last_event_time(
            conversation_id
        )
        is_running, current_message_id = await self._check_running(conversation_id)
        if current_message_id is None and last_event_time_us > 0:
            events = await self.event_repository.get_events(
                conversation_id=conversation_id,
                limit=1,
            )
            if events:
                current_message_id = events[-1].message_id

        recovery: AgentEventRecoveryStateV2 | None = None
        if include_recovery:
            recovery = AgentEventRecoveryStateV2(
                can_recover=last_event_time_us > from_time_us,
                recovery_source="database" if last_event_time_us > 0 else "none",
            )
            recovery = await self._check_stream_recovery(
                conversation_id=conversation_id,
                current_message_id=current_message_id,
                last_event_time_us=last_event_time_us,
                recovery=recovery,
            )

        return AgentEventExecutionStatusV2(
            is_running=is_running,
            last_event_time_us=last_event_time_us,
            last_event_counter=last_event_counter,
            current_message_id=current_message_id,
            recovery=recovery,
        )

    async def _check_running(self, conversation_id: str) -> tuple[bool, str | None]:
        if self.redis_client is None:
            return False, None
        if not isinstance(self.redis_client, AgentEventQueryRedisReadProtocolV2):
            raise RuntimeV2Error(
                "invalid_agent_event_query_redis",
                "Agent event query Redis Provider cannot read execution state",
            )
        running_message_id = await self.redis_client.get(f"agent:running:{conversation_id}")
        if not running_message_id:
            return False, None
        message_id = (
            running_message_id.decode()
            if isinstance(running_message_id, bytes)
            else str(running_message_id)
        )
        return True, message_id

    async def _check_stream_recovery(
        self,
        *,
        conversation_id: str,
        current_message_id: str | None,
        last_event_time_us: int,
        recovery: AgentEventRecoveryStateV2,
    ) -> AgentEventRecoveryStateV2:
        if self.redis_client is None or current_message_id is None:
            return recovery
        if not isinstance(self.redis_client, AgentEventQueryRedisStreamProtocolV2):
            raise RuntimeV2Error(
                "invalid_agent_event_query_redis",
                "Agent event query Redis Provider cannot inspect recovery streams",
            )
        stream_key = f"agent:events:{conversation_id}"
        try:
            stream_info = await self.redis_client.xinfo_stream(stream_key)
            updated = recovery
            if stream_info:
                updated = replace(
                    recovery,
                    stream_exists=True,
                    recovery_source="stream",
                )
                last_entry = await self.redis_client.xrevrange(stream_key, count=1)
                if last_entry:
                    _, fields = last_entry[0]
                    time_us_raw = fields.get(b"event_time_us") or fields.get("event_time_us")
                    if isinstance(time_us_raw, (str, bytes, bytearray, int)):
                        stream_time_us = int(time_us_raw)
                        if stream_time_us > last_event_time_us:
                            updated = replace(updated, can_recover=True)
            return updated
        except redis.ResponseError:
            return recovery


@runtime_checkable
class AgentEventQueryResolverProtocolV2(Protocol):
    """Resolve one event query service from declared Provider aliases."""

    def resolve(self, operation: OperationContextV2) -> AgentEventQueryServiceV2: ...


@dataclass(frozen=True, kw_only=True)
class AgentEventQueryResolverV2:
    """Compose event queries from persistence and Redis Provider seams."""

    repositories: AgentEventQueryRepositoryFactoryProtocolV2
    redis: RedisRuntimeServiceV2

    def resolve(self, operation: OperationContextV2) -> AgentEventQueryServiceV2:
        return AgentEventQueryServiceV2(
            event_repository=self.repositories.build(operation),
            redis_client=self.redis.client,
        )


def _apply_agent_event_query_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError(
            "Agent event query repository provider requires strategy request-async-session"
        )
    _ = context.provide(
        AGENT_EVENT_QUERY_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlAgentEventQueryRepositoryFactoryV2(strategy=strategy),
        label="agent-event-query-repository-provider",
    )


def _apply_agent_event_query_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-providers":
        raise ValueError("Agent event query requires strategy operation-scoped-providers")
    repositories = context.require(AGENT_EVENT_QUERY_REPOSITORIES_INJECT_V2)
    if not isinstance(repositories, AgentEventQueryRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_event_query_repository_provider",
            "Agent event query repository Provider has an invalid implementation",
        )
    redis_runtime = context.require(AGENT_EVENT_QUERY_REDIS_INJECT_V2)
    if not isinstance(redis_runtime, RedisRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_agent_event_query_redis_provider",
            "Agent event query Redis Provider has an invalid implementation",
        )
    _ = context.provide(
        AGENT_EVENT_QUERY_SERVICE_V2,
        AgentEventQueryResolverV2(
            repositories=repositories,
            redis=redis_runtime,
        ),
        label="agent-event-query",
    )


def agent_event_query_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the event persistence Provider and application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=AGENT_EVENT_QUERY_REPOSITORY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(
                AGENT_EVENT_QUERY_REPOSITORY_PROVIDER_MODULE_V2
            ),
            apply=_apply_agent_event_query_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=AGENT_EVENT_QUERY_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AGENT_EVENT_QUERY_MODULE_V2),
            apply=_apply_agent_event_query_v2,
        ),
    )


def _require_identifier(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


__all__ = [
    "AGENT_EVENT_QUERY_MODULE_V2",
    "AGENT_EVENT_QUERY_REDIS_INJECT_V2",
    "AGENT_EVENT_QUERY_REPOSITORIES_INJECT_V2",
    "AGENT_EVENT_QUERY_REPOSITORY_PROVIDER_MODULE_V2",
    "AGENT_EVENT_QUERY_REPOSITORY_PROVIDER_SERVICE_V2",
    "AGENT_EVENT_QUERY_SERVICE_V2",
    "AgentEventExecutionStatusV2",
    "AgentEventQueryRedisReadProtocolV2",
    "AgentEventQueryRedisStreamProtocolV2",
    "AgentEventQueryRepositoryFactoryProtocolV2",
    "AgentEventQueryResolverProtocolV2",
    "AgentEventQueryResolverV2",
    "AgentEventQueryServiceV2",
    "AgentEventRecoveryStateV2",
    "SqlAgentEventQueryRepositoryFactoryV2",
    "agent_event_query_service_definitions_v2",
]
