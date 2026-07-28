"""Artifact content orphan GC startup lifecycle tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.adapters.primary.web.startup import artifact_content_orphan_gc


@pytest.fixture(autouse=True)
def reset_worker_state(monkeypatch):
    monkeypatch.setattr(artifact_content_orphan_gc, "_worker", None)


@pytest.mark.unit
async def test_artifact_content_orphan_gc_startup_honors_bounded_configuration(
    monkeypatch,
) -> None:
    storage = MagicMock()
    worker = MagicMock()
    worker.is_running = False
    worker.owner_id = "worker-test"
    worker.stop = AsyncMock()
    monkeypatch.setenv("ARTIFACT_CONTENT_ORPHAN_GC_ENABLED", "true")
    monkeypatch.setenv("ARTIFACT_CONTENT_ORPHAN_GC_POLL_SECONDS", "2.5")
    monkeypatch.setenv("ARTIFACT_CONTENT_ORPHAN_GC_BATCH_SIZE", "7")
    monkeypatch.setenv("ARTIFACT_CONTENT_ORPHAN_GC_LEASE_SECONDS", "45")

    with patch.object(
        artifact_content_orphan_gc,
        "ArtifactContentOrphanGcWorker",
        return_value=worker,
    ) as worker_type:
        started = await artifact_content_orphan_gc.initialize_artifact_content_orphan_gc_worker(
            storage_service=storage,
        )

    assert started is worker
    worker_type.assert_called_once_with(
        session_factory=artifact_content_orphan_gc.async_session_factory,
        storage_service=storage,
        poll_interval_seconds=2.5,
        batch_size=7,
        lease_seconds=45,
    )
    worker.start.assert_called_once_with()

    await artifact_content_orphan_gc.shutdown_artifact_content_orphan_gc_worker()
    worker.stop.assert_awaited_once_with()
    assert artifact_content_orphan_gc._worker is None


@pytest.mark.unit
async def test_artifact_content_orphan_gc_startup_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACT_CONTENT_ORPHAN_GC_ENABLED", "false")

    with patch.object(
        artifact_content_orphan_gc,
        "ArtifactContentOrphanGcWorker",
    ) as worker_type:
        started = await artifact_content_orphan_gc.initialize_artifact_content_orphan_gc_worker(
            storage_service=MagicMock(),
        )

    assert started is None
    worker_type.assert_not_called()
