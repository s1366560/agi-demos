"""Redis-backed spawn manager for parent-child agent lifecycle tracking.

Mirrors the in-memory ``SpawnManager`` interface but persists all state
to Redis, enabling distributed multi-process agent coordination that
survives process restarts.

Redis key layout:
    ``agent:spawn:{child_session_id}``            → JSON of SpawnRecord.to_dict()
    ``agent:spawn:children:{parent_session_id}``   → SET of child_session_ids
    ``agent:spawn:project:{project_id}``           → SET of child_session_ids
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, cast

from redis.asyncio import Redis

from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.model.agent.spawn_record import SpawnRecord
from src.infrastructure.agent.orchestration.session_registry import (
    AgentSessionRegistry,
)
from src.infrastructure.agent.orchestration.spawn_manager import (
    SpawnDepthExceededError,
)
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry

logger = logging.getLogger(__name__)

DEFAULT_MAX_SPAWN_DEPTH = 5


class RedisSpawnManager:
    """Redis-backed spawn manager for parent-child agent lifecycle.

    All state is persisted to Redis using atomic pipelines. No in-memory
    caches or asyncio locks — Redis is the synchronization layer.

    Public API mirrors ``SpawnManager`` exactly so callers can swap
    implementations via dependency injection.
    """

    def __init__(
        self,
        redis_client: Redis,
        *,
        namespace: str = "agent:spawn",
        ttl_seconds: int = 86400,
        max_spawn_depth: int = DEFAULT_MAX_SPAWN_DEPTH,
        session_registry: AgentSessionRegistry | None = None,
        run_registry: SubAgentRunRegistry | None = None,
    ) -> None:
        self._redis = redis_client
        self._namespace = namespace
        self._ttl = ttl_seconds
        self._max_spawn_depth = max(1, max_spawn_depth)
        self._session_registry = session_registry
        self._run_registry = run_registry

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def max_spawn_depth(self) -> int:
        """Configured maximum spawn nesting depth."""
        return self._max_spawn_depth

    # ------------------------------------------------------------------
    # Key Helpers
    # ------------------------------------------------------------------

    def _record_key(self, child_session_id: str) -> str:
        return f"{self._namespace}:{child_session_id}"

    def _children_key(self, parent_session_id: str) -> str:
        return f"{self._namespace}:children:{parent_session_id}"

    def _project_key(self, project_id: str) -> str:
        return f"{self._namespace}:project:{project_id}"

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize(record: SpawnRecord) -> str:
        return json.dumps(record.to_dict())

    @staticmethod
    def _deserialize(raw: str | bytes) -> SpawnRecord:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data: dict[str, Any] = json.loads(raw)
        return SpawnRecord.from_dict(data)

    # ------------------------------------------------------------------
    # Spawn Registration
    # ------------------------------------------------------------------

    async def register_spawn(
        self,
        parent_agent_id: str,
        child_agent_id: str,
        child_session_id: str,
        project_id: str,
        *,
        mode: SpawnMode = SpawnMode.RUN,
        task_summary: str = "",
        parent_session_id: str | None = None,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SpawnRecord:
        """Register a new parent-child spawn relationship.

        Raises
        ------
        SpawnDepthExceededError
            If the spawn would exceed ``max_spawn_depth``.
        """
        depth = await self.get_spawn_depth(parent_session_id)
        if depth >= self._max_spawn_depth:
            raise SpawnDepthExceededError(
                current_depth=depth,
                max_depth=self._max_spawn_depth,
            )

        record = SpawnRecord(
            parent_agent_id=parent_agent_id,
            child_agent_id=child_agent_id,
            child_session_id=child_session_id,
            project_id=project_id,
            mode=mode,
            task_summary=task_summary,
        )

        try:
            pipe = self._redis.pipeline()
            pipe.setex(
                self._record_key(child_session_id),
                self._ttl,
                self._serialize(record),
            )
            if parent_session_id:
                pipe.sadd(self._children_key(parent_session_id), child_session_id)  # type: ignore[arg-type]
            pipe.sadd(self._project_key(project_id), child_session_id)  # type: ignore[arg-type]
            await pipe.execute()
        except Exception:
            logger.exception(
                "Failed to register spawn in Redis: child=%s",
                child_session_id,
            )

        logger.info(
            "Registered spawn: parent=%s child=%s session=%s depth=%d mode=%s",
            parent_agent_id,
            child_agent_id,
            child_session_id,
            depth + 1,
            mode.value,
        )

        if self._run_registry and conversation_id:
            run_metadata: dict[str, object] = {
                "spawn_record_id": record.id,
                "parent_agent_id": parent_agent_id,
                "child_agent_id": child_agent_id,
                "spawn_mode": mode.value,
            }
            if metadata:
                run_metadata.update(metadata)
            self._run_registry.create_run(
                conversation_id=conversation_id,
                subagent_name=child_agent_id,
                task=task_summary,
                metadata=run_metadata,
                run_id=record.id,
                parent_run_id=parent_session_id,
            )

        return record

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def find_children(
        self,
        parent_session_id: str,
        *,
        status: str | None = None,
    ) -> list[SpawnRecord]:
        """List direct child spawn records for a parent session."""
        try:
            members: set[Any] = await cast(
                Awaitable[set[Any]],
                self._redis.smembers(self._children_key(parent_session_id)),
            )
        except Exception:
            logger.exception(
                "Failed to find children from Redis: parent=%s",
                parent_session_id,
            )
            return []

        children: list[SpawnRecord] = []
        for member in members:
            if isinstance(member, bytes):
                member = member.decode("utf-8")
            child_id = str(member)
            record = await self.get_record(child_id)
            if record is not None:
                if status is None or record.status == status:
                    children.append(record)

        children.sort(key=lambda r: r.created_at)
        return children

    async def find_descendants(
        self,
        session_id: str,
        *,
        include_self: bool = False,
    ) -> list[SpawnRecord]:
        """Recursively find all descendant spawn records (BFS)."""
        result: list[SpawnRecord] = []
        if include_self:
            own = await self.get_record(session_id)
            if own:
                result.append(own)

        queue = [session_id]
        visited: set[str] = {session_id}

        while queue:
            current = queue.pop(0)
            try:
                members: set[Any] = await cast(
                    Awaitable[set[Any]],
                    self._redis.smembers(self._children_key(current)),
                )
            except Exception:
                logger.exception(
                    "Failed to find descendants from Redis: session=%s",
                    current,
                )
                continue

            child_ids: list[str] = []
            for member in members:
                if isinstance(member, bytes):
                    member = member.decode("utf-8")
                child_ids.append(str(member))

            for cid in sorted(child_ids):
                if cid in visited:
                    continue
                visited.add(cid)
                rec = await self.get_record(cid)
                if rec:
                    result.append(rec)
                    queue.append(cid)

        return result

    async def get_record(self, child_session_id: str) -> SpawnRecord | None:
        """Get the spawn record for a child session."""
        try:
            raw = await self._redis.get(self._record_key(child_session_id))
            if raw is None:
                return None
            return self._deserialize(raw)
        except Exception:
            logger.exception(
                "Failed to get spawn record from Redis: session=%s",
                child_session_id,
            )
            return None

    async def get_spawn_depth(self, session_id: str | None) -> int:
        """Compute the nesting depth by walking the parent chain via Redis.

        NOTE: This performs an O(n) scan of children sets to find the
        parent of each session. For the MVP this is acceptable; a
        dedicated ``child->parent`` reverse index can be added later
        for O(1) parent lookups.
        """
        if not session_id:
            return 0
        depth = 0
        current: str | None = session_id
        visited: set[str] = set()
        while current and current not in visited:
            visited.add(current)
            record = await self.get_record(current)
            if record is None:
                break
            depth += 1
            current = await self._find_parent_session(current)
        return depth

    async def has_active_children(self, parent_session_id: str) -> bool:
        """Check if a parent session has any running children."""
        children = await self.find_children(parent_session_id, status="running")
        return len(children) > 0

    async def count_children(
        self,
        parent_session_id: str,
        *,
        status: str | None = None,
    ) -> int:
        """Count direct children of a parent session."""
        children = await self.find_children(parent_session_id, status=status)
        return len(children)

    # ------------------------------------------------------------------
    # Status Updates
    # ------------------------------------------------------------------

    async def update_status(
        self,
        child_session_id: str,
        new_status: str,
        *,
        conversation_id: str | None = None,
    ) -> SpawnRecord | None:
        """Update the status of a spawn record.

        Because SpawnRecord is frozen, this reads the existing record,
        creates a new instance with the updated status, and writes it back.
        """
        old = await self.get_record(child_session_id)
        if old is None:
            return None

        updated = SpawnRecord(
            id=old.id,
            parent_agent_id=old.parent_agent_id,
            child_agent_id=old.child_agent_id,
            child_session_id=old.child_session_id,
            project_id=old.project_id,
            mode=old.mode,
            task_summary=old.task_summary,
            status=new_status,
            created_at=old.created_at,
        )

        try:
            ttl = await self._redis.ttl(self._record_key(child_session_id))
            effective_ttl = ttl if isinstance(ttl, int) and ttl > 0 else self._ttl
            await self._redis.setex(
                self._record_key(child_session_id),
                effective_ttl,
                self._serialize(updated),
            )
        except Exception:
            logger.exception(
                "Failed to update spawn status in Redis: session=%s",
                child_session_id,
            )
            return None

        if self._run_registry and conversation_id:
            self._sync_run_registry_status(
                conversation_id=conversation_id,
                run_id=old.id,
                status=new_status,
            )

        logger.debug(
            "Updated spawn status: session=%s %s -> %s",
            child_session_id,
            old.status,
            new_status,
        )
        return updated

    # ------------------------------------------------------------------
    # Cascade Stop
    # ------------------------------------------------------------------

    async def cascade_stop(
        self,
        session_id: str,
        project_id: str,
        *,
        conversation_id: str | None = None,
        on_stop: Callable[[str, str], Coroutine[Any, Any, None]] | None = None,
    ) -> list[str]:
        """Recursively stop a session and all its children.

        Traverses the spawn tree depth-first (children before parent)
        to ensure clean teardown order.
        """
        descendants = await self.find_descendants(session_id)
        descendants.reverse()

        stopped: list[str] = []

        for record in descendants:
            if record.status != "running":
                continue
            await self._stop_single(
                record=record,
                project_id=project_id,
                conversation_id=conversation_id,
                on_stop=on_stop,
            )
            stopped.append(record.child_session_id)

        root_record = await self.get_record(session_id)
        if root_record and root_record.status == "running":
            await self._stop_single(
                record=root_record,
                project_id=project_id,
                conversation_id=conversation_id,
                on_stop=on_stop,
            )
            stopped.append(session_id)

        logger.info(
            "Cascade stop from session=%s stopped %d sessions",
            session_id,
            len(stopped),
        )
        return stopped

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup_session(self, child_session_id: str) -> None:
        """Remove all records associated with a child session."""
        record = await self.get_record(child_session_id)
        if record is None:
            return

        try:
            pipe = self._redis.pipeline()
            pipe.delete(self._record_key(child_session_id))
            pipe.srem(self._project_key(record.project_id), child_session_id)  # type: ignore[arg-type]
            await pipe.execute()
        except Exception:
            logger.exception(
                "Failed to cleanup session from Redis: session=%s",
                child_session_id,
            )
            return

        parent_sid = await self._find_parent_session(child_session_id)
        if parent_sid:
            try:
                await self._redis.srem(self._children_key(parent_sid), child_session_id)  # type: ignore[arg-type]
            except Exception:
                logger.exception(
                    "Failed to remove child from parent set: parent=%s child=%s",
                    parent_sid,
                    child_session_id,
                )

        try:
            children_key = self._children_key(child_session_id)
            orphans: set[Any] = await cast(
                Awaitable[set[Any]],
                self._redis.smembers(children_key),
            )
            if orphans:
                orphan_pipe = self._redis.pipeline()
                for orphan in orphans:
                    if isinstance(orphan, bytes):
                        orphan = orphan.decode("utf-8")
                    orphan_id = str(orphan)
                    orphan_pipe.delete(self._record_key(orphan_id))
                orphan_pipe.delete(children_key)
                await orphan_pipe.execute()

                logger.debug(
                    "Cleaned up session=%s (orphaned %d children)",
                    child_session_id,
                    len(orphans),
                )
        except Exception:
            logger.exception(
                "Failed to cleanup orphaned children: session=%s",
                child_session_id,
            )

    async def cleanup_project(self, project_id: str) -> int:
        """Remove all spawn records for a project.

        Returns the number of records removed.
        """
        project_key = self._project_key(project_id)

        try:
            members: set[Any] = await cast(
                Awaitable[set[Any]],
                self._redis.smembers(project_key),
            )
        except Exception:
            logger.exception(
                "Failed to list project members from Redis: project=%s",
                project_id,
            )
            return 0

        if not members:
            return 0

        child_session_ids: list[str] = []
        for member in members:
            if isinstance(member, bytes):
                member = member.decode("utf-8")
            child_session_ids.append(str(member))

        try:
            pipe = self._redis.pipeline()
            for csid in child_session_ids:
                pipe.delete(self._record_key(csid))
                pipe.delete(self._children_key(csid))
            pipe.delete(project_key)
            await pipe.execute()
        except Exception:
            logger.exception(
                "Failed to cleanup project from Redis: project=%s",
                project_id,
            )
            return 0

        logger.debug(
            "Cleaned up %d spawn records for project %s",
            len(child_session_ids),
            project_id,
        )
        return len(child_session_ids)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    async def get_stats(self) -> dict[str, Any]:
        """Return diagnostic statistics about the spawn manager."""
        total = 0
        by_status: dict[str, int] = {}
        by_mode: dict[str, int] = {}
        record_prefix = f"{self._namespace}:"
        children_prefix = f"{self._namespace}:children:"
        project_prefix = f"{self._namespace}:project:"
        parent_sessions: set[str] = set()

        try:
            cursor: int | bytes = 0
            while True:
                cursor, keys = await self._redis.scan(
                    cursor=int(cursor) if isinstance(cursor, int) else 0,
                    match=f"{record_prefix}*",
                    count=100,
                )
                for key in keys:
                    if isinstance(key, bytes):
                        key = key.decode("utf-8")
                    key_str = str(key)
                    if key_str.startswith(children_prefix):
                        parent_sessions.add(key_str[len(children_prefix) :])
                        continue
                    if key_str.startswith(project_prefix):
                        continue
                    raw = await self._redis.get(key_str)
                    if raw is None:
                        continue
                    record = self._deserialize(raw)
                    total += 1
                    by_status[record.status] = by_status.get(record.status, 0) + 1
                    mode_val = record.mode.value
                    by_mode[mode_val] = by_mode.get(mode_val, 0) + 1

                if cursor == 0:
                    break
        except Exception:
            logger.exception("Failed to compute spawn stats from Redis")

        return {
            "total_records": total,
            "parent_count": len(parent_sessions),
            "by_status": by_status,
            "by_mode": by_mode,
            "max_spawn_depth": self._max_spawn_depth,
        }

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    async def _find_parent_session(self, child_session_id: str) -> str | None:
        """Find the parent session that spawned a child.

        NOTE: O(n) scan — iterates all ``children:*`` keys. Acceptable
        for MVP; add a reverse index ``child->parent`` for O(1) later.
        """
        prefix = f"{self._namespace}:children:"
        try:
            cursor: int | bytes = 0
            while True:
                cursor, keys = await self._redis.scan(
                    cursor=int(cursor) if isinstance(cursor, int) else 0,
                    match=f"{prefix}*",
                    count=100,
                )
                for key in keys:
                    if isinstance(key, bytes):
                        key = key.decode("utf-8")
                    is_member: bool = await cast(
                        Awaitable[bool],
                        self._redis.sismember(str(key), child_session_id),
                    )
                    if is_member:
                        return str(key)[len(prefix) :]
                if cursor == 0:
                    break
        except Exception:
            logger.exception(
                "Failed to find parent session from Redis: child=%s",
                child_session_id,
            )
        return None

    async def _stop_single(
        self,
        record: SpawnRecord,
        project_id: str,
        *,
        conversation_id: str | None = None,
        on_stop: Callable[[str, str], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """Stop a single spawned session."""
        await self.update_status(
            child_session_id=record.child_session_id,
            new_status="stopped",
            conversation_id=conversation_id,
        )

        if self._session_registry:
            await self._session_registry.unregister(
                conversation_id=record.child_session_id,
                project_id=project_id,
            )

        if on_stop is not None:
            try:
                await on_stop(record.child_session_id, record.child_agent_id)
            except Exception:
                logger.warning(
                    "on_stop callback failed for session=%s",
                    record.child_session_id,
                    exc_info=True,
                )

    def _sync_run_registry_status(
        self,
        conversation_id: str,
        run_id: str,
        status: str,
    ) -> None:
        """Mirror spawn status to SubAgentRunRegistry (sync API)."""
        if not self._run_registry:
            return
        try:
            if status == "completed":
                self._run_registry.mark_completed(
                    conversation_id=conversation_id,
                    run_id=run_id,
                )
            elif status == "failed":
                self._run_registry.mark_failed(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    error="Spawn failed",
                )
            elif status in ("stopped", "cancelled"):
                self._run_registry.mark_cancelled(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    reason=f"Spawn {status}",
                )
        except Exception:
            logger.warning(
                "Failed to sync run registry status: run=%s status=%s",
                run_id,
                status,
                exc_info=True,
            )
