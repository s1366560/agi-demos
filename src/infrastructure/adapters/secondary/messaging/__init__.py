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

from src.infrastructure.adapters.secondary.messaging.redis_agent_event_bus import (
    RedisAgentEventBusAdapter,
    create_redis_agent_event_bus,
)
from src.infrastructure.adapters.secondary.messaging.redis_hitl_message_bus import (
    RedisHITLMessageBusAdapter,
    create_redis_hitl_message_bus,
)
from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
    RedisUnifiedEventBusAdapter,
)
from src.infrastructure.adapters.secondary.messaging.event_router import (
    EventRouter,
    HandlerRegistration,
    RoutingResult,
    RouterMetrics,
)
from src.infrastructure.adapters.secondary.messaging.unified_adapter_wrapper import (
    UnifiedAgentEventBusAdapter,
)
from src.infrastructure.adapters.secondary.messaging.redis_dlq import (
    RedisDLQAdapter,
)

__all__ = [
    # Unified Event Bus (recommended)
    "RedisUnifiedEventBusAdapter",
    "EventRouter",
    "HandlerRegistration",
    "RoutingResult",
    "RouterMetrics",
    # Dead Letter Queue
    "RedisDLQAdapter",
    # Legacy Adapter Wrapper
    "UnifiedAgentEventBusAdapter",
    # HITL Message Bus
    "RedisHITLMessageBusAdapter",
    "create_redis_hitl_message_bus",
    # Agent Event Bus (legacy)
    "RedisAgentEventBusAdapter",
    "create_redis_agent_event_bus",
]
