"""Generation-owned application seam for Agent SubAgent control."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from src.domain.model.agent.tool_policy import ControlMessageType
from src.domain.ports.agent.control_channel_port import ControlMessage
from src.infrastructure.agent.subagent.control_channel import RedisControlChannel

from .redis_runtime import RedisRuntimeServiceV2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis


AGENT_SUBAGENT_CONTROL_MODULE_V2 = "builtin://memstack/application/agent-subagent-control"
AGENT_SUBAGENT_CONTROL_SERVICE_V2 = "service:application.agent-subagent-control"
AGENT_SUBAGENT_CONTROL_REDIS_INJECT_V2 = "redis"


class AgentSubAgentControlUnavailableV2(RuntimeError):
    """Raised when the generation has no usable cancellation data plane."""


@runtime_checkable
class AgentSubAgentControlServiceProtocolV2(Protocol):
    """Publish one cross-process SubAgent cancellation request."""

    async def request_cancel(
        self,
        *,
        execution_id: str,
        requested_by: str,
        reason: str | None,
        conversation_id: str | None,
    ) -> None: ...

    async def request_steer(
        self,
        *,
        execution_id: str,
        requested_by: str,
        conversation_id: str,
        instruction: str,
        idempotency_key: str,
    ) -> None: ...

    async def release_controls(self, *, execution_id: str) -> None: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, kw_only=True)
class RedisAgentSubAgentControlServiceV2:
    """Write cancellation signals through the Redis client pinned to a generation."""

    redis_runtime: RedisRuntimeServiceV2
    ttl_seconds: int
    clock: Callable[[], datetime] = _utc_now

    async def release_controls(self, *, execution_id: str) -> None:
        client = self.redis_runtime.client
        if client is not None:
            await RedisControlChannel(cast("Redis", client)).cleanup(execution_id)

    async def request_steer(
        self,
        *,
        execution_id: str,
        requested_by: str,
        conversation_id: str,
        instruction: str,
        idempotency_key: str,
    ) -> None:
        client = self.redis_runtime.client
        if client is None:
            raise AgentSubAgentControlUnavailableV2("SubAgent control Redis is unavailable")
        accepted = await RedisControlChannel(cast("Redis", client)).send_control_once(
            ControlMessage(
                run_id=execution_id,
                message_type=ControlMessageType.STEER,
                payload=instruction,
                sender_id=requested_by,
                idempotency_key=idempotency_key,
                conversation_id=conversation_id,
                timestamp=self.clock(),
            )
        )
        if not accepted:
            raise AgentSubAgentControlUnavailableV2("SubAgent owner control delivery failed")

    async def request_cancel(
        self,
        *,
        execution_id: str,
        requested_by: str,
        reason: str | None,
        conversation_id: str | None,
    ) -> None:
        client = self.redis_runtime.client
        if client is None:
            raise AgentSubAgentControlUnavailableV2("SubAgent cancellation Redis is unavailable")

        setter = getattr(client, "set", None)
        if not callable(setter):
            raise RuntimeV2Error(
                "invalid_agent_subagent_control_redis",
                "Agent SubAgent control requires an async Redis set operation",
            )

        payload: dict[str, Any] = {
            "requested_by": requested_by,
            "reason": reason or "Cancelled by user",
            "timestamp": self.clock().isoformat(),
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id

        result = setter(
            f"subagent:cancel:{execution_id}",
            json.dumps(payload),
            ex=self.ttl_seconds,
        )
        if not inspect.isawaitable(result):
            raise RuntimeV2Error(
                "invalid_agent_subagent_control_redis",
                "Agent SubAgent control Redis set operation must be awaitable",
            )
        await result
        delivered = await RedisControlChannel(cast("Redis", client)).send_control(
            ControlMessage(
                run_id=execution_id,
                message_type=ControlMessageType.KILL,
                payload=reason or "Cancelled by user",
                sender_id=requested_by,
                timestamp=self.clock(),
            )
        )
        if not delivered:
            raise AgentSubAgentControlUnavailableV2("SubAgent owner control delivery failed")


def _apply_agent_subagent_control_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "redis-cancel-signal":
        raise ValueError("Agent SubAgent control requires strategy redis-cancel-signal")
    ttl_seconds = config.get("ttl_seconds")
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or ttl_seconds <= 0:
        raise ValueError("Agent SubAgent control requires a positive ttl_seconds")

    redis_runtime = context.require(AGENT_SUBAGENT_CONTROL_REDIS_INJECT_V2)
    if not isinstance(redis_runtime, RedisRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_agent_subagent_control_redis",
            "Agent SubAgent control Redis inject has an invalid implementation",
        )
    _ = context.provide(
        AGENT_SUBAGENT_CONTROL_SERVICE_V2,
        RedisAgentSubAgentControlServiceV2(
            redis_runtime=redis_runtime,
            ttl_seconds=ttl_seconds,
        ),
        label="agent-subagent-control",
    )


def agent_subagent_control_definition_v2() -> PluginDefinitionV2:
    """Return the Agent SubAgent-control application definition."""
    return PluginDefinitionV2(
        module_ref=AGENT_SUBAGENT_CONTROL_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_SUBAGENT_CONTROL_MODULE_V2),
        apply=_apply_agent_subagent_control_v2,
    )


__all__ = [
    "AGENT_SUBAGENT_CONTROL_MODULE_V2",
    "AGENT_SUBAGENT_CONTROL_REDIS_INJECT_V2",
    "AGENT_SUBAGENT_CONTROL_SERVICE_V2",
    "AgentSubAgentControlServiceProtocolV2",
    "AgentSubAgentControlUnavailableV2",
    "RedisAgentSubAgentControlServiceV2",
    "agent_subagent_control_definition_v2",
]
