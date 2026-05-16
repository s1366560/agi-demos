"""Sandbox Idle Reaper - Background task for auto-destroying idle sandboxes.

Periodically checks for sandboxes that have exceeded the idle timeout threshold
and terminates them, optionally persisting workspace state via WorkspaceSyncService
before destruction.

This is the key piece of the hybrid sandbox lifecycle:
- Creation: lazy on first tool use (handled by get_or_create_sandbox)
- Keep-alive: during active conversation (handled by mark_accessed in execute_tool)
- Recycle: auto-destroy after idle timeout (THIS MODULE)
- Rebuild: auto-rebuild on next conversation (handled by get_or_create_sandbox + post_create_restore)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from inspect import isawaitable
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from src.application.services.workspace_sync_service import WorkspaceSyncService
    from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
        MCPSandboxAdapter,
    )

from src.domain.model.sandbox.project_sandbox import ProjectSandbox
from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
    SqlProjectSandboxRepository,
)

logger = logging.getLogger(__name__)


class SandboxIdleReaper:
    """Background task that periodically terminates idle sandboxes.

    Uses a repository factory to create per-iteration DB sessions (not a long-lived
    session), ensuring clean transaction boundaries on each sweep.

    Optionally calls WorkspaceSyncService.pre_destroy_sync before termination to
    persist workspace state for later restoration.

    Attributes:
        _idle_timeout_seconds: Max idle time before sandbox is reaped.
        _check_interval_seconds: How often to run the sweep.
        _session_factory: Callable that yields per-iteration AsyncSessions.
        _sandbox_adapter: Adapter for terminating sandbox containers.
        _workspace_sync: Optional workspace sync service for pre-destroy hooks.
        _task: The background asyncio task reference.
        _running: Whether the reaper loop is active.
    """

    def __init__(
        self,
        idle_timeout_seconds: int,
        check_interval_seconds: int,
        session_factory: Callable[[], AsyncSession],
        sandbox_adapter: MCPSandboxAdapter,
        workspace_sync: WorkspaceSyncService | None = None,
        is_recently_active: Callable[[str, int], Awaitable[bool] | bool] | None = None,
        recent_activity_window_seconds: int = 300,
    ) -> None:
        self._idle_timeout_seconds = idle_timeout_seconds
        self._check_interval_seconds = check_interval_seconds
        self._session_factory = session_factory
        self._sandbox_adapter = sandbox_adapter
        self._workspace_sync = workspace_sync
        self._is_recently_active = is_recently_active
        self._recent_activity_window_seconds = recent_activity_window_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        """Whether the reaper background loop is currently active."""
        return self._running

    def _is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Start the background reaper loop.

        Safe to call multiple times; subsequent calls are no-ops.
        """
        if self._running:
            logger.debug("SandboxIdleReaper already running, ignoring start()")
            return

        if self._idle_timeout_seconds <= 0:
            logger.info(
                "SandboxIdleReaper disabled (idle_timeout_seconds=%d)",
                self._idle_timeout_seconds,
            )
            return

        self._running = True
        self._task = asyncio.create_task(self._reaper_loop(), name="sandbox-idle-reaper")
        logger.info(
            "SandboxIdleReaper started: timeout=%ds, interval=%ds",
            self._idle_timeout_seconds,
            self._check_interval_seconds,
        )

    async def stop(self) -> None:
        """Stop the background reaper loop gracefully."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("SandboxIdleReaper stopped")

    async def _reaper_loop(self) -> None:
        """Main loop: sleep then sweep, until stopped."""
        while self._is_running():
            try:
                await asyncio.sleep(self._check_interval_seconds)
                if not self._is_running():
                    break
                await self._sweep()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("SandboxIdleReaper sweep failed unexpectedly")
                # Continue running; next sweep will retry

    async def _sweep(self) -> list[str]:
        """Find and terminate all sandboxes exceeding the idle timeout.

        Creates a fresh DB session per sweep for clean transaction boundaries.

        Returns:
            List of terminated sandbox IDs.
        """
        terminated: list[str] = []

        async with self._session_factory() as session:
            repo = SqlProjectSandboxRepository(session)
            stale = await repo.find_stale(
                max_idle_seconds=self._idle_timeout_seconds,
                limit=100,
            )

            if not stale:
                return terminated

            logger.info(
                "SandboxIdleReaper found %d stale sandbox(es) (idle > %ds)",
                len(stale),
                self._idle_timeout_seconds,
            )

            for association in stale:
                try:
                    if await self._should_skip_stale_termination(association, session):
                        continue
                    await self._terminate_one(association, session)
                    terminated.append(association.sandbox_id)
                except Exception:
                    logger.exception(
                        "SandboxIdleReaper failed to terminate sandbox %s (project %s)",
                        association.sandbox_id,
                        association.project_id,
                    )

            # Commit all changes in a single transaction
            if terminated:
                await session.commit()
                logger.info(
                    "SandboxIdleReaper terminated %d sandbox(es): %s",
                    len(terminated),
                    terminated,
                )

        return terminated

    async def _should_skip_stale_termination(
        self,
        association: ProjectSandbox,
        session: AsyncSession,
    ) -> bool:
        """Return True when stale DB record has recent in-memory adapter activity."""
        checker = self._is_recently_active
        if checker is None:
            return False

        try:
            maybe_result = checker(
                association.sandbox_id,
                self._recent_activity_window_seconds,
            )
            if isawaitable(maybe_result):
                is_recent = bool(await maybe_result)
            else:
                is_recent = bool(maybe_result)
        except Exception:
            logger.warning(
                "SandboxIdleReaper recent-activity check failed for sandbox %s; "
                "continuing with termination path",
                association.sandbox_id,
                exc_info=True,
            )
            return False

        if not is_recent:
            return False

        logger.info(
            "SandboxIdleReaper skipping stale sandbox %s due to recent adapter activity "
            "(window=%ss)",
            association.sandbox_id,
            self._recent_activity_window_seconds,
        )
        association.last_accessed_at = datetime.now(UTC)
        repo = SqlProjectSandboxRepository(session)
        await repo.save(association)
        return True

    async def _terminate_one(
        self,
        association: ProjectSandbox,
        session: AsyncSession,
    ) -> None:
        """Terminate a single idle sandbox, with optional workspace sync.

        Steps:
        1. Call WorkspaceSyncService.pre_destroy_sync (if configured) to persist
           workspace state before the container is destroyed.
        2. Terminate the sandbox container via the adapter.
        3. Mark the association as TERMINATED in the database.

        Args:
            association: The stale sandbox association to terminate.
            session: Active DB session (caller commits).
        """
        sandbox_id = association.sandbox_id
        project_id = association.project_id

        # Step 1: Pre-destroy workspace sync
        if self._workspace_sync is not None:
            try:
                await self._workspace_sync.pre_destroy_sync(
                    sandbox_id=sandbox_id,
                    project_id=project_id,
                    tenant_id=association.tenant_id,
                )
                logger.debug(
                    "SandboxIdleReaper: workspace synced before termination "
                    "(sandbox %s, project %s)",
                    sandbox_id,
                    project_id,
                )
            except Exception:
                logger.warning(
                    "SandboxIdleReaper: workspace sync failed for sandbox %s, "
                    "proceeding with termination anyway",
                    sandbox_id,
                    exc_info=True,
                )

        # Step 2: Terminate the container
        await self._sandbox_adapter.terminate_sandbox(sandbox_id)

        # Step 3: Update DB status
        association.mark_terminated()
        repo = SqlProjectSandboxRepository(session)
        await repo.save(association)

        logger.info(
            "SandboxIdleReaper: terminated idle sandbox %s (project %s)",
            sandbox_id,
            project_id,
        )
