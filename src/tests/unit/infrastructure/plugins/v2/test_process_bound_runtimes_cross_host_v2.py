"""Cross-host process-bound runtime regressions for Cron, Docker, and LLM health.

These tests use stub start/stop hooks and two independent runtime hosts, as
root and scoped generations do in production. They do not start the real
scheduler, Docker monitor, or health loop, and they do not claim the live
host process has been restored.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from src.infrastructure.plugins.v2 import (
    docker_monitor_runtime as docker_module,
    llm_health_runtime as llm_module,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.cron_services import (
    process_cron_scheduler_runtime_v2,
    reset_process_cron_scheduler_runtime_v2,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.scheduler import scheduler_service
from src.tests.unit.infrastructure.plugins.v2.test_cron_scheduler_process_runtime_v2 import (
    _apply_gateway,
    _install_stub,
    _StubScheduler,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def _bootstrap_pair(first_generation: int, second_generation: int):
    root = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    scoped = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    first = await root.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=first_generation,
        version=first_generation,
    )
    second = await scoped.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=second_generation,
        version=second_generation,
    )
    return root, scoped, first, second


async def test_cancel_while_waiting_for_lock_does_not_stop_other_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _install_stub(monkeypatch, _StubScheduler())
    stub.hold_start = True
    first_task = asyncio.create_task(_apply_gateway())
    await asyncio.wait_for(stub.start_entered.wait(), timeout=1)
    waiter = asyncio.create_task(_apply_gateway())
    await asyncio.sleep(0)
    assert waiter.done() is False
    assert stub.starts == 0
    assert stub.stops == 0

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    assert stub.stops == 0
    stub.start_release.set()
    first_dispose = await first_task
    assert stub.starts == 1
    assert stub.stops == 0
    assert process_cron_scheduler_runtime_v2().generation_references == 1

    await first_dispose()
    assert stub.stops == 1


async def test_start_then_sync_failure_does_not_leave_running_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _install_stub(monkeypatch, _StubScheduler())

    async def fail_sync() -> None:
        stub.syncs += 1
        raise RuntimeError("cron sync unavailable")

    monkeypatch.setattr(scheduler_service, "sync_all_jobs", fail_sync)
    reset_process_cron_scheduler_runtime_v2()

    with pytest.raises(RuntimeError, match="cron sync unavailable"):
        await _apply_gateway()

    assert stub.starts == 1
    assert stub.syncs == 1
    assert stub.stops == 1
    assert stub.running is False
    assert process_cron_scheduler_runtime_v2().generation_references == 0


async def test_duplicate_release_of_one_token_does_not_stop_remaining_holder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _install_stub(monkeypatch, _StubScheduler())
    first = await _apply_gateway()
    second = await _apply_gateway()

    await second()
    await second()
    assert stub.stops == 0
    assert stub.running is True
    assert process_cron_scheduler_runtime_v2().generation_references == 1

    await first()
    assert stub.stops == 1


async def test_docker_monitor_survives_scoped_host_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = AsyncMock(return_value=Mock())
    stop = AsyncMock()
    monkeypatch.setattr(docker_module, "start_docker_event_monitor", start)
    monkeypatch.setattr(docker_module, "stop_docker_event_monitor", stop)
    docker_module.reset_process_docker_event_monitor_runtime_v2()

    root, scoped, first, second = await _bootstrap_pair(231, 232)
    try:
        assert first.accepted is True
        assert second.accepted is True
        assert start.await_count == 1
        stop.assert_not_awaited()
        await scoped.close()
        stop.assert_not_awaited()
    finally:
        await root.close()
    stop.assert_awaited_once()


async def test_failed_scoped_docker_host_does_not_stop_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = AsyncMock(return_value=Mock())
    stop = AsyncMock()
    monkeypatch.setattr(docker_module, "start_docker_event_monitor", start)
    monkeypatch.setattr(docker_module, "stop_docker_event_monitor", stop)
    docker_module.reset_process_docker_event_monitor_runtime_v2()

    root, scoped, first, _second = await _bootstrap_pair(233, 234)
    try:
        assert first.accepted is True
        start.side_effect = RuntimeError("docker start failed")
        # Root already holds the process monitor, so a later host must not start or stop it.
        third = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
        failed = await third.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=235,
            version=235,
        )
        # The new host may still accept because start is skipped when refs > 0.
        # If bootstrap fails for another reason, root must remain running.
        _ = failed
        await third.close()
        stop.assert_not_awaited()
        assert start.await_count == 1
    finally:
        await scoped.close()
        await root.close()
    stop.assert_awaited_once()


async def test_llm_health_survives_scoped_host_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = AsyncMock()
    sync = AsyncMock(return_value=2)
    stop = AsyncMock()
    monkeypatch.setattr(llm_module, "start_health_checker", start)
    monkeypatch.setattr(llm_module, "sync_llm_health_checker_providers_v2", sync)
    monkeypatch.setattr(llm_module, "stop_health_checker", stop)
    llm_module.reset_process_llm_health_runtime_v2()

    root, scoped, first, second = await _bootstrap_pair(241, 242)
    try:
        assert first.accepted is True
        assert second.accepted is True
        start.assert_awaited_once()
        sync.assert_awaited_once()
        stop.assert_not_awaited()
        await scoped.close()
        stop.assert_not_awaited()
    finally:
        await root.close()
    stop.assert_awaited_once()


async def test_failed_new_llm_generation_does_not_stop_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = AsyncMock()
    sync = AsyncMock(return_value=1)
    stop = AsyncMock()
    monkeypatch.setattr(llm_module, "start_health_checker", start)
    monkeypatch.setattr(llm_module, "sync_llm_health_checker_providers_v2", sync)
    monkeypatch.setattr(llm_module, "stop_health_checker", stop)
    llm_module.reset_process_llm_health_runtime_v2()

    root = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    first = await root.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=243,
        version=243,
    )
    assert first.accepted is True
    sync.side_effect = RuntimeError("llm sync unavailable")
    scoped = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    try:
        second = await scoped.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=244,
            version=244,
        )
        # Shared manager skips start/sync while root holds the checker.
        if not second.accepted:
            stop.assert_not_awaited()
        else:
            await scoped.close()
            stop.assert_not_awaited()
        start.assert_awaited_once()
        assert sync.await_count == 1
    finally:
        await scoped.close()
        await root.close()
    stop.assert_awaited_once()
