"""Periodic per-project reflection runner.

Drives ``ReflectionService.reflect_window`` on a fixed interval for an
externally-supplied set of project IDs. Mirrors the start/stop pattern of
``OutboxRetryWorker`` so it can be hosted in any FastAPI lifespan.

Per Agent-First: the *trigger* (interval timer + project list) is structural
and lives here. The *verdict* is delegated to ``ReflectorPort`` via
``ReflectionService``, which we never override.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from src.application.services.reflection_service import ReflectionService
from src.domain.model.flow.reflection_verdict import ReflectionVerdict

logger = logging.getLogger(__name__)

ProjectIdsProvider = Callable[[], Awaitable[list[str]]]
ReflectionServiceFactory = Callable[[str], Awaitable[ReflectionService | None]]
ReflectionCompleteEmitter = Callable[
    [str, list[ReflectionVerdict], Literal["success", "failed", "timeout", "unavailable"], str | None],
    Awaitable[None],
]


class ReflectionRunner:
    """Background loop that calls ``reflect_window`` per project on an interval.

    Construction does not start the loop — call ``start()`` once the event
    loop is running (typically from a FastAPI lifespan or an admin script).
    """

    def __init__(
        self,
        *,
        project_ids_provider: ProjectIdsProvider,
        service_factory: ReflectionServiceFactory,
        interval_seconds: float = 600.0,
        per_project_timeout_seconds: float = 60.0,
        completion_emitter: ReflectionCompleteEmitter | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if per_project_timeout_seconds <= 0:
            raise ValueError("per_project_timeout_seconds must be positive")
        self._project_ids_provider = project_ids_provider
        self._service_factory = service_factory
        self._interval = interval_seconds
        self._timeout = per_project_timeout_seconds
        self._completion_emitter = completion_emitter
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def configure_completion_emitter(
        self, emitter: ReflectionCompleteEmitter | None
    ) -> None:
        """Update the optional ``reflection_complete`` emitter at runtime."""
        self._completion_emitter = emitter

    def start(self) -> None:
        """Start the background loop. Idempotent."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="reflection-runner")
        logger.info(
            "ReflectionRunner started (interval=%ss, per-project timeout=%ss)",
            self._interval,
            self._timeout,
        )

    async def stop(self) -> None:
        """Cancel the loop and await its exit."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        logger.info("ReflectionRunner stopped")

    async def run_once(self, project_id: str) -> list[ReflectionVerdict]:
        """Run a single reflection cycle for one project.

        Returns the applied verdicts (possibly empty). Suitable for tests,
        admin CLIs, or agent-tool invocations.
        """
        service = await self._service_factory(project_id)
        if service is None:
            logger.info("No reflection service available for project %s", project_id)
            return []
        return await service.reflect_window(project_id)

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                if not self._running:
                    break
                await self._sweep_once()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("ReflectionRunner sweep failed")

    async def _sweep_once(self) -> None:
        try:
            project_ids = await self._project_ids_provider()
        except Exception:
            logger.exception("ReflectionRunner: project_ids_provider failed")
            return
        if not project_ids:
            return
        for project_id in project_ids:
            try:
                verdicts = await asyncio.wait_for(
                    self.run_once(project_id), timeout=self._timeout
                )
            except TimeoutError:
                logger.warning(
                    "ReflectionRunner: timeout for project %s after %ss",
                    project_id,
                    self._timeout,
                )
                await self._emit_completion(project_id, [], "timeout", None)
            except Exception:
                logger.exception(
                    "ReflectionRunner: project %s failed", project_id
                )
                await self._emit_completion(project_id, [], "failed", "reflection_run_failed")
            else:
                await self._emit_completion(project_id, verdicts, "success", None)
                if verdicts:
                    logger.info(
                        "ReflectionRunner: project %s produced %d verdict(s)",
                        project_id,
                        len(verdicts),
                    )

    async def _emit_completion(
        self,
        project_id: str,
        verdicts: list[ReflectionVerdict],
        status: Literal["success", "failed", "timeout", "unavailable"],
        error: str | None,
    ) -> None:
        if self._completion_emitter is None:
            return
        try:
            await self._completion_emitter(project_id, verdicts, status, error)
        except Exception:
            logger.exception(
                "ReflectionRunner completion emitter failed",
                extra={"project_id": project_id, "status": status},
            )


__all__ = [
    "ProjectIdsProvider",
    "ReflectionCompleteEmitter",
    "ReflectionRunner",
    "ReflectionServiceFactory",
]
