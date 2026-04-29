"""
Workspace Supervisor — WTP fan-in consumer (Phase 2).

The supervisor subscribes to a **single global Redis Stream**
``workspace:wtp:inbox`` and dispatches every :class:`WtpEnvelope` it sees
to the appropriate domain hook:

* ``task.completed`` / ``task.blocked`` → :func:`apply_workspace_worker_report`
  (idempotent via ``report_id = envelope.correlation_id``).
* ``task.progress`` / ``task.heartbeat`` → logged (Phase 5 will wire the
  watchdog; Phase 7 will emit UI events).
* Any other verb → logged at INFO and skipped.

The inbox stream is populated by the worker WTP tools
(``src/infrastructure/agent/tools/workspace_wtp.py``) as they deliver their
A2A envelopes. See :func:`publish_envelope`.

Why a dedicated fan-in stream (vs. tapping the leader session streams
directly): ``WorkspaceTaskSessionAttempt`` only stores the worker's
``conversation_id`` — the leader's session id is not tracked in the DB, so
there is no reliable way to subscribe to "all leader inbound streams" from
a workspace-scoped supervisor without a new DB column. The dedicated
workspace inbox stream sidesteps that entirely: it is a second, parallel
copy of the same envelope, created by the WTP tool layer, read only by the
supervisor. A2A traffic is unchanged.

Idempotency guarantee: every terminal verb is dispatched with
``report_id = envelope.correlation_id``. The domain function
:func:`apply_workspace_worker_report` records the fingerprint and short-
circuits repeated applications — so running the supervisor alongside the
tool-layer "belt-and-suspenders" direct call in Phase 1/2 is safe.

Not yet (future phases):

* Consumer groups (``XREADGROUP``) for multi-instance sharding — Phase 5.
* Heartbeat watchdog + stale attempt re-dispatch — Phase 5.
* ``AgentDomainEvent`` emission for real-time UI — Phase 7.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from typing import Any, Protocol

from src.domain.model.workspace.wtp_envelope import (
    WtpEnvelope,
    WtpValidationError,
    WtpVerb,
)

logger = logging.getLogger(__name__)

WORKSPACE_WTP_INBOX_STREAM = "workspace:wtp:inbox"
DEFAULT_MAXLEN = 10_000
DEFAULT_BLOCK_MS = 5_000

# --- Phase 5: watchdog defaults ---------------------------------------------
# How long an attempt may go without ANY inbound WTP traffic (progress /
# heartbeat / terminal) before the watchdog flips it to blocked. Set to 0
# to disable the watchdog entirely.
DEFAULT_STALE_SECONDS = int(os.getenv("WORKSPACE_ATTEMPT_STALE_SECONDS", "180"))
# How often the watchdog wakes up to scan the in-memory liveness map.
DEFAULT_WATCHDOG_INTERVAL_SECONDS = float(
    os.getenv("WORKSPACE_ATTEMPT_WATCHDOG_INTERVAL_SECONDS", "30")
)


# --- Phase 7: Prometheus metrics (soft import) ------------------------------

try:  # pragma: no cover - exercised in prod runtime
    from prometheus_client import Counter  # type: ignore[import-untyped]

    _WTP_VERB_COUNTER = Counter(
        "memstack_wtp_envelopes_total",
        "Total WTP envelopes processed by the supervisor, labeled by verb.",
        labelnames=("verb", "source"),
    )
    _WTP_STALE_COUNTER = Counter(
        "memstack_wtp_stale_attempts_total",
        "Total attempts flipped to blocked by the liveness watchdog.",
    )
except Exception:  # pragma: no cover - keep supervisor importable without prom
    _WTP_VERB_COUNTER = None  # type: ignore[assignment]
    _WTP_STALE_COUNTER = None  # type: ignore[assignment]


def _count_verb(verb: WtpVerb, *, source: str) -> None:
    if _WTP_VERB_COUNTER is None:
        return
    with contextlib.suppress(Exception):
        _WTP_VERB_COUNTER.labels(verb=verb.value, source=source).inc()


def _count_stale() -> None:
    if _WTP_STALE_COUNTER is None:
        return
    with contextlib.suppress(Exception):
        _WTP_STALE_COUNTER.inc()


class _RedisLike(Protocol):
    """Minimal redis.asyncio client surface the supervisor uses."""

    async def xadd(
        self,
        name: str,
        fields: dict[str, Any],
        *,
        maxlen: int | None = ...,
        approximate: bool = ...,
    ) -> Any: ...  # noqa: ANN401

    async def xread(
        self,
        streams: dict[str, str],
        *,
        count: int | None = ...,
        block: int | None = ...,
    ) -> Any: ...  # noqa: ANN401


# --- Publishing ---------------------------------------------------------------


async def publish_envelope(
    redis_client: _RedisLike | None,
    envelope: WtpEnvelope,
    *,
    maxlen: int = DEFAULT_MAXLEN,
) -> str | None:
    """
    XADD the envelope onto the workspace inbox stream.

    Returns the stream entry id on success, ``None`` if the write failed or
    no Redis client is available. Failure is NEVER raised — the supervisor
    is an observer; publishing should not break the worker's critical path.
    """
    if redis_client is None:
        return None
    try:
        body = json.dumps(envelope.to_dict(), ensure_ascii=False)
        entry_id = await redis_client.xadd(
            WORKSPACE_WTP_INBOX_STREAM,
            {"data": body},
            maxlen=maxlen,
            approximate=True,
        )
        return str(entry_id) if entry_id is not None else None
    except Exception:
        logger.exception(
            "workspace_supervisor.publish_envelope failed (verb=%s task=%s)",
            envelope.verb.value,
            envelope.task_id,
        )
        return None


# --- Supervisor ---------------------------------------------------------------


class WorkspaceSupervisor:
    """
    Single-consumer fan-in loop for the workspace WTP inbox stream.

    Lifecycle:

    * :meth:`start` spawns a long-running asyncio task that XREADs the
      inbox stream from ``$`` (new entries only) with a block timeout.
    * :meth:`stop` cancels the task and awaits graceful exit.

    The supervisor is process-local; a single instance per FastAPI process
    is sufficient for Phase 2. Multi-instance deployments will add consumer
    groups in Phase 5.
    """

    def __init__(
        self,
        redis_client: _RedisLike | None,
        *,
        stream: str = WORKSPACE_WTP_INBOX_STREAM,
        block_ms: int = DEFAULT_BLOCK_MS,
        stale_seconds: int = DEFAULT_STALE_SECONDS,
        watchdog_interval_seconds: float = DEFAULT_WATCHDOG_INTERVAL_SECONDS,
    ) -> None:
        self._redis = redis_client
        self._stream = stream
        self._block_ms = block_ms
        self._task: asyncio.Task[None] | None = None
        self._watchdog_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._last_id: str = "$"
        # Phase 5 liveness state: attempt_id → {last_seen, envelope snapshot}.
        self._liveness: dict[str, dict[str, Any]] = {}
        # Terminal WTP envelopes are authoritative for process-local liveness:
        # delayed launch-owned heartbeats must not resurrect a completed attempt.
        self._terminal_attempts: set[str] = set()
        self._stale_seconds = max(0, int(stale_seconds))
        self._watchdog_interval = max(1.0, float(watchdog_interval_seconds))

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def get_liveness_snapshot(self) -> dict[str, dict[str, Any]]:
        """Return a deep copy of the liveness table (for health checks / tests)."""
        return {k: dict(v) for k, v in self._liveness.items()}

    async def start(self) -> None:
        """Begin consuming. Safe to call multiple times (idempotent)."""
        if self._redis is None:
            logger.warning(
                "WorkspaceSupervisor.start skipped: no Redis client available"
            )
            return
        if self.is_running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run_loop(), name="workspace-supervisor"
        )
        if self._stale_seconds > 0 and self._watchdog_task is None:
            self._watchdog_task = asyncio.create_task(
                self._watchdog_loop(), name="workspace-supervisor-watchdog"
            )
        logger.info(
            "WorkspaceSupervisor started (stream=%s block_ms=%d stale_seconds=%d)",
            self._stream,
            self._block_ms,
            self._stale_seconds,
        )

    async def stop(self) -> None:
        """Signal the loop to exit and await the task."""
        self._stop_event.set()
        for task in (self._task, self._watchdog_task):
            if task is None:
                continue
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._task = None
        self._watchdog_task = None
        logger.info("WorkspaceSupervisor stopped")

    # --- Internal loop ---------------------------------------------------

    async def _run_loop(self) -> None:
        assert self._redis is not None
        while not self._stop_event.is_set():
            try:
                resp = await self._redis.xread(
                    {self._stream: self._last_id},
                    count=32,
                    block=self._block_ms,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("workspace_supervisor xread failed; backing off")
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=2.0)
                    return
                except TimeoutError:
                    continue

            if not resp:
                continue

            # Redis client returns: [(stream_name, [(entry_id, {fields}), ...])]
            for _stream_name, entries in resp:
                for entry_id, fields in entries:
                    self._last_id = (
                        entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
                    )
                    await self._dispatch_entry(self._last_id, fields)

    async def _dispatch_entry(
        self, entry_id: str, fields: dict[Any, Any]
    ) -> None:
        """Parse one stream entry and route to the domain sink."""
        try:
            raw = fields.get("data") or fields.get(b"data")
            if isinstance(raw, bytes):
                raw = raw.decode()
            if not raw:
                logger.debug("workspace_supervisor: empty entry %s", entry_id)
                return
            data = json.loads(raw)
            envelope = WtpEnvelope.from_dict(data)
        except (WtpValidationError, json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning(
                "workspace_supervisor: unparseable entry %s (%s): %s",
                entry_id,
                type(exc).__name__,
                exc,
            )
            return

        try:
            await self._dispatch_envelope(envelope)
        except Exception:
            logger.exception(
                "workspace_supervisor: dispatch failed (verb=%s task=%s)",
                envelope.verb.value,
                envelope.task_id,
            )

    async def _dispatch_envelope(self, envelope: WtpEnvelope) -> None:
        """Route an envelope to the correct domain handler."""
        verb = envelope.verb
        _count_verb(verb, source="supervisor")

        if envelope.attempt_id in self._terminal_attempts and verb not in WtpVerb.terminal():
            self._liveness.pop(envelope.attempt_id, None)
            logger.debug(
                "workspace_supervisor ignored post-terminal %s for attempt=%s",
                verb.value,
                envelope.attempt_id,
            )
            return

        # Phase 5: every inbound envelope refreshes the attempt's liveness.
        if envelope.attempt_id:
            self._liveness[envelope.attempt_id] = {
                "last_seen_monotonic": time.monotonic(),
                "workspace_id": envelope.workspace_id,
                "task_id": envelope.task_id,
                "root_goal_task_id": envelope.root_goal_task_id or "",
                "leader_agent_id": envelope.extra_metadata.get("leader_agent_id")
                or "",
                "worker_agent_id": envelope.extra_metadata.get("worker_agent_id")
                or "",
                "actor_user_id": envelope.extra_metadata.get("actor_user_id") or "",
                "worker_conversation_id": envelope.extra_metadata.get(
                    "worker_conversation_id"
                )
                or "",
                "last_verb": verb.value,
            }

        if verb in WtpVerb.terminal():
            # Terminal envelope removes the attempt from liveness tracking.
            if envelope.attempt_id:
                self._liveness.pop(envelope.attempt_id, None)
                self._terminal_attempts.add(envelope.attempt_id)
            await self._apply_terminal(envelope)
            return
        if verb is WtpVerb.TASK_PROGRESS:
            logger.info(
                "wtp.progress workspace=%s task=%s attempt=%s summary=%s",
                envelope.workspace_id,
                envelope.task_id,
                envelope.attempt_id,
                envelope.payload.get("summary"),
            )
            return
        if verb is WtpVerb.TASK_HEARTBEAT:
            logger.debug(
                "wtp.heartbeat workspace=%s task=%s",
                envelope.workspace_id,
                envelope.task_id,
            )
            return
        if verb is WtpVerb.TASK_CLARIFY_RESPONSE:
            try:
                from src.infrastructure.agent.tools.workspace_clarification import (
                    deliver_clarification_response,
                )

                delivered = deliver_clarification_response(envelope)
                logger.info(
                    "wtp.clarify_response correlation=%s delivered=%s",
                    envelope.correlation_id,
                    delivered,
                )
            except Exception:
                logger.exception(
                    "workspace_supervisor: failed delivering clarify_response "
                    "correlation=%s",
                    envelope.correlation_id,
                )
            return
        logger.info(
            "wtp.%s received (workspace=%s task=%s)",
            verb.value,
            envelope.workspace_id,
            envelope.task_id,
        )

    async def _watchdog_loop(self) -> None:
        """Phase 5: scan liveness table and flip stale attempts to blocked."""
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._watchdog_interval
                    )
                    return
                except TimeoutError:
                    pass
                try:
                    await self._watchdog_tick()
                except Exception:
                    logger.exception("workspace_supervisor watchdog tick failed")
        except asyncio.CancelledError:
            raise

    async def _watchdog_tick(self) -> None:
        """Inspect liveness table once; flip stale attempts to blocked."""
        if self._stale_seconds <= 0:
            return
        now = time.monotonic()
        stale: list[tuple[str, dict[str, Any]]] = []
        for attempt_id, info in list(self._liveness.items()):
            last_seen = info.get("last_seen_monotonic")
            if not isinstance(last_seen, int | float):
                continue
            if now - last_seen < self._stale_seconds:
                continue
            stale.append((attempt_id, info))

        for attempt_id, info in stale:
            self._liveness.pop(attempt_id, None)
            await self._apply_stale_attempt(attempt_id, info)

    async def _apply_stale_attempt(
        self, attempt_id: str, info: dict[str, Any]
    ) -> None:
        """Record a ``blocked`` terminal report for a stale attempt."""
        from src.infrastructure.agent.workspace.workspace_goal_runtime import (
            apply_workspace_worker_report,
        )

        if not await self._attempt_is_still_running(attempt_id):
            self._terminal_attempts.add(attempt_id)
            logger.info(
                "workspace_supervisor.watchdog skipped terminal attempt=%s task=%s",
                attempt_id,
                info.get("task_id"),
            )
            return

        summary = f"stale_no_heartbeat (last_verb={info.get('last_verb')})"
        try:
            await apply_workspace_worker_report(
                workspace_id=str(info.get("workspace_id") or ""),
                root_goal_task_id=str(info.get("root_goal_task_id") or ""),
                task_id=str(info.get("task_id") or ""),
                attempt_id=attempt_id,
                conversation_id=str(info.get("worker_conversation_id") or ""),
                actor_user_id=str(info.get("actor_user_id") or ""),
                worker_agent_id=str(info.get("worker_agent_id") or ""),
                report_type="blocked",
                summary=summary,
                artifacts=None,
                leader_agent_id=(
                    str(info["leader_agent_id"])
                    if info.get("leader_agent_id")
                    else None
                ),
                report_id=f"watchdog:{attempt_id}",
            )
            _count_stale()
            logger.warning(
                "workspace_supervisor.watchdog flipped attempt=%s task=%s to blocked (stale)",
                attempt_id,
                info.get("task_id"),
            )
        except Exception:
            logger.exception(
                "workspace_supervisor.watchdog failed to apply stale report "
                "(attempt=%s task=%s)",
                attempt_id,
                info.get("task_id"),
            )

    async def _attempt_is_still_running(self, attempt_id: str) -> bool:
        """Return whether durable state still considers this attempt running."""
        if not attempt_id:
            return False
        try:
            from sqlalchemy import select

            from src.domain.model.workspace.workspace_task_session_attempt import (
                WorkspaceTaskSessionAttemptStatus,
            )
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.models import (
                WorkspaceTaskSessionAttemptModel,
            )

            async with async_session_factory() as session:
                result = await session.execute(
                    select(WorkspaceTaskSessionAttemptModel.status).where(
                        WorkspaceTaskSessionAttemptModel.id == attempt_id
                    )
                )
                status = result.scalar_one_or_none()
            return status == WorkspaceTaskSessionAttemptStatus.RUNNING.value
        except Exception:
            logger.warning(
                "workspace_supervisor.watchdog attempt status lookup failed",
                exc_info=True,
                extra={"attempt_id": attempt_id},
            )
            return True

    async def _apply_terminal(self, envelope: WtpEnvelope) -> None:
        """Invoke :func:`apply_workspace_worker_report` for terminal verbs."""
        from src.infrastructure.agent.workspace.workspace_goal_runtime import (
            apply_workspace_worker_report,
        )

        report_type = (
            "completed" if envelope.verb is WtpVerb.TASK_COMPLETED else "blocked"
        )
        payload = envelope.payload
        summary = str(
            payload.get("summary")
            or payload.get("reason")
            or ""
        )
        if not summary:
            summary = f"WTP {envelope.verb.value} (no summary)"
        evidence = payload.get("evidence")
        if report_type == "blocked" and isinstance(evidence, str) and evidence:
            summary = f"{summary}\n\n{evidence}"
        artifacts_raw = payload.get("artifacts")
        artifacts: list[str] | None = None
        if isinstance(artifacts_raw, list):
            artifacts = [a for a in artifacts_raw if isinstance(a, str) and a]
            artifacts = artifacts or None

        leader_agent_id = envelope.extra_metadata.get("leader_agent_id")
        worker_agent_id = envelope.extra_metadata.get("worker_agent_id") or ""
        actor_user_id = envelope.extra_metadata.get("actor_user_id") or ""
        conversation_id = envelope.extra_metadata.get("worker_conversation_id") or ""

        try:
            await apply_workspace_worker_report(
                workspace_id=envelope.workspace_id,
                root_goal_task_id=envelope.root_goal_task_id or "",
                task_id=envelope.task_id,
                attempt_id=envelope.attempt_id,
                conversation_id=conversation_id,
                actor_user_id=actor_user_id,
                worker_agent_id=worker_agent_id,
                report_type=report_type,
                summary=summary,
                artifacts=artifacts,
                leader_agent_id=leader_agent_id
                if isinstance(leader_agent_id, str)
                else None,
                report_id=envelope.correlation_id,
            )
            logger.info(
                "workspace_supervisor applied %s for task=%s attempt=%s",
                report_type,
                envelope.task_id,
                envelope.attempt_id,
            )
        except Exception:
            logger.exception(
                "workspace_supervisor: apply_workspace_worker_report failed "
                "(task=%s verb=%s)",
                envelope.task_id,
                envelope.verb.value,
            )


# --- Global accessor --------------------------------------------------------

_supervisor: WorkspaceSupervisor | None = None


def set_workspace_supervisor(supervisor: WorkspaceSupervisor | None) -> None:
    """Record the process-wide supervisor (called from FastAPI lifespan)."""
    global _supervisor
    _supervisor = supervisor


def get_workspace_supervisor() -> WorkspaceSupervisor | None:
    """Return the process-wide supervisor, or ``None`` if not initialised."""
    return _supervisor


# Redis client injected separately so the WTP tools can publish even when
# the supervisor itself is disabled (degraded-mode: worker still delivers
# A2A + direct apply; supervisor fan-in just doesn't run).
_publish_redis: _RedisLike | None = None


def configure_wtp_publisher(redis_client: _RedisLike | None) -> None:
    """Inject the Redis client used by :func:`publish_envelope_default`."""
    global _publish_redis
    _publish_redis = redis_client


def get_wtp_publisher_redis() -> _RedisLike | None:
    return _publish_redis


async def publish_envelope_default(envelope: WtpEnvelope) -> str | None:
    """Convenience wrapper used by the worker WTP tools."""
    return await publish_envelope(_publish_redis, envelope)


__all__ = [
    "DEFAULT_BLOCK_MS",
    "DEFAULT_MAXLEN",
    "WORKSPACE_WTP_INBOX_STREAM",
    "WorkspaceSupervisor",
    "configure_wtp_publisher",
    "get_workspace_supervisor",
    "get_wtp_publisher_redis",
    "publish_envelope",
    "publish_envelope_default",
    "set_workspace_supervisor",
]
