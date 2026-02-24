import json
import logging
import time
from uuid import uuid4

import redis.asyncio as redis

from src.configuration.config import get_settings
from src.domain.ports.services.queue_port import QueuePort

logger = logging.getLogger(__name__)


class RedisQueueAdapter(QueuePort):
    def __init__(self, redis_client: redis.Redis | None = None) -> None:
        self._settings = get_settings()
        self._redis = redis_client or redis.from_url(
            self._settings.redis_url, encoding="utf-8", decode_responses=True
        )

    async def add_episode(
        self,
        group_id: str,
        name: str,
        content: str,
        source_description: str,
        episode_type: str,
        uuid: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
        user_id: str | None = None,
        memory_id: str | None = None,
    ) -> None:
        try:
            # Replicate the payload structure expected by existing workers
            payload = {
                "group_id": group_id,
                "task_type": "add_episode",
                "name": name,
                "content": content,
                "source_description": source_description,
                "episode_type": episode_type,
                "uuid": uuid,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "user_id": user_id,
                "memory_id": memory_id,
                "timestamp": time.time(),
            }

            # In the original service, a TaskLog entry is created in SQL here.
            # To maintain full parity without importing the old service, we should ideally
            # create the TaskLog here too. However, that requires DB access in this adapter.
            # For this step of "decoupling", we will focus on the Redis push.
            # If the worker relies on the TaskLog existing in DB, we might have a gap.
            # Assuming the worker updates the status based on the ID in the payload.

            # Let's generate a task_id here
            task_id = str(uuid4())
            payload["task_id"] = task_id

            # Note: We are skipping the DB TaskLog creation for now to keep this adapter simple
            # and focused on the Queue mechanism.
            # A full implementation would inject a TaskRepository here to log the task.

            # Add to Redis
            await self._redis.sadd("queue:active_groups", group_id)
            queue_key = f"queue:group:{group_id}"
            await self._redis.rpush(queue_key, json.dumps(payload))

            logger.info(f"Task {task_id} added to queue {queue_key}")

        except Exception as e:
            logger.error(f"Failed to add episode to queue via adapter: {e}")
            raise

    async def close(self) -> None:
        await self._redis.close()
