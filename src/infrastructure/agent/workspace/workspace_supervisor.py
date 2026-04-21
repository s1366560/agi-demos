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
import json
import logging
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


class _RedisLike(Protocol):
    """Minimal redis.asyncio client surface the supervisor uses."""

    async def xadd(
        self,
        name: str,
        fields: dict[str, Any],
        *,
        maxlen: int | None = ...,
        approximate: bool = ...,
    ) -> Any: ...

    async def xread(
        self,
        streams: dict[str, str],
        *,
        count: int | None = ...,
        block: int | None = ...,
    ) -> Any: ...


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
    ) -> None:
        self._redis = redis_client
        self._stream = stream
        self._block_ms = block_ms
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._last_id: str = "$"

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

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
        logger.info(
            "WorkspaceSupervisor started (stream=%s block_ms=%d)",
            self._stream,
            self._block_ms,
        )

    async def stop(self) -> None:
        """Signal the loop to exit and await the task."""
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        finally:
            self._task = None
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
                except asyncio.TimeoutError:
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
        if verb in WtpVerb.terminal():
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
        logger.info(
            "wtp.%s received (workspace=%s task=%s) — no Phase 2 handler",
            verb.value,
            envelope.workspace_id,
            envelope.task_id,
        )

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
