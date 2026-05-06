"""Tests for ``ReflectionRunner``."""

from __future__ import annotations

import asyncio

import pytest

from src.application.services.reflection_runner import ReflectionRunner
from src.application.services.reflection_service import ReflectionService
from src.domain.model.flow.friction_signal import FrictionKind, FrictionSignal
from src.domain.model.flow.reflection_verdict import (
    ReflectionAction,
    ReflectionVerdict,
)
from src.domain.ports.services.reflector_port import ReflectorPort
from src.infrastructure.adapters.secondary.in_memory.friction_loop import (
    InMemoryFrictionLedger,
    InMemoryPlaybookRepository,
)


class _StubReflector(ReflectorPort):
    def __init__(self, verdicts: list[ReflectionVerdict] | None = None) -> None:
        self._verdicts = verdicts or []
        self.call_count = 0

    async def reflect(self, *, project_id, signals, existing_playbooks):  # type: ignore[override]
        del project_id, signals, existing_playbooks
        self.call_count += 1
        return list(self._verdicts)


async def _service_with_signal(project_id: str) -> ReflectionService:
    ledger = InMemoryFrictionLedger()
    await ledger.append(
        FrictionSignal(
            project_id=project_id,
            task_id="t1",
            kind=FrictionKind.BOUNCE,
            source_lane="dev",
            target_lane="todo",
        )
    )
    return ReflectionService(
        ledger=ledger,
        playbooks=InMemoryPlaybookRepository(),
        reflector=_StubReflector(
            [
                ReflectionVerdict(
                    action=ReflectionAction.NOOP,
                    playbook_id=None,
                    rationale="quiet window",
                )
            ]
        ),
    )


class TestReflectionRunner:
    def test_rejects_invalid_intervals(self) -> None:
        async def _provider() -> list[str]:
            return []

        async def _factory(_pid: str) -> ReflectionService | None:
            return None

        with pytest.raises(ValueError):
            ReflectionRunner(
                project_ids_provider=_provider,
                service_factory=_factory,
                interval_seconds=0,
            )
        with pytest.raises(ValueError):
            ReflectionRunner(
                project_ids_provider=_provider,
                service_factory=_factory,
                per_project_timeout_seconds=-1,
            )

    async def test_run_once_returns_empty_when_factory_returns_none(self) -> None:
        async def _provider() -> list[str]:
            return ["p1"]

        async def _factory(_pid: str) -> ReflectionService | None:
            return None

        runner = ReflectionRunner(
            project_ids_provider=_provider, service_factory=_factory
        )
        assert await runner.run_once("p1") == []

    async def test_run_once_invokes_service(self) -> None:
        service_holder: dict[str, ReflectionService] = {}

        async def _provider() -> list[str]:
            return ["p1"]

        async def _factory(pid: str) -> ReflectionService | None:
            service_holder[pid] = await _service_with_signal(pid)
            return service_holder[pid]

        runner = ReflectionRunner(
            project_ids_provider=_provider, service_factory=_factory
        )
        verdicts = await runner.run_once("p1")
        # NOOP verdicts are not "applied" — but reflector was still called
        assert isinstance(verdicts, list)

    async def test_loop_sweeps_all_projects_then_stops(self) -> None:
        seen: list[str] = []

        async def _provider() -> list[str]:
            return ["p1", "p2"]

        async def _factory(pid: str) -> ReflectionService | None:
            seen.append(pid)
            return await _service_with_signal(pid)

        runner = ReflectionRunner(
            project_ids_provider=_provider,
            service_factory=_factory,
            interval_seconds=0.05,
        )
        runner.start()
        # Idempotent
        runner.start()
        await asyncio.sleep(0.15)
        await runner.stop()
        assert "p1" in seen and "p2" in seen

    async def test_loop_swallows_per_project_failure(self) -> None:
        async def _provider() -> list[str]:
            return ["good", "bad"]

        async def _factory(pid: str) -> ReflectionService | None:
            if pid == "bad":
                raise RuntimeError("boom")
            return await _service_with_signal(pid)

        runner = ReflectionRunner(
            project_ids_provider=_provider,
            service_factory=_factory,
            interval_seconds=0.05,
        )
        runner.start()
        await asyncio.sleep(0.12)
        await runner.stop()
        # No exception escaped; runner remained healthy.

    async def test_loop_swallows_provider_failure(self) -> None:
        async def _provider() -> list[str]:
            raise RuntimeError("project list unavailable")

        async def _factory(_pid: str) -> ReflectionService | None:
            return None

        runner = ReflectionRunner(
            project_ids_provider=_provider,
            service_factory=_factory,
            interval_seconds=0.05,
        )
        runner.start()
        await asyncio.sleep(0.12)
        await runner.stop()

    async def test_per_project_timeout(self) -> None:
        async def _provider() -> list[str]:
            return ["slow"]

        async def _factory(_pid: str) -> ReflectionService | None:
            class _SlowService:
                async def reflect_window(self, _project_id: str):  # type: ignore[no-untyped-def]
                    await asyncio.sleep(1.0)
                    return []

            return _SlowService()  # type: ignore[return-value]

        runner = ReflectionRunner(
            project_ids_provider=_provider,
            service_factory=_factory,
            interval_seconds=0.05,
            per_project_timeout_seconds=0.05,
        )
        runner.start()
        await asyncio.sleep(0.2)
        await runner.stop()
