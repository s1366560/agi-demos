"""Cross-process lifecycle publication using the existing Redis project event bus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.domain.events.envelope import EventEnvelope
from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
    RedisUnifiedEventBusAdapter,
)
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    agent_worker_redis_runtime_factory_v2,
)


def lifecycle_routing_key_v2(tenant_id: str, project_id: str) -> str:
    return f"project:{project_id}:agent_lifecycle:{tenant_id}"


@dataclass(frozen=True)
class AgentWorkerLifecycleTransportV2:
    """Publish to Redis, never to a worker-local API connection manager.

    Each awaited publish owns and closes its client. A positive return means durable
    publication, not a count of connected browser recipients.
    """

    async def broadcast_to_project(
        self, tenant_id: str, project_id: str, message: dict[str, Any]
    ) -> int:
        if message.get("tenant_id") != tenant_id or message.get("project_id") != project_id:
            raise ValueError("Lifecycle publication scope mismatch")
        if message.get("type") not in {"subagent_lifecycle", "lifecycle_state_change"}:
            raise ValueError("Undeclared lifecycle publication")
        client = await agent_worker_redis_runtime_factory_v2()
        try:
            await RedisUnifiedEventBusAdapter(client).publish(
                EventEnvelope(
                    event_type=message["type"],
                    payload=message,
                    metadata={"tenant_id": tenant_id, "project_id": project_id},
                ),
                lifecycle_routing_key_v2(tenant_id, project_id),
            )
        finally:
            await client.aclose()
        return 1
