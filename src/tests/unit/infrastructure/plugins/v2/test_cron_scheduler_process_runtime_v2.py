"""Isolated Cron scheduler generation-refcount behavior for process-bound start/stop.

These tests use a stub scheduler and do not start the real APScheduler, connect
live PostgreSQL/Redis/queues, or claim that the current host process has been
restored end-to-end.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.cron_services import (
    cron_scheduler_gateway_definition_v2,
    process_cron_scheduler_runtime_v2,
    reset_process_cron_scheduler_runtime_v2,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.scheduler import scheduler_service

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_GATEWAY_CONFIG = {"strategy": "builtin-scheduler-bridge"}


class _StubScheduler:
    """Process-bound start/sync/stop with optional barriers for interleaving."""

    def __init__(self) -> None:
        self.starts = 0
        self.syncs = 0
        self.stops = 0
        self.running = False
        self.start_entered = asyncio.Event()
        self.start_release = asyncio.Event()
        self.hold_start = False

    async def start(self) -> object:
        self.start_entered.set()
        if self.hold_start:
            await self.start_release.wait()
        self.starts += 1
        self.running = True
        return object()

    async def sync(self) -> None:
        self.syncs += 1

    async def stop(self) -> None:
        self.stops += 1
        self.running = False


class _StubContext:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self.provided: list[str] = []
        self._error = error

    def provide(self, service: str, _value: object, **_kwargs: Any) -> None:
        if self._error is not None:
            raise self._error
        self.provided.append(service)


def _install_stub(monkeypatch: pytest.MonkeyPatch, stub: _StubScheduler) -> _StubScheduler:
    monkeypatch.setattr(scheduler_service, "start_scheduler", stub.start)
    monkeypatch.setattr(scheduler_service, "sync_all_jobs", stub.sync)
    monkeypatch.setattr(scheduler_service, "stop_scheduler", stub.stop)
    reset_process_cron_scheduler_runtime_v2()
    return stub


async def _apply_gateway(context: _StubContext | None = None) -> Any:
    definition = cron_scheduler_gateway_definition_v2()
    result = definition.apply(context or _StubContext(), _GATEWAY_CONFIG)
    if asyncio.iscoroutine(result):
        return await result
    return result


def test_definition_factories_share_one_process_runtime() -> None:
    reset_process_cron_scheduler_runtime_v2()
    first = process_cron_scheduler_runtime_v2()
    _ = cron_scheduler_gateway_definition_v2()
    second = process_cron_scheduler_runtime_v2()
    _ = cron_scheduler_gateway_definition_v2()

    assert first is second
    assert process_cron_scheduler_runtime_v2() is first


async def test_successful_new_generation_keeps_scheduler_when_old_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _install_stub(monkeypatch, _StubScheduler())
    root = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    scoped = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    first = await root.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=201,
        version=201,
    )
    second = await scoped.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=202,
        version=202,
    )
    assert first.accepted is True
    assert second.accepted is True
    assert stub.starts == 1
    assert stub.syncs == 1
    assert stub.running is True

    await scoped.close()
    assert stub.stops == 0
    assert stub.running is True

    await root.close()
    assert stub.stops == 1
    assert stub.running is False


async def test_failed_new_generation_does_not_release_old(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _install_stub(monkeypatch, _StubScheduler())
    first_dispose = await _apply_gateway()
    assert stub.running is True

    with pytest.raises(RuntimeError, match="staging provide failed"):
        await _apply_gateway(_StubContext(error=RuntimeError("staging provide failed")))

    assert stub.stops == 0
    assert stub.running is True
    assert process_cron_scheduler_runtime_v2().generation_references == 1

    await first_dispose()
    assert stub.stops == 1
    assert stub.running is False


async def test_duplicate_release_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _install_stub(monkeypatch, _StubScheduler())
    dispose = await _apply_gateway()

    await dispose()
    await dispose()
    await dispose()

    assert stub.starts == 1
    assert stub.stops == 1
    assert stub.running is False
    assert process_cron_scheduler_runtime_v2().generation_references == 0


async def test_last_generation_release_stops_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _install_stub(monkeypatch, _StubScheduler())
    first = await _apply_gateway()
    second = await _apply_gateway()

    await first()
    assert stub.stops == 0
    assert stub.running is True

    await second()
    assert stub.stops == 1
    assert stub.running is False


async def test_overlapping_acquire_uses_one_start_under_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _install_stub(monkeypatch, _StubScheduler())
    stub.hold_start = True
    first_task = asyncio.create_task(_apply_gateway())
    await asyncio.wait_for(stub.start_entered.wait(), timeout=1)
    second_task = asyncio.create_task(_apply_gateway())
    await asyncio.sleep(0)
    assert stub.starts == 0
    assert second_task.done() is False

    stub.start_release.set()
    first_dispose, second_dispose = await asyncio.gather(first_task, second_task)

    assert stub.starts == 1
    assert stub.syncs == 1
    assert stub.stops == 0
    assert process_cron_scheduler_runtime_v2().generation_references == 2

    await second_dispose()
    assert stub.stops == 0
    await first_dispose()
    assert stub.stops == 1


async def test_cancel_during_first_start_cleans_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _install_stub(monkeypatch, _StubScheduler())
    stub.hold_start = True
    task = asyncio.create_task(_apply_gateway())
    await asyncio.wait_for(stub.start_entered.wait(), timeout=1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert stub.starts == 0
    assert stub.stops == 1
    assert stub.running is False
    assert process_cron_scheduler_runtime_v2().generation_references == 0


async def test_cancel_during_new_generation_does_not_stop_old(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _install_stub(monkeypatch, _StubScheduler())
    first_dispose = await _apply_gateway()

    with pytest.raises(asyncio.CancelledError):
        await _apply_gateway(_StubContext(error=asyncio.CancelledError()))

    assert stub.stops == 0
    assert stub.running is True
    assert process_cron_scheduler_runtime_v2().generation_references == 1

    await first_dispose()
    assert stub.stops == 1


async def test_same_generation_rollback_keeps_other_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _install_stub(monkeypatch, _StubScheduler())
    kept = await _apply_gateway()
    rolled_back = await _apply_gateway()

    await rolled_back()
    assert stub.stops == 0
    assert stub.running is True

    await kept()
    assert stub.stops == 1
