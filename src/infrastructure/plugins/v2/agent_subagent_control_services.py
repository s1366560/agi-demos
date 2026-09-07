"""Generation-owned application seam for Agent SubAgent control."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from .redis_runtime import RedisRuntimeServiceV2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

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


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, kw_only=True)
class RedisAgentSubAgentControlServiceV2:
    """Write cancellation signals through the Redis client pinned to a generation."""

    redis_runtime: RedisRuntimeServiceV2
    ttl_seconds: int
    clock: Callable[[], datetime] = _utc_now

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
