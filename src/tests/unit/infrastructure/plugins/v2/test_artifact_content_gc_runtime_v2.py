"""V2 Provider/Consumer lifecycle coverage for Artifact content orphan GC."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.storage.s3_storage_adapter import S3StorageAdapter
from src.infrastructure.plugins.v2 import artifact_content_gc_runtime as runtime_module
from src.infrastructure.plugins.v2.artifact_content_gc_runtime import (
    ARTIFACT_CONTENT_GC_MODULE_V2,
    ARTIFACT_CONTENT_GC_RUNTIME_SERVICE_V2,
    ARTIFACT_CONTENT_GC_SESSIONS_INJECT_V2,
    ARTIFACT_CONTENT_GC_STORAGE_INJECT_V2,
    ASYNC_SESSION_FACTORY_MODULE_V2,
    ASYNC_SESSION_FACTORY_SERVICE_V2,
    OBJECT_STORAGE_PROVIDER_MODULE_V2,
    OBJECT_STORAGE_SERVICE_V2,
    ArtifactContentOrphanGcRuntimeV2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_GC_ENV_KEYS = (
    "ARTIFACT_CONTENT_ORPHAN_GC_ENABLED",
    "ARTIFACT_CONTENT_ORPHAN_GC_POLL_SECONDS",
    "ARTIFACT_CONTENT_ORPHAN_GC_BATCH_SIZE",
    "ARTIFACT_CONTENT_ORPHAN_GC_LEASE_SECONDS",
)


@pytest.fixture(autouse=True)
def _clear_gc_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _GC_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


async def test_gc_runtime_survives_generation_replacement_and_stops_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_released = asyncio.Event()
    original_release = ArtifactContentOrphanGcRuntimeV2.release_generation

    async def observe_release(runtime: ArtifactContentOrphanGcRuntimeV2) -> None:
        await original_release(runtime)
        if runtime.generation_references == 1:
            old_released.set()

    monkeypatch.setattr(ArtifactContentOrphanGcRuntimeV2, "release_generation", observe_release)
    worker = MagicMock(owner_id="artifact-gc-test")
    worker.stop = AsyncMock()
    worker_type = MagicMock(return_value=worker)
    monkeypatch.setattr(runtime_module, "ArtifactContentOrphanGcWorker", worker_type)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=111,
        version=111,
    )
    assert first.accepted is True
    first_generation = host.manager.current
    assert first_generation is not None
    runtime = first_generation.resolve(
        ARTIFACT_CONTENT_GC_RUNTIME_SERVICE_V2,
        first_generation.snapshot.entries[0].scope,
    )
    assert isinstance(runtime, ArtifactContentOrphanGcRuntimeV2)

    second = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=112,
        version=112,
    )

    assert second.accepted is True
    second_generation = host.manager.current
    assert second_generation is not None
    replacement_runtime = second_generation.resolve(
        ARTIFACT_CONTENT_GC_RUNTIME_SERVICE_V2,
        second_generation.snapshot.entries[0].scope,
    )
    assert replacement_runtime is runtime
    # ACK commits the new identity; retirement drains independently afterward.
    await asyncio.wait_for(old_released.wait(), timeout=2)
    assert runtime.generation_references == 1
    worker_type.assert_called_once()
    worker.start.assert_called_once_with()
    worker.stop.assert_not_awaited()
    call = worker_type.call_args.kwargs
    assert call["session_factory"] is async_session_factory
    assert isinstance(call["storage_service"], S3StorageAdapter)
    assert call["poll_interval_seconds"] == 5.0
    assert call["batch_size"] == 10
    assert call["lease_seconds"] == 60

    await host.close()
    worker.stop.assert_awaited_once_with()
    assert runtime.generation_references == 0


async def test_gc_worker_start_failure_nacks_and_cleans_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = MagicMock(owner_id="artifact-gc-failed")
    worker.start.side_effect = RuntimeError("worker start unavailable")
    worker.stop = AsyncMock()
    monkeypatch.setattr(
        runtime_module, "ArtifactContentOrphanGcWorker", MagicMock(return_value=worker)
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=113,
        version=113,
    )

    assert publication.accepted is False
    assert publication.receipt.error_code == "staging_failed"
    assert host.manager.current is None
    worker.start.assert_called_once_with()
    worker.stop.assert_awaited_once_with()


async def test_disabled_gc_module_does_not_construct_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_type = MagicMock()
    monkeypatch.setattr(runtime_module, "ArtifactContentOrphanGcWorker", worker_type)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    def disable_gc(document):
        return replace(
            document,
            entries=tuple(
                replace(entry, config={**entry.config, "enabled": False})
                if entry.module_ref == ARTIFACT_CONTENT_GC_MODULE_V2
                else entry
                for entry in document.entries
            ),
        )

    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=114,
        version=114,
        profile_projector=disable_gc,
    )

    assert publication.accepted is True
    worker_type.assert_not_called()
    await host.close()


async def test_gc_runtime_preserves_environment_configuration_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARTIFACT_CONTENT_ORPHAN_GC_ENABLED", "true")
    monkeypatch.setenv("ARTIFACT_CONTENT_ORPHAN_GC_POLL_SECONDS", "2.5")
    monkeypatch.setenv("ARTIFACT_CONTENT_ORPHAN_GC_BATCH_SIZE", "7")
    monkeypatch.setenv("ARTIFACT_CONTENT_ORPHAN_GC_LEASE_SECONDS", "45")
    worker = MagicMock(owner_id="artifact-gc-environment")
    worker.stop = AsyncMock()
    worker_type = MagicMock(return_value=worker)
    monkeypatch.setattr(runtime_module, "ArtifactContentOrphanGcWorker", worker_type)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=115,
        version=115,
    )

    assert publication.accepted is True
    call = worker_type.call_args.kwargs
    assert call["poll_interval_seconds"] == 2.5
    assert call["batch_size"] == 7
    assert call["lease_seconds"] == 45
    await host.close()


async def test_gc_config_change_requires_process_restart_and_keeps_last_good(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = MagicMock(owner_id="artifact-gc-process-boundary")
    worker.stop = AsyncMock()
    worker_type = MagicMock(return_value=worker)
    monkeypatch.setattr(runtime_module, "ArtifactContentOrphanGcWorker", worker_type)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=116,
        version=116,
    )
    assert first.accepted is True

    def change_gc_batch_size(document):
        return replace(
            document,
            entries=tuple(
                replace(entry, config={**entry.config, "batch_size": 11})
                if entry.module_ref == ARTIFACT_CONTENT_GC_MODULE_V2
                else entry
                for entry in document.entries
            ),
        )

    rejected = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=117,
        version=117,
        profile_projector=change_gc_batch_size,
    )

    assert rejected.accepted is False
    assert rejected.receipt.error_code == "process_boundary_required"
    assert host.manager.current is not None
    assert host.manager.current.descriptor.generation == 116
    worker_type.assert_called_once()
    worker.stop.assert_not_awaited()
    await host.close()
    worker.stop.assert_awaited_once_with()


def test_gc_dependencies_and_lifecycle_are_explicit_v2_entries() -> None:
    profile = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in profile.entries}

    assert entries[ARTIFACT_CONTENT_GC_MODULE_V2].inject == {
        ARTIFACT_CONTENT_GC_SESSIONS_INJECT_V2: ASYNC_SESSION_FACTORY_SERVICE_V2,
        ARTIFACT_CONTENT_GC_STORAGE_INJECT_V2: OBJECT_STORAGE_SERVICE_V2,
    }
    assert entries[ARTIFACT_CONTENT_GC_MODULE_V2].restart_policy.value == "process-boundary"
    ordered_modules = tuple(entry.module_ref for entry in profile.entries)
    assert ordered_modules.index(ASYNC_SESSION_FACTORY_MODULE_V2) < ordered_modules.index(
        ARTIFACT_CONTENT_GC_MODULE_V2
    )
    assert ordered_modules.index(OBJECT_STORAGE_PROVIDER_MODULE_V2) < ordered_modules.index(
        ARTIFACT_CONTENT_GC_MODULE_V2
    )

    main_source = (_ROOT / "src/infrastructure/adapters/primary/web/main.py").read_text(
        encoding="utf-8"
    )
    startup_source = (
        _ROOT / "src/infrastructure/adapters/primary/web/startup/__init__.py"
    ).read_text(encoding="utf-8")
    retired_startup = (
        _ROOT / "src/infrastructure/adapters/primary/web/startup/artifact_content_orphan_gc.py"
    )
    assert "initialize_artifact_content_orphan_gc_worker" not in main_source
    assert "shutdown_artifact_content_orphan_gc_worker" not in main_source
    assert "container.storage_service()" not in main_source
    assert "artifact_content_orphan_gc" not in startup_source
    assert not retired_startup.exists()
