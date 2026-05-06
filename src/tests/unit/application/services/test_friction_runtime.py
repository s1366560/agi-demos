"""Unit tests for ``src.application.services.friction_runtime``."""

from __future__ import annotations

import pytest

from src.application.services.friction_runtime import (
    configure_friction_ingest,
    record_lane_change,
    reset_friction_ingest,
)
from src.domain.model.flow.friction_signal import FrictionKind
from src.infrastructure.adapters.secondary.in_memory.friction_loop import (
    InMemoryFrictionLedger,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_friction_ingest()
    yield
    reset_friction_ingest()


@pytest.mark.unit
async def test_record_lane_change_noop_without_configuration() -> None:
    sig = await record_lane_change(
        project_id="p1",
        task_id="t1",
        from_lane="executing",
        to_lane="todo",
    )
    assert sig is None


@pytest.mark.unit
async def test_record_lane_change_emits_bounce_on_backward_move() -> None:
    ledger = InMemoryFrictionLedger()
    configure_friction_ingest(
        ledger,
        lane_order=("todo", "dispatched", "executing", "done"),
    )

    sig = await record_lane_change(
        project_id="p1",
        task_id="t1",
        from_lane="executing",
        to_lane="todo",
    )

    assert sig is not None
    assert sig.kind is FrictionKind.BOUNCE
    assert sig.source_lane == "executing"
    assert sig.target_lane == "todo"
    assert sig.project_id == "p1"


@pytest.mark.unit
async def test_record_lane_change_silent_on_forward_move() -> None:
    ledger = InMemoryFrictionLedger()
    configure_friction_ingest(
        ledger,
        lane_order=("todo", "dispatched", "executing", "done"),
    )

    sig = await record_lane_change(
        project_id="p1",
        task_id="t1",
        from_lane="todo",
        to_lane="executing",
    )

    assert sig is None


@pytest.mark.unit
async def test_record_lane_change_silent_on_unknown_lane() -> None:
    ledger = InMemoryFrictionLedger()
    configure_friction_ingest(
        ledger,
        lane_order=("todo", "done"),
    )

    sig = await record_lane_change(
        project_id="p1",
        task_id="t1",
        from_lane="executing",  # not in lane_order
        to_lane="todo",
    )

    assert sig is None


@pytest.mark.unit
async def test_record_lane_change_swallows_ledger_failure() -> None:
    class _FailingLedger:
        async def append(self, _signal: object) -> None:
            raise RuntimeError("boom")

        async def query_window(self, *_args: object, **_kwargs: object) -> list[object]:
            return []

    configure_friction_ingest(
        _FailingLedger(),  # type: ignore[arg-type]
        lane_order=("todo", "dispatched", "executing", "done"),
    )

    # Must not raise, must return None.
    sig = await record_lane_change(
        project_id="p1",
        task_id="t1",
        from_lane="executing",
        to_lane="todo",
    )
    assert sig is None
