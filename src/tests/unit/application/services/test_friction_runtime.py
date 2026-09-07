"""Tests for the generation-pinned friction application facade."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.services.friction_runtime import record_lane_change
from src.domain.model.flow.friction_signal import FrictionKind, FrictionSignal
from src.infrastructure.plugins.v2 import reflection_runtime as runtime_module
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


async def test_record_lane_change_delegates_to_pinned_v2_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal = FrictionSignal(
        project_id="p1",
        task_id="t1",
        kind=FrictionKind.BOUNCE,
        source_lane="executing",
        target_lane="todo",
    )
    record = AsyncMock(return_value=signal)
    monkeypatch.setattr(
        runtime_module,
        "current_reflection_runtime_v2",
        lambda: SimpleNamespace(record_lane_change=record),
    )

    result = await record_lane_change(
        project_id="p1",
        task_id="t1",
        from_lane="executing",
        to_lane="todo",
        metadata={"workspace_id": "w1"},
    )

    assert result is signal
    record.assert_awaited_once_with(
        project_id="p1",
        task_id="t1",
        from_lane="executing",
        to_lane="todo",
        metadata={"workspace_id": "w1"},
    )


async def test_record_lane_change_fails_closed_without_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _missing():
        raise RuntimeV2Error("generation_not_pinned", "plugin generation is not pinned")

    monkeypatch.setattr(runtime_module, "current_reflection_runtime_v2", _missing)

    with pytest.raises(RuntimeV2Error) as error:
        await record_lane_change(
            project_id="p1",
            task_id="t1",
            from_lane="executing",
            to_lane="todo",
        )

    assert error.value.code == "generation_not_pinned"
