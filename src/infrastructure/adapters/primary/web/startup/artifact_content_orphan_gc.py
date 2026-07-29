"""Artifact content orphan GC worker startup."""

import logging
import os

from src.domain.ports.services.storage_service_port import StorageServicePort
from src.infrastructure.adapters.secondary.persistence.artifact_content_orphan_gc_worker import (
    ArtifactContentOrphanGcWorker,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

logger = logging.getLogger(__name__)

_ENABLED_ENV = "ARTIFACT_CONTENT_ORPHAN_GC_ENABLED"
_POLL_ENV = "ARTIFACT_CONTENT_ORPHAN_GC_POLL_SECONDS"
_BATCH_ENV = "ARTIFACT_CONTENT_ORPHAN_GC_BATCH_SIZE"
_LEASE_ENV = "ARTIFACT_CONTENT_ORPHAN_GC_LEASE_SECONDS"

_worker: ArtifactContentOrphanGcWorker | None = None


def _enabled() -> bool:
    raw = os.environ.get(_ENABLED_ENV)
    if raw is None:
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _positive_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value > 0 else default


async def initialize_artifact_content_orphan_gc_worker(
    *,
    storage_service: StorageServicePort,
) -> ArtifactContentOrphanGcWorker | None:
    """Start one durable bounded GC dispatcher for this API process."""
    global _worker

    if not _enabled():
        logger.info(
            "Artifact content orphan GC is disabled",
            extra={"event": "artifact_content_orphan_gc.disabled"},
        )
        return None
    if _worker is not None and _worker.is_running:
        return _worker
    if _worker is not None:
        _worker = None
    try:
        _worker = ArtifactContentOrphanGcWorker(
            session_factory=async_session_factory,
            storage_service=storage_service,
            poll_interval_seconds=_positive_float_env(_POLL_ENV, 5.0),
            batch_size=_positive_int_env(_BATCH_ENV, 10),
            lease_seconds=_positive_int_env(_LEASE_ENV, 60),
        )
        _worker.start()
    except Exception:
        logger.warning(
            "Artifact content orphan GC failed to start",
            exc_info=True,
            extra={"event": "artifact_content_orphan_gc.start_failed"},
        )
        _worker = None
        return None
    logger.info(
        "Artifact content orphan GC started",
        extra={
            "event": "artifact_content_orphan_gc.started",
            "owner_id": _worker.owner_id,
        },
    )
    return _worker


async def shutdown_artifact_content_orphan_gc_worker() -> None:
    """Stop the durable Artifact content orphan GC dispatcher."""
    global _worker
    if _worker is None:
        return
    try:
        await _worker.stop()
    except Exception:
        logger.warning(
            "Artifact content orphan GC failed to stop",
            exc_info=True,
            extra={"event": "artifact_content_orphan_gc.stop_failed"},
        )
    finally:
        _worker = None


__all__ = [
    "initialize_artifact_content_orphan_gc_worker",
    "shutdown_artifact_content_orphan_gc_worker",
]
