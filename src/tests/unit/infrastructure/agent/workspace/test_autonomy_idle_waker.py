"""Unit tests for WorkspaceAutonomyIdleWaker (P2b)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.services.workspace_autonomy_idle_waker import (
    WorkspaceAutonomyIdleWaker,
)


class _FakeSessionContext:
    """Async context manager that yields a fake session with an execute() result."""

    def __init__(self, rows: list[tuple[str, str, str]]) -> None:
        self._rows = rows
        self._result = MagicMock()
        self._result.all.return_value = rows
        self.session = MagicMock()
        self.session.execute = AsyncMock(return_value=self._result)

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, *_a: object) -> None:
        return None


def _fake_factory(rows: list[tuple[str, str, str]]) -> Any:
    """Return a callable that emulates ``async_session_factory()``."""
    ctx = _FakeSessionContext(rows)
    return lambda: ctx


class TestValidation:
    def test_invalid_interval_raises(self) -> None:
        with pytest.raises(ValueError, match="check_interval_seconds must be > 0"):
            WorkspaceAutonomyIdleWaker(
                check_interval_seconds=0,
                session_factory=_fake_factory([]),
                schedule_tick=lambda _w, _u: None,
            )


class TestSweepOnce:
    @pytest.mark.asyncio
    async def test_schedules_tick_for_each_eligible_row(self) -> None:
        rows = [("ws-1", "user-a", "root-1"), ("ws-2", "user-b", "root-2")]
        scheduled: list[tuple[str, str]] = []

        waker = WorkspaceAutonomyIdleWaker(
            check_interval_seconds=60,
            session_factory=_fake_factory(rows),
            schedule_tick=lambda ws, uid: scheduled.append((ws, uid)),
        )
        nudged = await waker._sweep_once()
        assert nudged == 2
        assert scheduled == [("ws-1", "user-a"), ("ws-2", "user-b")]

    @pytest.mark.asyncio
    async def test_empty_result_no_schedule(self) -> None:
        scheduled: list[tuple[str, str]] = []
        waker = WorkspaceAutonomyIdleWaker(
            check_interval_seconds=60,
            session_factory=_fake_factory([]),
            schedule_tick=lambda ws, uid: scheduled.append((ws, uid)),
        )
        nudged = await waker._sweep_once()
        assert nudged == 0
        assert scheduled == []

    @pytest.mark.asyncio
    async def test_schedule_failure_does_not_abort_sweep(self) -> None:
        rows = [("ws-1", "u1", "r1"), ("ws-2", "u2", "r2"), ("ws-3", "u3", "r3")]
        scheduled: list[tuple[str, str]] = []

        def flaky(ws: str, uid: str) -> None:
            if ws == "ws-2":
                msg = "boom"
                raise RuntimeError(msg)
            scheduled.append((ws, uid))

        waker = WorkspaceAutonomyIdleWaker(
            check_interval_seconds=60,
            session_factory=_fake_factory(rows),
            schedule_tick=flaky,
        )
        nudged = await waker._sweep_once()
        # ws-2 failed; ws-1 and ws-3 succeeded (not counted as nudged because exception path)
        assert nudged == 2
        assert scheduled == [("ws-1", "u1"), ("ws-3", "u3")]


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_then_stop_clean(self) -> None:
        waker = WorkspaceAutonomyIdleWaker(
            check_interval_seconds=60,
            session_factory=_fake_factory([]),
            schedule_tick=lambda _w, _u: None,
        )
        waker.start()
        assert waker._task is not None
        assert waker._running is True
        await waker.stop()
        assert waker._task is None
        assert waker._running is False

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self) -> None:
        waker = WorkspaceAutonomyIdleWaker(
            check_interval_seconds=60,
            session_factory=_fake_factory([]),
            schedule_tick=lambda _w, _u: None,
        )
        waker.start()
        first = waker._task
        waker.start()
        assert waker._task is first
        await waker.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start_noop(self) -> None:
        waker = WorkspaceAutonomyIdleWaker(
            check_interval_seconds=60,
            session_factory=_fake_factory([]),
            schedule_tick=lambda _w, _u: None,
        )
        await waker.stop()
        assert waker._task is None

    @pytest.mark.asyncio
    async def test_loop_surfaces_sweep_to_schedule(self) -> None:
        rows = [("ws-loop", "u-loop", "r-loop")]
        called = asyncio.Event()

        def on_tick(ws: str, uid: str) -> None:
            assert ws == "ws-loop"
            assert uid == "u-loop"
            called.set()

        waker = WorkspaceAutonomyIdleWaker(
            check_interval_seconds=1,
            session_factory=_fake_factory(rows),
            schedule_tick=on_tick,
        )
        waker.start()
        try:
            await asyncio.wait_for(called.wait(), timeout=1.0)
        finally:
            await waker.stop()


class TestStartupWrapper:
    """Lightweight tests for the env-flag helpers in the startup wrapper."""

    def test_enabled_default_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WORKSPACE_AUTONOMY_IDLE_WAKE_ENABLED", raising=False)
        from src.infrastructure.adapters.primary.web.startup import autonomy_waker as mod

        assert mod._enabled() is False

    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
    def test_enabled_truthy(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv("WORKSPACE_AUTONOMY_IDLE_WAKE_ENABLED", val)
        from src.infrastructure.adapters.primary.web.startup import autonomy_waker as mod

        assert mod._enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
    def test_enabled_falsy(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv("WORKSPACE_AUTONOMY_IDLE_WAKE_ENABLED", val)
        from src.infrastructure.adapters.primary.web.startup import autonomy_waker as mod

        assert mod._enabled() is False

    def test_interval_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WORKSPACE_AUTONOMY_IDLE_WAKE_INTERVAL_SECONDS", raising=False)
        from src.infrastructure.adapters.primary.web.startup import autonomy_waker as mod

        assert mod._interval_seconds() == 300

    def test_interval_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WORKSPACE_AUTONOMY_IDLE_WAKE_INTERVAL_SECONDS", "45")
        from src.infrastructure.adapters.primary.web.startup import autonomy_waker as mod

        assert mod._interval_seconds() == 45

    @pytest.mark.parametrize("val", ["0", "-10", "abc", ""])
    def test_interval_invalid_falls_back(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv("WORKSPACE_AUTONOMY_IDLE_WAKE_INTERVAL_SECONDS", val)
        from src.infrastructure.adapters.primary.web.startup import autonomy_waker as mod

        assert mod._interval_seconds() == 300

    @pytest.mark.asyncio
    async def test_initialize_skipped_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WORKSPACE_AUTONOMY_IDLE_WAKE_ENABLED", "false")
        from src.infrastructure.adapters.primary.web.startup import autonomy_waker as mod

        result = await mod.initialize_autonomy_idle_waker()
        assert result is None
        assert mod._idle_waker is None

    @pytest.mark.asyncio
    async def test_shutdown_without_instance_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.infrastructure.adapters.primary.web.startup import autonomy_waker as mod

        monkeypatch.setattr(mod, "_idle_waker", None)
        await mod.shutdown_autonomy_idle_waker()  # must not raise


# Silence unused-import warning on AsyncIterator (kept for future async-gen tests)
_ = AsyncIterator
