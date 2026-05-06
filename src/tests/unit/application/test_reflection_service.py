"""Unit tests for ``ReflectionService`` + in-memory friction ledger / playbook
repository.

Verifies:
- Friction ingestion is pure pass-through.
- Lane-change derivation flags backward moves and ignores forward moves.
- ``reflect_window`` calls the reflector with the windowed signals + existing
  playbooks and applies CREATE / REINFORCE / DEPRECATE / NOOP correctly.
- Subjective verdicts always come from the reflector port — the service
  itself never invents them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import override

import pytest

from src.application.services.reflection_service import ReflectionService
from src.domain.model.flow.friction_signal import FrictionKind, FrictionSignal
from src.domain.model.flow.playbook import Playbook, PlaybookStatus, TriggerPattern
from src.domain.model.flow.reflection_verdict import ReflectionAction, ReflectionVerdict
from src.domain.ports.services.reflector_port import ReflectorPort
from src.infrastructure.adapters.secondary.in_memory.friction_loop import (
    InMemoryFrictionLedger,
    InMemoryPlaybookRepository,
)

pytestmark = pytest.mark.unit


class FixedReflector(ReflectorPort):
    """Reflector stub returning a pre-canned verdict list."""

    def __init__(self, verdicts: list[ReflectionVerdict]) -> None:
        self.verdicts = verdicts
        self.calls: list[dict[str, object]] = []

    @override
    async def reflect(
        self,
        *,
        project_id: str,
        signals: list[FrictionSignal],
        existing_playbooks: list[Playbook],
    ) -> list[ReflectionVerdict]:
        self.calls.append(
            {
                "project_id": project_id,
                "signal_count": len(signals),
                "playbook_count": len(existing_playbooks),
            }
        )
        return list(self.verdicts)


class TestFrictionIngestion:
    async def test_ingest_friction_appends_to_ledger(self) -> None:
        ledger = InMemoryFrictionLedger()
        service = ReflectionService(
            ledger=ledger,
            playbooks=InMemoryPlaybookRepository(),
            reflector=FixedReflector([]),
        )
        signal = FrictionSignal(
            project_id="p1",
            task_id="t1",
            kind=FrictionKind.RETRY,
        )

        await service.ingest_friction(signal)

        stored = await ledger.query_window("p1")
        assert len(stored) == 1
        assert stored[0].task_id == "t1"
        assert stored[0].kind is FrictionKind.RETRY


class TestLaneChangeDerivation:
    async def test_backward_move_is_bounce(self) -> None:
        service = ReflectionService(
            ledger=InMemoryFrictionLedger(),
            playbooks=InMemoryPlaybookRepository(),
            reflector=FixedReflector([]),
        )
        signal = await service.derive_signal_from_lane_change(
            project_id="p1",
            task_id="t1",
            from_lane="dev",
            to_lane="todo",
            lane_order=["backlog", "todo", "dev", "review", "done"],
        )
        assert signal is not None
        assert signal.kind is FrictionKind.BOUNCE
        assert signal.source_lane == "dev"
        assert signal.target_lane == "todo"

    async def test_forward_move_returns_none(self) -> None:
        service = ReflectionService(
            ledger=InMemoryFrictionLedger(),
            playbooks=InMemoryPlaybookRepository(),
            reflector=FixedReflector([]),
        )
        signal = await service.derive_signal_from_lane_change(
            project_id="p1",
            task_id="t1",
            from_lane="todo",
            to_lane="dev",
            lane_order=["backlog", "todo", "dev", "review", "done"],
        )
        assert signal is None

    async def test_unknown_lane_returns_none(self) -> None:
        service = ReflectionService(
            ledger=InMemoryFrictionLedger(),
            playbooks=InMemoryPlaybookRepository(),
            reflector=FixedReflector([]),
        )
        signal = await service.derive_signal_from_lane_change(
            project_id="p1",
            task_id="t1",
            from_lane="dev",
            to_lane="unknown_lane",
            lane_order=["backlog", "todo", "dev"],
        )
        assert signal is None


class TestReflectWindow:
    async def test_no_signals_returns_empty(self) -> None:
        reflector = FixedReflector([])
        service = ReflectionService(
            ledger=InMemoryFrictionLedger(),
            playbooks=InMemoryPlaybookRepository(),
            reflector=reflector,
        )
        result = await service.reflect_window("p1")
        assert result == []
        assert reflector.calls == []  # reflector not called when no signals

    async def test_create_verdict_persists_new_playbook(self) -> None:
        ledger = InMemoryFrictionLedger()
        playbooks = InMemoryPlaybookRepository()
        reflector = FixedReflector(
            [
                ReflectionVerdict(
                    action=ReflectionAction.CREATE,
                    playbook_id=None,
                    rationale="Recurring lint failures detected",
                    proposed_playbook={
                        "name": "Run formatter before commit",
                        "trigger": {
                            "description": "code_diff bounces from review->dev",
                            "friction_kinds": ["bounce"],
                            "lane_transitions": [["review", "dev"]],
                        },
                        "steps": [
                            {"order": 0, "instruction": "Run make format"},
                            {"order": 1, "instruction": "Re-run failing tests"},
                        ],
                    },
                )
            ]
        )
        service = ReflectionService(
            ledger=ledger, playbooks=playbooks, reflector=reflector
        )
        await ledger.append(
            FrictionSignal(project_id="p1", task_id="t1", kind=FrictionKind.BOUNCE)
        )

        applied = await service.reflect_window("p1")

        assert len(applied) == 1
        stored = await playbooks.find_by_project("p1")
        assert len(stored) == 1
        assert stored[0].name == "Run formatter before commit"
        assert stored[0].status is PlaybookStatus.ACTIVE
        assert len(stored[0].steps) == 2
        assert stored[0].trigger.friction_kinds == ("bounce",)

    async def test_reinforce_verdict_increments_hit_count(self) -> None:
        ledger = InMemoryFrictionLedger()
        playbooks = InMemoryPlaybookRepository()
        existing = Playbook(
            project_id="p1",
            name="existing",
            trigger=TriggerPattern(description="x"),
            status=PlaybookStatus.ACTIVE,
            hit_count=2,
        )
        await playbooks.save(existing)
        reflector = FixedReflector(
            [
                ReflectionVerdict(
                    action=ReflectionAction.REINFORCE,
                    playbook_id=existing.id,
                    rationale="pattern continues to occur",
                )
            ]
        )
        service = ReflectionService(
            ledger=ledger, playbooks=playbooks, reflector=reflector
        )
        await ledger.append(
            FrictionSignal(project_id="p1", task_id="t1", kind=FrictionKind.BOUNCE)
        )

        applied = await service.reflect_window("p1")
        assert len(applied) == 1
        updated = await playbooks.find_by_id(existing.id)
        assert updated is not None
        assert updated.hit_count == 3

    async def test_deprecate_verdict_changes_status(self) -> None:
        ledger = InMemoryFrictionLedger()
        playbooks = InMemoryPlaybookRepository()
        existing = Playbook(
            project_id="p1",
            name="stale",
            trigger=TriggerPattern(description="x"),
            status=PlaybookStatus.ACTIVE,
        )
        await playbooks.save(existing)
        reflector = FixedReflector(
            [
                ReflectionVerdict(
                    action=ReflectionAction.DEPRECATE,
                    playbook_id=existing.id,
                    rationale="pattern no longer relevant",
                )
            ]
        )
        service = ReflectionService(
            ledger=ledger, playbooks=playbooks, reflector=reflector
        )
        await ledger.append(
            FrictionSignal(project_id="p1", task_id="t1", kind=FrictionKind.BOUNCE)
        )

        applied = await service.reflect_window("p1")
        assert len(applied) == 1
        updated = await playbooks.find_by_id(existing.id)
        assert updated is not None
        assert updated.status is PlaybookStatus.DEPRECATED

    async def test_noop_verdict_does_nothing(self) -> None:
        ledger = InMemoryFrictionLedger()
        playbooks = InMemoryPlaybookRepository()
        reflector = FixedReflector(
            [ReflectionVerdict(action=ReflectionAction.NOOP, playbook_id=None, rationale="all good")]
        )
        service = ReflectionService(
            ledger=ledger, playbooks=playbooks, reflector=reflector
        )
        await ledger.append(
            FrictionSignal(project_id="p1", task_id="t1", kind=FrictionKind.BOUNCE)
        )

        applied = await service.reflect_window("p1")
        assert applied == []
        stored = await playbooks.find_by_project("p1")
        assert stored == []

    async def test_window_filters_old_signals(self) -> None:
        ledger = InMemoryFrictionLedger()
        playbooks = InMemoryPlaybookRepository()
        reflector = FixedReflector([])
        service = ReflectionService(
            ledger=ledger,
            playbooks=playbooks,
            reflector=reflector,
            window_minutes=60,  # 1h window
        )
        # Old signal (2h ago) should be excluded
        await ledger.append(
            FrictionSignal(
                project_id="p1",
                task_id="old",
                kind=FrictionKind.BOUNCE,
                observed_at=datetime.now(UTC) - timedelta(hours=2),
            )
        )

        await service.reflect_window("p1")
        # Reflector should NOT be called: no signals in window
        assert reflector.calls == []
