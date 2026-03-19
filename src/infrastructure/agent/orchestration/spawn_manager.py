"""Spawn manager for parent-child agent lifecycle tracking.

Responsibilities:
- Parent-child relationship tracking via SpawnRecord
- Nesting depth enforcement (max_spawn_depth)
- Cascade stop (recursively stop children when parent stops)
- Integration with SubAgentRunRegistry for run lifecycle
- SpawnRecord CRUD (create, find_children, update_status)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.model.agent.spawn_record import SpawnRecord
from src.infrastructure.agent.orchestration.session_registry import (
    AgentSessionRegistry,
)
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry

logger = logging.getLogger(__name__)

# Default maximum nesting depth for spawned agents.
DEFAULT_MAX_SPAWN_DEPTH = 5


class SpawnDepthExceededError(Exception):
    """Raised when a spawn request would exceed the maximum nesting depth."""

    def __init__(self, current_depth: int, max_depth: int) -> None:
        self.current_depth = current_depth
        self.max_depth = max_depth
        super().__init__(f"Spawn depth {current_depth} would exceed max {max_depth}")


class SpawnManager:
    """Manages parent-child agent spawn lifecycle.

    Thread-safe via asyncio.Lock. Stores SpawnRecords in memory,
    keyed by child_session_id for O(1) lookup. Provides:

    - ``register_spawn``: Create a SpawnRecord and optionally register
      a run in the SubAgentRunRegistry.
    - ``find_children``: List direct children of a parent session.
    - ``find_descendants``: Recursively list all descendants.
    - ``get_spawn_depth``: Compute current nesting depth for a session.
    - ``update_status``: Update a spawn record's status.
    - ``cascade_stop``: Recursively stop an agent and all children.
    - ``cleanup_session``: Remove records for a completed session.
    """

    def __init__(
        self,
        session_registry: AgentSessionRegistry,
        run_registry: SubAgentRunRegistry | None = None,
        max_spawn_depth: int = DEFAULT_MAX_SPAWN_DEPTH,
    ) -> None:
        self._session_registry = session_registry
        self._run_registry = run_registry
        self._max_spawn_depth = max(1, max_spawn_depth)
        self._lock = asyncio.Lock()

        # Primary index: child_session_id -> SpawnRecord
        self._records_by_child_session: dict[str, SpawnRecord] = {}
        # Secondary index: parent_session_id -> set of child_session_ids
        self._children_by_parent: dict[str, set[str]] = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def max_spawn_depth(self) -> int:
        """Configured maximum spawn nesting depth."""
        return self._max_spawn_depth

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

        Parameters
        ----------
        parent_agent_id:
            ID of the parent agent performing the spawn.
        child_agent_id:
            ID of the child agent being spawned.
        child_session_id:
            Unique session/conversation ID for the child.
        project_id:
            Multi-tenant project scope.
        mode:
            SpawnMode.RUN (one-shot) or SpawnMode.SESSION (persistent).
        task_summary:
            Brief description of what the child was asked to do.
        parent_session_id:
            Session ID of the parent (for depth calculation).
        conversation_id:
            Conversation ID for RunRegistry integration.
        metadata:
            Additional metadata to attach to the run record.

        Returns
        -------
        SpawnRecord
            The registered spawn record.

        Raises
        ------
        SpawnDepthExceededError
            If the spawn would exceed ``max_spawn_depth``.
        """
        async with self._lock:
            # Enforce nesting depth.
            depth = self._compute_depth_locked(parent_session_id)
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

            # Primary index.
            self._records_by_child_session[child_session_id] = record

            # Secondary index.
            if parent_session_id:
                self._children_by_parent.setdefault(parent_session_id, set()).add(child_session_id)

            logger.info(
                "Registered spawn: parent=%s child=%s session=%s depth=%d mode=%s",
                parent_agent_id,
                child_agent_id,
                child_session_id,
                depth + 1,
                mode.value,
            )

        # Register in SubAgentRunRegistry if available (outside lock).
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
        """List direct child spawn records for a parent session.

        Parameters
        ----------
        parent_session_id:
            Session ID of the parent.
        status:
            If provided, filter children by status.

        Returns
        -------
        list[SpawnRecord]
            Direct children, sorted by creation time (oldest first).
        """
        async with self._lock:
            child_ids = self._children_by_parent.get(parent_session_id, set())
            children = [
                self._records_by_child_session[cid]
                for cid in child_ids
                if cid in self._records_by_child_session
            ]
        if status:
            children = [c for c in children if c.status == status]
        children.sort(key=lambda r: r.created_at)
        return children

    async def find_descendants(
        self,
        session_id: str,
        *,
        include_self: bool = False,
    ) -> list[SpawnRecord]:
        """Recursively find all descendant spawn records.

        Parameters
        ----------
        session_id:
            Root session ID to start traversal from.
        include_self:
            If True and session_id is itself a child spawn,
            include its own record in the result.

        Returns
        -------
        list[SpawnRecord]
            All descendants, breadth-first order.
        """
        async with self._lock:
            result: list[SpawnRecord] = []
            if include_self:
                own = self._records_by_child_session.get(session_id)
                if own:
                    result.append(own)

            queue = [session_id]
            visited: set[str] = {session_id}
            while queue:
                current = queue.pop(0)
                child_ids = self._children_by_parent.get(current, set())
                for cid in sorted(child_ids):
                    if cid in visited:
                        continue
                    visited.add(cid)
                    rec = self._records_by_child_session.get(cid)
                    if rec:
                        result.append(rec)
                        queue.append(cid)

        return result

    async def get_record(self, child_session_id: str) -> SpawnRecord | None:
        """Get the spawn record for a child session."""
        async with self._lock:
            return self._records_by_child_session.get(child_session_id)

    async def get_spawn_depth(self, session_id: str | None) -> int:
        """Compute the nesting depth for a session.

        Depth 0 means the session is a root (not a spawned child).
        Depth 1 means it was spawned by a root, etc.

        Parameters
        ----------
        session_id:
            The session to check. Returns 0 if None or unknown.
        """
        async with self._lock:
            return self._compute_depth_locked(session_id)

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

        Because SpawnRecord is frozen, this replaces the record with
        a new instance carrying the updated status.

        Parameters
        ----------
        child_session_id:
            The child session whose record to update.
        new_status:
            The new status string (e.g. ``"completed"``, ``"failed"``,
            ``"stopped"``).
        conversation_id:
            If provided, also updates the RunRegistry run status.

        Returns
        -------
        SpawnRecord | None
            The updated record, or None if not found.
        """
        async with self._lock:
            old = self._records_by_child_session.get(child_session_id)
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
            self._records_by_child_session[child_session_id] = updated

        # Mirror status to RunRegistry if available.
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

        Parameters
        ----------
        session_id:
            The root session to stop.
        project_id:
            Project scope.
        conversation_id:
            If provided, updates RunRegistry for each stopped session.
        on_stop:
            Optional async callback ``(session_id, agent_id) -> None``
            invoked for each stopped session. Use to cancel running
            tasks, abort LLM calls, etc.

        Returns
        -------
        list[str]
            All session IDs that were stopped (children first, root last).
        """
        descendants = await self.find_descendants(session_id)
        # Reverse so deepest children are stopped first.
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

        # Stop the root session itself (if it is a spawned child).
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
        """Remove all records associated with a child session.

        Call after a session is fully complete and no longer needed.
        """
        async with self._lock:
            record = self._records_by_child_session.pop(child_session_id, None)
            if record is None:
                return

            # Clean secondary index: find which parent owned this child.
            for parent_id, child_set in list(self._children_by_parent.items()):
                child_set.discard(child_session_id)
                if not child_set:
                    del self._children_by_parent[parent_id]

            # Also clean any entries where this session was a parent.
            orphaned_children = self._children_by_parent.pop(child_session_id, set())
            for orphan_id in orphaned_children:
                self._records_by_child_session.pop(orphan_id, None)

            logger.debug(
                "Cleaned up session=%s (orphaned %d children)",
                child_session_id,
                len(orphaned_children),
            )

    async def cleanup_project(self, project_id: str) -> int:
        """Remove all spawn records for a project.

        Returns the number of records removed.
        """
        async with self._lock:
            to_remove = [
                sid
                for sid, rec in self._records_by_child_session.items()
                if rec.project_id == project_id
            ]
            for sid in to_remove:
                self._records_by_child_session.pop(sid, None)
            self._rebuild_secondary_index_locked()
            return len(to_remove)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    async def get_stats(self) -> dict[str, Any]:
        """Return diagnostic statistics about the spawn manager."""
        async with self._lock:
            total = len(self._records_by_child_session)
            by_status: dict[str, int] = {}
            by_mode: dict[str, int] = {}
            for rec in self._records_by_child_session.values():
                by_status[rec.status] = by_status.get(rec.status, 0) + 1
                mode_val = rec.mode.value
                by_mode[mode_val] = by_mode.get(mode_val, 0) + 1
            return {
                "total_records": total,
                "parent_count": len(self._children_by_parent),
                "by_status": by_status,
                "by_mode": by_mode,
                "max_spawn_depth": self._max_spawn_depth,
            }

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _compute_depth_locked(self, session_id: str | None) -> int:
        """Compute nesting depth by walking parent chain. Lock must be held."""
        if not session_id:
            return 0
        depth = 0
        current = session_id
        visited: set[str] = set()
        while current and current not in visited:
            visited.add(current)
            record = self._records_by_child_session.get(current)
            if record is None:
                break
            depth += 1
            # Walk up: find which parent session spawned ``current``.
            current = self._find_parent_session_locked(current)
        return depth

    def _find_parent_session_locked(self, child_session_id: str) -> str | None:
        """Find the parent session that spawned a child. Lock must be held."""
        for parent_sid, children in self._children_by_parent.items():
            if child_session_id in children:
                return parent_sid
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

        # Unregister from session registry.
        await self._session_registry.unregister(
            conversation_id=record.child_session_id,
            project_id=project_id,
        )

        # Invoke optional callback.
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

    def _rebuild_secondary_index_locked(self) -> None:
        """Rebuild _children_by_parent from primary index. Lock must be held.

        Since SpawnRecord is frozen and doesn't store parent_session_id,
        we reconstruct from the _children_by_parent entries that still
        reference valid child sessions.
        """
        new_index: dict[str, set[str]] = {}
        valid_children = set(self._records_by_child_session.keys())
        for parent_sid, child_set in self._children_by_parent.items():
            remaining = child_set & valid_children
            if remaining:
                new_index[parent_sid] = remaining
        self._children_by_parent = new_index
