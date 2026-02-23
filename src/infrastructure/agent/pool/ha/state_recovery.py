"""
State Recovery Service.

Provides state persistence and recovery for agent instances:
- Checkpoint creation on state changes
- State recovery after crashes/restarts
- Conversation context restoration
- Tool state recovery

Recovery strategies:
- Redis-based checkpoint storage (fast)
- PostgreSQL-based persistence (durable)
- Hybrid approach for critical data

State components recovered:
- Instance lifecycle state
- Active conversations
- Tool execution context
- Resource allocations
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CheckpointType(str, Enum):
    """Checkpoint types."""

    LIFECYCLE = "lifecycle"  # Instance state changes
    CONVERSATION = "conversation"  # Active conversation context
    EXECUTION = "execution"  # Tool execution state
    RESOURCE = "resource"  # Resource allocation state
    FULL = "full"  # Complete state snapshot


@dataclass
class StateCheckpoint:
    """State checkpoint for recovery."""

    checkpoint_id: str
    instance_key: str
    checkpoint_type: CheckpointType
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    state_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "checkpoint_id": self.checkpoint_id,
            "instance_key": self.instance_key,
            "checkpoint_type": self.checkpoint_type.value,
            "timestamp": self.timestamp.isoformat(),
            "state_data": self.state_data,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StateCheckpoint":
        """Create from dictionary."""
        return cls(
            checkpoint_id=data["checkpoint_id"],
            instance_key=data["instance_key"],
            checkpoint_type=CheckpointType(data["checkpoint_type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            state_data=data.get("state_data", {}),
            metadata=data.get("metadata", {}),
        )


@dataclass
class RecoveryResult:
    """Recovery operation result."""

    success: bool
    instance_key: str
    checkpoint_id: Optional[str] = None
    recovered_state: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    recovery_time_ms: float = 0.0


class StateRecoveryService:
    """
    State recovery service for agent instances.

    Handles:
    - State checkpointing on lifecycle changes
    - Recovery after crashes/restarts
    - Conversation context restoration
    - Resource reallocation
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        db_url: Optional[str] = None,
        checkpoint_ttl_seconds: int = 86400,  # 24 hours
        max_checkpoints_per_instance: int = 10,
    ):
        self._redis_url = redis_url
        self._db_url = db_url
        self._checkpoint_ttl = checkpoint_ttl_seconds
        self._max_checkpoints = max_checkpoints_per_instance
        self._redis_client: Optional[Any] = None
        self._is_running = False
        # In-memory fallback storage
        self._memory_storage: Dict[str, List[str]] = {}

    async def start(self) -> None:
        """Start the recovery service."""
        logger.info("Starting State Recovery Service")

        # Initialize Redis connection
        if self._redis_url:
            try:
                import redis.asyncio as redis

                self._redis_client = redis.from_url(self._redis_url)
                await self._redis_client.ping()
                logger.info("Redis connection established for state recovery")
            except ImportError:
                logger.warning("Redis not available, using in-memory storage")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}, using in-memory storage")

        self._is_running = True
        logger.info("State Recovery Service started")

    async def stop(self) -> None:
        """Stop the recovery service."""
        self._is_running = False

        if self._redis_client:
            await self._redis_client.close()

        logger.info("State Recovery Service stopped")

    async def create_checkpoint(
        self,
        instance_key: str,
        checkpoint_type: CheckpointType,
        state_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StateCheckpoint:
        """
        Create a state checkpoint.

        Args:
            instance_key: Instance identifier
            checkpoint_type: Type of checkpoint
            state_data: State data to checkpoint
            metadata: Optional metadata

        Returns:
            Created checkpoint
        """
        checkpoint = StateCheckpoint(
            checkpoint_id=f"{instance_key}:{checkpoint_type.value}:{int(time.time() * 1000)}",
            instance_key=instance_key,
            checkpoint_type=checkpoint_type,
            state_data=state_data,
            metadata=metadata or {},
        )

        # Store checkpoint
        await self._store_checkpoint(checkpoint)

        # Cleanup old checkpoints
        await self._cleanup_old_checkpoints(instance_key, checkpoint_type)

        logger.debug(
            f"Created checkpoint: {checkpoint.checkpoint_id}, type={checkpoint_type.value}"
        )
        return checkpoint

    async def recover_instance(
        self,
        instance_key: str,
        checkpoint_type: Optional[CheckpointType] = None,
    ) -> RecoveryResult:
        """
        Recover instance state from checkpoint.

        Args:
            instance_key: Instance to recover
            checkpoint_type: Specific checkpoint type (or None for latest)

        Returns:
            Recovery result
        """
        start_time = time.time()

        try:
            # Get latest checkpoint
            checkpoint = await self._get_latest_checkpoint(
                instance_key, checkpoint_type
            )

            if not checkpoint:
                return RecoveryResult(
                    success=False,
                    instance_key=instance_key,
                    error_message="No checkpoint found",
                    recovery_time_ms=(time.time() - start_time) * 1000,
                )

            return RecoveryResult(
                success=True,
                instance_key=instance_key,
                checkpoint_id=checkpoint.checkpoint_id,
                recovered_state=checkpoint.state_data,
                recovery_time_ms=(time.time() - start_time) * 1000,
            )

        except Exception as e:
            logger.error(f"Recovery failed for {instance_key}: {e}")
            return RecoveryResult(
                success=False,
                instance_key=instance_key,
                error_message=str(e),
                recovery_time_ms=(time.time() - start_time) * 1000,
            )

    async def recover_all_instances(self) -> List[RecoveryResult]:
        """
        Recover all instances with checkpoints.

        Returns:
            List of recovery results
        """
        results = []

        # Get all instance keys with checkpoints
        instance_keys = await self._get_all_instance_keys()

        for instance_key in instance_keys:
            result = await self.recover_instance(instance_key)
            results.append(result)

        logger.info(
            f"Recovered {len([r for r in results if r.success])}/{len(results)} instances"
        )
        return results

    async def delete_checkpoints(self, instance_key: str) -> int:
        """
        Delete all checkpoints for an instance.

        Args:
            instance_key: Instance identifier

        Returns:
            Number of checkpoints deleted
        """
        count = await self._delete_instance_checkpoints(instance_key)
        logger.info(f"Deleted {count} checkpoints for {instance_key}")
        return count

    async def get_checkpoint_stats(self) -> Dict[str, Any]:
        """Get checkpoint statistics."""
        instance_keys = await self._get_all_instance_keys()

        total_checkpoints = 0
        by_type: Dict[str, int] = {}

        for instance_key in instance_keys:
            checkpoints = await self._list_checkpoints(instance_key)
            total_checkpoints += len(checkpoints)
            for cp in checkpoints:
                cp_type = cp.checkpoint_type.value
                by_type[cp_type] = by_type.get(cp_type, 0) + 1

        return {
            "total_instances": len(instance_keys),
            "total_checkpoints": total_checkpoints,
            "by_type": by_type,
        }

    # =========================================================================
    # Private Methods - Storage Operations
    # =========================================================================

    async def _store_checkpoint(self, checkpoint: StateCheckpoint) -> None:
        """Store checkpoint in Redis or memory."""
        key = f"checkpoint:{checkpoint.instance_key}:{checkpoint.checkpoint_type.value}"
        data = json.dumps(checkpoint.to_dict())

        if self._redis_client:
            await self._redis_client.lpush(key, data)
            await self._redis_client.expire(key, self._checkpoint_ttl)
        else:
            # In-memory fallback
            if key not in self._memory_storage:
                self._memory_storage[key] = []
            self._memory_storage[key].insert(0, data)
            # Trim to max checkpoints
            if len(self._memory_storage[key]) > self._max_checkpoints:
                self._memory_storage[key] = self._memory_storage[key][
                    : self._max_checkpoints
                ]

    async def _get_latest_checkpoint(
        self,
        instance_key: str,
        checkpoint_type: Optional[CheckpointType] = None,
    ) -> Optional[StateCheckpoint]:
        """Get latest checkpoint for instance."""
        if checkpoint_type:
            key = f"checkpoint:{instance_key}:{checkpoint_type.value}"
            if self._redis_client:
                data = await self._redis_client.lindex(key, 0)
                if data:
                    return StateCheckpoint.from_dict(json.loads(data))
            elif self._memory_storage.get(key):
                return StateCheckpoint.from_dict(json.loads(self._memory_storage[key][0]))
        else:
            # Get latest across all types
            latest: Optional[StateCheckpoint] = None
            for cp_type in CheckpointType:
                key = f"checkpoint:{instance_key}:{cp_type.value}"
                data = None
                if self._redis_client:
                    data = await self._redis_client.lindex(key, 0)
                elif self._memory_storage.get(key):
                    data = self._memory_storage[key][0]
                if data:
                    cp = StateCheckpoint.from_dict(json.loads(data))
                    if latest is None or cp.timestamp > latest.timestamp:
                        latest = cp
            return latest

        return None

    async def _list_checkpoints(
        self,
        instance_key: str,
    ) -> List[StateCheckpoint]:
        """List all checkpoints for instance."""
        checkpoints = []

        for cp_type in CheckpointType:
            key = f"checkpoint:{instance_key}:{cp_type.value}"
            items = []
            if self._redis_client:
                items = await self._redis_client.lrange(key, 0, -1)
            elif key in self._memory_storage:
                items = self._memory_storage[key]
            for item in items:
                checkpoints.append(StateCheckpoint.from_dict(json.loads(item)))

        return checkpoints

    async def _cleanup_old_checkpoints(
        self,
        instance_key: str,
        checkpoint_type: CheckpointType,
    ) -> None:
        """Cleanup old checkpoints beyond limit."""
        key = f"checkpoint:{instance_key}:{checkpoint_type.value}"

        if self._redis_client:
            # Keep only max_checkpoints
            await self._redis_client.ltrim(key, 0, self._max_checkpoints - 1)
        elif key in self._memory_storage:
            self._memory_storage[key] = self._memory_storage[key][
                : self._max_checkpoints
            ]

    async def _delete_instance_checkpoints(self, instance_key: str) -> int:
        """Delete all checkpoints for an instance."""
        count = 0

        for cp_type in CheckpointType:
            key = f"checkpoint:{instance_key}:{cp_type.value}"
            if self._redis_client:
                deleted = await self._redis_client.delete(key)
                count += deleted
            elif key in self._memory_storage:
                count += len(self._memory_storage[key])
                del self._memory_storage[key]

        return count

    async def _get_all_instance_keys(self) -> List[str]:
        """Get all instance keys with checkpoints."""
        instance_keys = set()

        if self._redis_client:
            keys = await self._redis_client.keys("checkpoint:*")
            for key in keys:
                # Extract instance_key from "checkpoint:{instance_key}:{type}"
                parts = key.decode().split(":")
                if len(parts) >= 3:
                    instance_key = ":".join(parts[1:-1])
                    instance_keys.add(instance_key)
        else:
            for key in self._memory_storage.keys():
                # Extract instance_key from "checkpoint:{instance_key}:{type}"
                parts = key.split(":")
                if len(parts) >= 3:
                    instance_key = ":".join(parts[1:-1])
                    instance_keys.add(instance_key)

        return list(instance_keys)


# =============================================================================
# Checkpoint Helpers for Common Operations
# =============================================================================


async def checkpoint_lifecycle_state(
    recovery_service: StateRecoveryService,
    instance_key: str,
    lifecycle_state: str,
    extra_data: Optional[Dict[str, Any]] = None,
) -> StateCheckpoint:
    """Create lifecycle state checkpoint."""
    state_data = {
        "lifecycle_state": lifecycle_state,
        **(extra_data or {}),
    }
    return await recovery_service.create_checkpoint(
        instance_key=instance_key,
        checkpoint_type=CheckpointType.LIFECYCLE,
        state_data=state_data,
    )


async def checkpoint_conversation(
    recovery_service: StateRecoveryService,
    instance_key: str,
    conversation_id: str,
    messages: List[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None,
) -> StateCheckpoint:
    """Create conversation checkpoint."""
    state_data = {
        "conversation_id": conversation_id,
        "messages": messages,
        "context": context or {},
    }
    return await recovery_service.create_checkpoint(
        instance_key=instance_key,
        checkpoint_type=CheckpointType.CONVERSATION,
        state_data=state_data,
        metadata={"conversation_id": conversation_id},
    )


async def checkpoint_execution(
    recovery_service: StateRecoveryService,
    instance_key: str,
    execution_id: str,
    step_index: int,
    tool_calls: List[Dict[str, Any]],
) -> StateCheckpoint:
    """Create execution checkpoint."""
    state_data = {
        "execution_id": execution_id,
        "step_index": step_index,
        "tool_calls": tool_calls,
    }
    return await recovery_service.create_checkpoint(
        instance_key=instance_key,
        checkpoint_type=CheckpointType.EXECUTION,
        state_data=state_data,
        metadata={"execution_id": execution_id, "step_index": step_index},
    )
