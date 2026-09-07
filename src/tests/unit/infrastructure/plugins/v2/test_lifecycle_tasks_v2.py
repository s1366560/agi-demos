"""Physical cleanup survives cancelled observers and replays its cached outcome."""

from __future__ import annotations

import asyncio
import gc

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.lifecycle_tasks import OwnedLifecycleTaskV2
from src.infrastructure.plugins.v2.runtime import OperationContextV2
from src.infrastructure.plugins.v2.runtime_context import (
    ContextV2,
    FiberPhaseV2,
    RuntimeV2Error,
    _EffectStack,
    _EventBusV2,
    _ProviderStore,
)
from src.tests.unit.infrastructure.plugins.v2.test_reconciler import _loader, _snapshot

pytestmark = pytest.mark.unit


def _context() -> tuple[ContextV2, _EffectStack]:
    effects = _EffectStack(lambda: FiberPhaseV2.ACTIVE)
    context = ContextV2(
        entry_id="lifecycle-test",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
        providers=_ProviderStore(),
        events=_EventBusV2(),
        effects=effects,
        privileged=True,
    )
    return context, effects


async def test_manual_and_stack_disposal_wait_for_one_physical_cleanup() -> None:
    context, effects = _context()
    entered = asyncio.Event()
    finish = asyncio.Event()
    calls: list[str] = []

    async def physical_cleanup() -> None:
        calls.append("blocked")
        entered.set()
        await finish.wait()

    def earlier_cleanup() -> None:
        calls.append("earlier")

    await context.effect(lambda: earlier_cleanup, label="earlier")
    manual = effects.add(physical_cleanup, label="blocked")

    async def dispose_manually() -> None:
        result = manual()
        assert result is not None
        await result

    first = asyncio.create_task(dispose_manually())
    await asyncio.wait_for(entered.wait(), timeout=2)
    second = asyncio.create_task(dispose_manually())
    stack_drain = asyncio.create_task(effects.dispose())
    await asyncio.sleep(0)
    assert not first.done()
    assert not second.done()
    assert not stack_drain.done()
    assert calls == ["blocked"]
    finish.set()
    await asyncio.wait_for(asyncio.gather(first, second, stack_drain), timeout=2)
    await dispose_manually()
    await effects.dispose()
    assert calls == ["blocked", "earlier"]


async def test_cancelled_waiter_and_dropped_owner_cannot_cancel_physical_cleanup() -> None:
    entered = asyncio.Event()
    finish = asyncio.Event()
    settled = asyncio.Event()
    cancelled: list[bool] = []

    async def physical_cleanup() -> None:
        entered.set()
        try:
            await finish.wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
        settled.set()

    owner = OwnedLifecycleTaskV2(physical_cleanup, name="test-detached-cleanup")
    waiter = asyncio.create_task(owner.wait())
    await asyncio.wait_for(entered.wait(), timeout=2)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    del waiter
    del owner
    gc.collect()
    assert not settled.is_set()
    assert not cancelled
    finish.set()
    await asyncio.wait_for(settled.wait(), timeout=2)
    assert not cancelled


async def test_ordinary_cleanup_exception_remains_diagnostic_and_lifo_continues() -> None:
    context, effects = _context()
    calls: list[str] = []

    def first() -> None:
        calls.append("first")

    def failed() -> None:
        calls.append("failed")
        raise ValueError("expected diagnostic")

    await context.effect(lambda: first, label="first")
    await context.effect(lambda: failed, label="failed")
    await effects.dispose()
    await effects.dispose()
    assert calls == ["failed", "first"]
    assert effects.diagnostics()[1].error == "ValueError: expected diagnostic"


async def test_unprintable_base_exception_preserves_original_identity_on_repeat() -> None:
    class UnprintableFailure(BaseException):
        def __str__(self) -> str:
            raise ValueError("diagnostic cannot format")

    context, effects = _context()
    original = UnprintableFailure()
    calls: list[str] = []

    def cleanup() -> None:
        calls.append("cleanup")
        raise original

    await context.effect(lambda: cleanup, label="unprintable")
    for _ in range(2):
        with pytest.raises(UnprintableFailure) as raised:
            await effects.dispose()
        assert raised.value is original
    assert calls == ["cleanup"]
    assert effects.diagnostics()[0].error == "plugin effect cleanup failed"


async def test_effect_registration_is_rejected_once_physical_drain_begins() -> None:
    context, effects = _context()
    entered = asyncio.Event()
    finish = asyncio.Event()
    late_setup_calls: list[str] = []

    async def cleanup() -> None:
        entered.set()
        await finish.wait()

    def late_setup() -> None:
        late_setup_calls.append("late")

    await context.effect(lambda: cleanup, label="blocked")
    drain = asyncio.create_task(effects.dispose())
    await asyncio.wait_for(entered.wait(), timeout=2)
    try:
        with pytest.raises(RuntimeV2Error, match="inactive context"):
            await context.effect(late_setup, label="late")
        assert not late_setup_calls
    finally:
        finish.set()
        await asyncio.wait_for(drain, timeout=2)


async def test_disposer_self_cancellation_is_replayed_without_rerunning_disposer() -> None:
    original = asyncio.CancelledError("disposer self cancellation")
    calls: list[str] = []

    async def cleanup() -> None:
        calls.append("cleanup")
        raise original

    owner = OwnedLifecycleTaskV2(cleanup, name="test-self-cancelled-cleanup")
    for _ in range(2):
        with pytest.raises(asyncio.CancelledError) as raised:
            await owner.wait()
        assert raised.value is original
    assert calls == ["cleanup"]


async def test_operation_dispose_closes_admission_before_owned_drain_is_scheduled() -> None:
    generation = await _loader().stage(_snapshot())
    operation = OperationContextV2(
        generation=generation,
        operation_id="immediate-admission-stop",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    late_setup_calls: list[str] = []

    def late_setup() -> None:
        late_setup_calls.append("late")

    await operation.__aenter__()
    drain = asyncio.create_task(operation.dispose())
    # The public dispose coroutine runs before this continuation, while the
    # cleanup task it creates is queued after this continuation.
    await asyncio.sleep(0)
    try:
        with pytest.raises(RuntimeV2Error) as raised:
            await operation.effect(late_setup, label="late")
        assert raised.value.code == "inactive_effect"
        assert operation.phase is FiberPhaseV2.UNLOADING
        assert not late_setup_calls
    finally:
        await asyncio.wait_for(drain, timeout=2)
        await generation.dispose()
