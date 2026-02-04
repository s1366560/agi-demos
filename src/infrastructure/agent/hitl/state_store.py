"""
HITL State Store - Redis-based state persistence for Agent pause/resume.

This module provides state persistence for Agent execution when paused
for Human-in-the-Loop interactions. It allows:

1. Saving Agent processor state when HITL request is initiated
2. Restoring state when user provides response
3. Automatic expiration aligned with HITL timeout

State Flow:
    Agent executing → HITL request → save_state() → return to Workflow
    User responds → Workflow resumes → load_state() → continue Agent

Key Design Decisions:
- Uses Redis for fast read/write and automatic expiration
- State is JSON serializable for compatibility
- TTL slightly exceeds HITL timeout to handle edge cases
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# State Data Classes
# =============================================================================


@dataclass
class HITLAgentState:
    """
    Serializable state of an Agent processor paused for HITL.

    This captures everything needed to resume Agent execution:
    - Conversation context (messages exchanged so far)
    - Current step and tool execution state
    - Work plan progress
    - Cost tracking
    """

    # Identifiers
    conversation_id: str
    message_id: str
    tenant_id: str
    project_id: str

    # HITL request info
    hitl_request_id: str
    hitl_type: str
    hitl_request_data: Dict[str, Any]

    # Conversation state
    messages: List[Dict[str, Any]] = field(default_factory=list)
    user_message: str = ""
    user_id: str = ""

    # Execution state
    step_count: int = 0
    current_plan_step: int = 0
    work_plan_id: Optional[str] = None
    work_plan_steps: List[Dict[str, Any]] = field(default_factory=list)

    # Pending tool calls (serialized)
    pending_tool_calls: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Current message being built
    current_message_text: str = ""
    current_message_thinking: str = ""

    # Cost tracking
    total_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    timeout_seconds: float = 300.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HITLAgentState":
        """Create from dictionary."""
        return cls(**data)


# =============================================================================
# State Store
# =============================================================================


class HITLStateStore:
    """
    Redis-based state store for HITL Agent pause/resume.

    Usage:
        store = HITLStateStore(redis_client)

        # Save state when HITL initiated
        state_key = await store.save_state(state)

        # Load state when user responds
        state = await store.load_state(state_key)

        # Delete after successful resume
        await store.delete_state(state_key)
    """

    # Redis key prefix
    KEY_PREFIX = "hitl:agent_state:"

    # Default TTL buffer (added to HITL timeout)
    TTL_BUFFER_SECONDS = 60

    def __init__(self, redis_client):
        """
        Initialize state store.

        Args:
            redis_client: Async Redis client instance
        """
        self._redis = redis_client

    def _make_key(self, conversation_id: str, request_id: str) -> str:
        """Generate Redis key for state storage.
        
        Note: Uses request_id (not message_id) to ensure each HITL request
        has a unique state key. This prevents issues when multiple HITL
        requests occur for the same message.
        """
        return f"{self.KEY_PREFIX}{conversation_id}:{request_id}"

    def _make_key_from_request(self, request_id: str) -> str:
        """Generate Redis key from HITL request ID."""
        return f"{self.KEY_PREFIX}request:{request_id}"

    async def save_state(
        self,
        state: HITLAgentState,
        ttl_seconds: Optional[float] = None,
    ) -> str:
        """
        Save Agent state to Redis.

        Args:
            state: Agent state to save
            ttl_seconds: TTL override (default: state.timeout_seconds + buffer)

        Returns:
            State key for later retrieval
        """
        state_key = self._make_key(state.conversation_id, state.hitl_request_id)
        request_key = self._make_key_from_request(state.hitl_request_id)

        # Calculate TTL
        ttl = int(ttl_seconds or (state.timeout_seconds + self.TTL_BUFFER_SECONDS))

        # Serialize state
        state_json = json.dumps(state.to_dict())

        # Save to Redis with TTL
        await self._redis.setex(state_key, ttl, state_json)

        # Also create index by request_id for lookup
        await self._redis.setex(request_key, ttl, state_key)

        logger.info(
            f"[HITLStateStore] Saved state: key={state_key}, "
            f"request_id={state.hitl_request_id}, ttl={ttl}s"
        )

        return state_key

    async def load_state(self, state_key: str) -> Optional[HITLAgentState]:
        """
        Load Agent state from Redis.

        Args:
            state_key: Key returned from save_state()

        Returns:
            Agent state if found, None if expired or not found
        """
        state_json = await self._redis.get(state_key)

        if not state_json:
            logger.warning(f"[HITLStateStore] State not found: {state_key}")
            return None

        try:
            state_dict = json.loads(state_json)
            state = HITLAgentState.from_dict(state_dict)

            logger.info(
                f"[HITLStateStore] Loaded state: key={state_key}, "
                f"request_id={state.hitl_request_id}"
            )

            return state

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"[HITLStateStore] Failed to deserialize state: {e}")
            return None

    async def load_state_by_request(
        self,
        request_id: str,
    ) -> Optional[HITLAgentState]:
        """
        Load Agent state by HITL request ID.

        Args:
            request_id: HITL request ID

        Returns:
            Agent state if found, None if expired or not found
        """
        request_key = self._make_key_from_request(request_id)

        # Get the actual state key from index
        state_key = await self._redis.get(request_key)

        if not state_key:
            logger.warning(f"[HITLStateStore] State key not found for request: {request_id}")
            return None

        # state_key might be bytes, decode if needed
        if isinstance(state_key, bytes):
            state_key = state_key.decode("utf-8")

        return await self.load_state(state_key)

    async def delete_state(self, state_key: str) -> bool:
        """
        Delete Agent state from Redis.

        Args:
            state_key: Key to delete

        Returns:
            True if deleted, False if not found
        """
        # First load to get request_id for index cleanup
        state = await self.load_state(state_key)

        if state:
            request_key = self._make_key_from_request(state.hitl_request_id)
            await self._redis.delete(request_key)

        result = await self._redis.delete(state_key)

        if result:
            logger.info(f"[HITLStateStore] Deleted state: {state_key}")
        else:
            logger.warning(f"[HITLStateStore] State not found for deletion: {state_key}")

        return bool(result)

    async def delete_state_by_request(self, request_id: str) -> bool:
        """
        Delete Agent state by HITL request ID.

        Args:
            request_id: HITL request ID

        Returns:
            True if deleted, False if not found
        """
        request_key = self._make_key_from_request(request_id)

        state_key = await self._redis.get(request_key)
        if not state_key:
            return False

        if isinstance(state_key, bytes):
            state_key = state_key.decode("utf-8")

        # Delete both keys
        await self._redis.delete(request_key)
        result = await self._redis.delete(state_key)

        return bool(result)

    async def exists(self, state_key: str) -> bool:
        """Check if state exists."""
        return bool(await self._redis.exists(state_key))

    async def get_ttl(self, state_key: str) -> int:
        """Get remaining TTL in seconds (-2 if not exists, -1 if no expiry)."""
        return await self._redis.ttl(state_key)


# =============================================================================
# Factory Function
# =============================================================================


async def get_hitl_state_store() -> HITLStateStore:
    """
    Get HITL state store instance with Redis client.

    Returns:
        Configured HITLStateStore instance
    """
    from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
        get_redis_client,
    )

    redis_client = await get_redis_client()

    if not redis_client:
        raise RuntimeError("Redis client not available for HITL state store")

    return HITLStateStore(redis_client)
