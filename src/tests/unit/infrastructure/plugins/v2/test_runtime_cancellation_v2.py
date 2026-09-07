"""Real Loader regressions for cancellation-safe generation ownership and drain."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace

import pytest

from src.infrastructure.plugins.v2.runtime import GenerationManagerV2, LoaderV2
from src.tests.unit.infrastructure.plugins.v2.runtime_test_support import (
    RuntimeTestArtifactResolverV2,
    target_catalog_from_snapshot_v2,
)
from src.tests.unit.infrastructure.plugins.v2.test_reconciler import _loader, _snapshot

pytestmark = pytest.mark.unit


def instrumented_loader(
    events: list[str],
    *,
    cancel_cleanup: bool = False,
    cancellation_errors: list[asyncio.CancelledError] | None = None,
    cleanup_started: asyncio.Event | None = None,
    cleanup_resume: asyncio.Event | None = None,
    apply_started: asyncio.Event | None = None,
    apply_resume: asyncio.Event | None = None,
) -> LoaderV2:
    snapshot = _snapshot()
    definitions = []
    for definition in _loader()._definitions.values():

        async def apply(context, config, definition=definition):
            async def dispose() -> None:
                events.append(f"dispose-start:{context.entry_id}")
                if cleanup_started is not None:
                    cleanup_started.set()
                if cleanup_resume is not None:
                    await cleanup_resume.wait()
                events.append(f"dispose-end:{context.entry_id}")
                if cancel_cleanup:
                    error = asyncio.CancelledError("injected disposer cancellation")
                    if cancellation_errors is not None:
                        cancellation_errors.append(error)
                    raise error

            await context.effect(lambda: dispose, label="cancellation-owned-effect")
            result = definition.apply(context, config)
            if inspect.isawaitable(result):
                result = await result
            if context.entry_id == "session-consumer" and apply_started is not None:
                apply_started.set()
                if apply_resume is not None:
                    await apply_resume.wait()
            events.append(f"apply:{context.entry_id}")
            return result

        definitions.append(replace(definition, apply=apply))
    return LoaderV2(
        definitions,
        target_catalog=target_catalog_from_snapshot_v2(snapshot),
        artifact_resolver=RuntimeTestArtifactResolverV2(),
    )


async def test_same_generation_publish_does_not_retire_or_dispose_itself() -> None:
    events: list[str] = []
    generation = await instrumented_loader(events).stage(_snapshot())
    manager = GenerationManagerV2()
    await manager.publish(generation)
    await manager.publish(generation)
    assert manager.current is generation
    assert not generation._retired
    assert not generation._disposed
    assert not any(event.startswith("dispose-") for event in events)
    await manager.close()


async def test_retirement_cancellation_drains_all_fibers_and_preserves_new_current() -> None:
    events: list[str] = []
    cancellation_errors: list[asyncio.CancelledError] = []
    previous = await instrumented_loader(
        events, cancel_cleanup=True, cancellation_errors=cancellation_errors
    ).stage(_snapshot())
    manager = GenerationManagerV2()
    await manager.publish(previous)
    next_generation = await _loader().stage(replace(_snapshot(), generation=8, digest="2" * 64))
    with pytest.raises(BaseExceptionGroup) as failure:
        await manager.publish(next_generation)
    assert len(cancellation_errors) == 2
    assert failure.value.exceptions == tuple(cancellation_errors)
    for actual, original in zip(failure.value.exceptions, cancellation_errors, strict=True):
        assert actual is original
    assert manager.current is next_generation
    assert previous._disposed
    assert all(fiber.phase.value == "disposed" for fiber in previous.fibers)
    assert [event for event in events if event.startswith("dispose-end:")] == [
        "dispose-end:session-consumer",
        "dispose-end:root-provider",
    ]
    await manager.close()


async def test_cancelling_dispose_observation_keeps_physical_cleanup_running() -> None:
    events: list[str] = []
    started, resume = asyncio.Event(), asyncio.Event()
    generation = await instrumented_loader(
        events, cleanup_started=started, cleanup_resume=resume
    ).stage(_snapshot())
    first = asyncio.create_task(generation.dispose())
    second = None
    try:
        await asyncio.wait_for(started.wait(), 1)
        first.cancel()
        second = asyncio.create_task(generation.dispose())
        await asyncio.sleep(0)
        assert not second.done()
        assert "dispose-end:session-consumer" not in events
    finally:
        resume.set()
        await asyncio.gather(first, return_exceptions=True)
        if second is not None:
            await asyncio.wait_for(second, 1)
    assert generation._disposed
    assert [event for event in events if event.startswith("dispose-end:")] == [
        "dispose-end:session-consumer",
        "dispose-end:root-provider",
    ]
    await generation.dispose()
    assert events.count("dispose-start:session-consumer") == 1


async def test_cancelled_lease_release_waiting_for_manager_lock_decrements_once() -> None:
    generation = await _loader().stage(_snapshot())
    manager = GenerationManagerV2()
    await manager.publish(generation)
    lease = await manager.acquire()
    await manager._lock.acquire()
    release = asyncio.create_task(lease.release())
    repeated = None
    try:
        await asyncio.sleep(0)
        release.cancel()
        repeated = asyncio.create_task(lease.release())
        await asyncio.sleep(0)
        assert generation._lease_count == 1
        assert not repeated.done()
    finally:
        manager._lock.release()
        await asyncio.gather(release, return_exceptions=True)
        if repeated is not None:
            await asyncio.wait_for(repeated, 1)
    assert generation._lease_count == 0
    await lease.release()
    assert generation._lease_count == 0
    await manager.close()


async def test_cancelled_apply_drains_current_registered_effects_and_previous_fibers() -> None:
    events: list[str] = []
    started, resume = asyncio.Event(), asyncio.Event()
    loader = instrumented_loader(events, apply_started=started, apply_resume=resume)
    staging = asyncio.create_task(loader.stage(_snapshot()))
    try:
        await asyncio.wait_for(started.wait(), 1)
        staging.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(staging, 1)
    finally:
        resume.set()
        if not staging.done():
            staging.cancel()
        await asyncio.gather(staging, return_exceptions=True)
    assert "apply:root-provider" in events
    assert "apply:session-consumer" not in events
    assert [event for event in events if event.startswith("dispose-end:")] == [
        "dispose-end:session-consumer",
        "dispose-end:root-provider",
    ]
