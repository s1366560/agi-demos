"""
Message Bus adapters.

This module provides message bus implementations for:
- Unified Event Bus (new): Consolidated event bus for all domains
- Dead Letter Queue: Failed event handling and retry
- Human-in-the-Loop (HITL) cross-process communication
- Agent event streaming and recovery

Migration Path:
- New code should use UnifiedEventBusPort and RedisUnifiedEventBusAdapter
- Legacy code can use UnifiedAgentEventBusAdapter for backward compatibility
"""

from src.infrastructure.adapters.secondary.messaging.event_router import (
    EventRouter,
    HandlerRegistration,
    RouterMetrics,
    RoutingResult,
)
from src.infrastructure.adapters.secondary.messaging.redis_agent_event_bus import (
    RedisAgentEventBusAdapter,
    create_redis_agent_event_bus,
)
from src.infrastructure.adapters.secondary.messaging.redis_dlq import (
    RedisDLQAdapter,
)
from src.infrastructure.adapters.secondary.messaging.redis_hitl_message_bus import (
    RedisHITLMessageBusAdapter,
    create_redis_hitl_message_bus,
)
from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
    RedisUnifiedEventBusAdapter,
)
from src.infrastructure.adapters.secondary.messaging.unified_adapter_wrapper import (
    UnifiedAgentEventBusAdapter,
)

__all__ = [
    "EventRouter",
    "HandlerRegistration",
    # Agent Event Bus (legacy)
    "RedisAgentEventBusAdapter",
    # Dead Letter Queue
    "RedisDLQAdapter",
    # HITL Message Bus
    "RedisHITLMessageBusAdapter",
    # Unified Event Bus (recommended)
    "RedisUnifiedEventBusAdapter",
    "RouterMetrics",
    "RoutingResult",
    # Legacy Adapter Wrapper
    "UnifiedAgentEventBusAdapter",
    "create_redis_agent_event_bus",
    "create_redis_hitl_message_bus",
]
