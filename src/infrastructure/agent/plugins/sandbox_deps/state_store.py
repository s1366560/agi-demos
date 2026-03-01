"""Redis-backed state store for dependency installation tracking.

Persists DepsStateRecord objects to Redis, tracking dependency installation
state per (plugin, project, sandbox) triple. Follows the same key/index/TTL
patterns as SandboxToolRegistry but fixes the str() vs json.dumps() bug.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from .models import DepsStateRecord, PreparedState

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class DepsStateStore:
    """Redis-backed store for dependency installation state.

    Follows the same key/index/TTL patterns as SandboxToolRegistry.
    """

    _KEY_PREFIX = "deps:state:"
    _TRACKING_KEY = "deps:state:tracking"
    _PROJECT_PREFIX = "deps:state:project:"
    _DEFAULT_TTL = 7200  # 2 hours (longer than SandboxToolRegistry's 1h since deps are expensive)

    def __init__(
        self,
        redis_client: Redis | None = None,
        ttl: int | None = None,
    ) -> None:
        """Initialize the state store.

        Args:
            redis_client: Async Redis client (decode_responses=True expected).
            ttl: TTL in seconds for Redis keys. Defaults to 7200 (2 hours).
        """
        self._redis = redis_client
        self._ttl = ttl if ttl is not None else self._DEFAULT_TTL

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _record_key(plugin_id: str, sandbox_id: str) -> str:
        """Build the Redis key for a single record."""
        return f"deps:state:{plugin_id}:{sandbox_id}"

    @staticmethod
    def _compound_id(plugin_id: str, sandbox_id: str) -> str:
        """Build the compound member stored in sets."""
        return f"{plugin_id}:{sandbox_id}"

    @staticmethod
    def _project_key(project_id: str) -> str:
        """Build the Redis key for a project index set."""
        return f"deps:state:project:{project_id}"

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_record(record: DepsStateRecord) -> str:
        """Serialize a DepsStateRecord to a JSON string.

        Uses json.dumps (not str()) to produce valid JSON that can be
        reliably deserialized with json.loads.
        """
        state_dict: dict[str, Any] | None = None
        if record.state is not None:
            state_dict = {
                "plugin_id": record.state.plugin_id,
                "deps_hash": record.state.deps_hash,
                "sandbox_image_digest": record.state.sandbox_image_digest,
                "prepared_at": record.state.prepared_at.isoformat(),
                "venv_path": record.state.venv_path,
            }

        data: dict[str, Any] = {
            "plugin_id": record.plugin_id,
            "project_id": record.project_id,
            "sandbox_id": record.sandbox_id,
            "state": state_dict,
            "last_check": record.last_check.isoformat(),
            "install_attempts": record.install_attempts,
            "last_error": record.last_error,
        }
        return json.dumps(data)

    @staticmethod
    def _deserialize_record(raw: str) -> DepsStateRecord:
        """Deserialize a JSON string into a DepsStateRecord."""
        data: dict[str, Any] = json.loads(raw)

        state: PreparedState | None = None
        if data.get("state") is not None:
            s = data["state"]
            state = PreparedState(
                plugin_id=s["plugin_id"],
                deps_hash=s["deps_hash"],
                sandbox_image_digest=s["sandbox_image_digest"],
                prepared_at=datetime.fromisoformat(s["prepared_at"]),
                venv_path=s["venv_path"],
            )

        return DepsStateRecord(
            plugin_id=data["plugin_id"],
            project_id=data["project_id"],
            sandbox_id=data["sandbox_id"],
            state=state,
            last_check=datetime.fromisoformat(data["last_check"]),
            install_attempts=data.get("install_attempts", 0),
            last_error=data.get("last_error"),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def save(self, record: DepsStateRecord) -> None:
        """Persist a DepsStateRecord to Redis.

        Stores the record at ``{prefix}{plugin_id}:{sandbox_id}``, adds
        the compound key to the tracking set, and adds it to the project
        index set.

        Args:
            record: The record to persist.
        """
        if not self._redis:
            logger.warning("[DepsStateStore] No Redis client -- skipping save")
            return

        key = self._record_key(record.plugin_id, record.sandbox_id)
        compound = self._compound_id(record.plugin_id, record.sandbox_id)
        project_key = self._project_key(record.project_id)

        try:
            # Store serialized record with TTL
            await self._redis.set(key, self._serialize_record(record), ex=self._ttl)

            # Add to tracking set
            await cast(Awaitable[int], self._redis.sadd(self._TRACKING_KEY, compound))

            # Add to project index set
            await cast(Awaitable[int], self._redis.sadd(project_key, compound))

            logger.debug(
                "[DepsStateStore] Saved record plugin=%s sandbox=%s project=%s",
                record.plugin_id,
                record.sandbox_id,
                record.project_id,
            )
        except Exception as e:
            logger.warning("[DepsStateStore] Failed to save record to Redis: %s", e)

    async def load(self, plugin_id: str, sandbox_id: str) -> DepsStateRecord | None:
        """Load a DepsStateRecord from Redis.

        Args:
            plugin_id: Plugin identifier.
            sandbox_id: Sandbox instance identifier.

        Returns:
            The deserialized record, or None if not found or Redis unavailable.
        """
        if not self._redis:
            logger.warning("[DepsStateStore] No Redis client -- cannot load")
            return None

        key = self._record_key(plugin_id, sandbox_id)
        try:
            data = await self._redis.get(key)
            if not data:
                return None
            return self._deserialize_record(data)
        except Exception as e:
            logger.warning("[DepsStateStore] Failed to load from Redis: %s", e)
            return None

    async def remove(self, plugin_id: str, sandbox_id: str, project_id: str) -> bool:
        """Delete a record and remove it from all index sets.

        Args:
            plugin_id: Plugin identifier.
            sandbox_id: Sandbox instance identifier.
            project_id: Project identifier (needed for project index cleanup).

        Returns:
            True if the key existed and was deleted, False otherwise.
        """
        if not self._redis:
            logger.warning("[DepsStateStore] No Redis client -- cannot remove")
            return False

        key = self._record_key(plugin_id, sandbox_id)
        compound = self._compound_id(plugin_id, sandbox_id)
        project_key = self._project_key(project_id)

        try:
            deleted = await self._redis.delete(key)

            # Remove from tracking set
            await cast(Awaitable[int], self._redis.srem(self._TRACKING_KEY, compound))

            # Remove from project index set
            await cast(Awaitable[int], self._redis.srem(project_key, compound))

            logger.debug(
                "[DepsStateStore] Removed record plugin=%s sandbox=%s",
                plugin_id,
                sandbox_id,
            )
            return bool(deleted)
        except Exception as e:
            logger.warning("[DepsStateStore] Failed to remove from Redis: %s", e)
            return False

    async def list_by_project(self, project_id: str) -> list[DepsStateRecord]:
        """Get all records for a project using the project index set.

        Args:
            project_id: Project identifier.

        Returns:
            List of DepsStateRecord objects for this project (may be empty).
        """
        if not self._redis:
            logger.warning("[DepsStateStore] No Redis client -- cannot list by project")
            return []

        project_key = self._project_key(project_id)
        try:
            members: set[Any] = await cast(Awaitable[set[Any]], self._redis.smembers(project_key))

            records: list[DepsStateRecord] = []
            for compound in members:
                parts = str(compound).split(":", 1)
                if len(parts) != 2:
                    continue
                p_id, s_id = parts
                record = await self.load(p_id, s_id)
                if record is not None:
                    records.append(record)

            return records
        except Exception as e:
            logger.warning("[DepsStateStore] Failed to list by project %s: %s", project_id, e)
            return []

    async def list_by_sandbox(self, sandbox_id: str) -> list[DepsStateRecord]:
        """Get all records matching a sandbox_id by scanning the tracking set.

        This performs a scan of the tracking set and filters by suffix match.

        Args:
            sandbox_id: Sandbox instance identifier.

        Returns:
            List of DepsStateRecord objects for this sandbox (may be empty).
        """
        if not self._redis:
            logger.warning("[DepsStateStore] No Redis client -- cannot list by sandbox")
            return []

        try:
            members: set[Any] = await cast(
                Awaitable[set[Any]], self._redis.smembers(self._TRACKING_KEY)
            )

            suffix = f":{sandbox_id}"
            records: list[DepsStateRecord] = []
            for compound in members:
                compound_str = str(compound)
                if not compound_str.endswith(suffix):
                    continue
                p_id = compound_str[: -len(suffix)]
                record = await self.load(p_id, sandbox_id)
                if record is not None:
                    records.append(record)

            return records
        except Exception as e:
            logger.warning("[DepsStateStore] Failed to list by sandbox %s: %s", sandbox_id, e)
            return []

    async def refresh_all(self) -> int:
        """Restore all records from the tracking set.

        Iterates every compound key in the tracking set and loads the
        corresponding record from Redis. This is analogous to
        SandboxToolRegistry.refresh_all_from_redis.

        Returns:
            Number of records successfully loaded.
        """
        if not self._redis:
            return 0

        try:
            members: set[Any] = await cast(
                Awaitable[set[Any]], self._redis.smembers(self._TRACKING_KEY)
            )

            loaded = 0
            for compound in members:
                parts = str(compound).split(":", 1)
                if len(parts) != 2:
                    continue
                p_id, s_id = parts
                record = await self.load(p_id, s_id)
                if record is not None:
                    loaded += 1

            logger.info("[DepsStateStore] Refreshed %d records from Redis", loaded)
            return loaded
        except Exception as e:
            logger.warning("[DepsStateStore] Failed to refresh from Redis: %s", e)
            return 0

    async def cleanup_expired(self) -> int:
        """Remove tracking entries whose Redis keys have expired.

        Iterates the tracking set and checks whether the corresponding
        data key still exists. Entries without a live key are removed
        from the tracking set (and any project index sets we can infer).

        Returns:
            Number of stale entries removed.
        """
        if not self._redis:
            return 0

        try:
            members: set[Any] = await cast(
                Awaitable[set[Any]], self._redis.smembers(self._TRACKING_KEY)
            )

            removed = 0
            for compound in members:
                parts = str(compound).split(":", 1)
                if len(parts) != 2:
                    continue
                p_id, s_id = parts
                key = self._record_key(p_id, s_id)
                exists = await self._redis.exists(key)
                if not exists:
                    # Key expired -- clean up tracking set
                    await cast(
                        Awaitable[int],
                        self._redis.srem(self._TRACKING_KEY, str(compound)),
                    )
                    removed += 1
                    logger.debug(
                        "[DepsStateStore] Cleaned expired entry plugin=%s sandbox=%s",
                        p_id,
                        s_id,
                    )

            if removed:
                logger.info("[DepsStateStore] Cleaned up %d expired tracking entries", removed)
            return removed
        except Exception as e:
            logger.warning("[DepsStateStore] Failed to clean up expired entries: %s", e)
            return 0
